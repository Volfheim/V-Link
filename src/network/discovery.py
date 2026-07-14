"""
V-Link - Discovery Service
mDNS/Zeroconf device discovery.
"""

import asyncio
import ipaddress
import json
import os
import re
import socket
import subprocess
import time
from typing import Callable, Dict, List, Optional

try:
    import ifaddr
except Exception:  # pragma: no cover - zeroconf normally installs ifaddr
    ifaddr = None

from zeroconf import ServiceInfo, ServiceListener, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
try:
    from zeroconf import InterfaceChoice, IPVersion
except Exception:  # pragma: no cover - compatibility for older zeroconf
    InterfaceChoice = None
    IPVersion = None

from version import __version__


SERVICE_TYPE = "_vlink._tcp.local."
SERVICE_NAME = "V-Link"
SERVICE_INFO_RETRIES = 2
SERVICE_INFO_TIMEOUT = 1500  # ms
COMPAT_UDP_PORT = 39555
COMPAT_ANNOUNCE_INTERVAL = 4.0
COMPAT_PROBE_INTERVAL = 18.0
COMPAT_DEVICE_TTL = 35.0
MDNS_REMOVE_GRACE = 6.0


class _CompatDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, discovery: "DeviceDiscovery"):
        self.discovery = discovery

    def datagram_received(self, data: bytes, addr):
        asyncio.create_task(self.discovery._on_compat_datagram(data, addr))


class DeviceDiscovery:
    """Device discovery with registration and pausable browsing."""

    VPN_IFACE_MARKERS = (
        "vpn",
        "wireguard",
        "wintun",
        "openvpn",
        "tap-",
        "tun",
        "ppp",
        "hamachi",
        "zerotier",
        "tailscale",
        "nordlynx",
        "forti",
        "anyconnect",
        "windscribe",
    )
    VIRTUAL_IFACE_MARKERS = (
        "hyper-v",
        "vethernet",
        "wsl",
        "virtual",
        "vmware",
        "virtualbox",
        "docker",
        "bluetooth",
        "loopback",
        "npcap",
    )

    def __init__(self, port: int = 8765, compatibility_mode: bool = False):
        self.port = port
        self.compatibility_mode = compatibility_mode
        self.zeroconf: Optional[AsyncZeroconf] = None
        self.browser: Optional[AsyncServiceBrowser] = None
        self.service_info: Optional[ServiceInfo] = None
        self.devices: Dict[str, Dict] = {}
        self._running = False

        self._local_ips: List[str] = []
        self._local_ip: Optional[str] = None
        self._scan_cursor: Dict[str, int] = {}
        self._port_scan_cursor = 0

        self._compat_transport = None
        self._compat_protocol: Optional[_CompatDatagramProtocol] = None
        self._compat_announce_task: Optional[asyncio.Task] = None
        self._compat_probe_task: Optional[asyncio.Task] = None
        self._compat_probe_lock = asyncio.Lock()
        self._mdns_remove_tasks: Dict[str, asyncio.Task] = {}

        self.on_device_added: Optional[Callable] = None
        self.on_device_removed: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

    def _is_valid_local_ip(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return False
        return True

    def _is_private_ip(self, ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    def _is_hotspot_ip(self, ip: str) -> bool:
        return str(ip).startswith("192.168.137.")

    def _is_hotspot_environment(self) -> bool:
        return any(self._is_hotspot_ip(ip) for ip in self.get_local_ips())

    @staticmethod
    def _is_valid_local_ip_static(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return False
        return True

    @classmethod
    def _is_vpn_iface_name(cls, iface_name: str) -> bool:
        probe = str(iface_name or "").lower()
        return any(marker in probe for marker in cls.VPN_IFACE_MARKERS)

    @classmethod
    def _is_virtual_iface_name(cls, iface_name: str) -> bool:
        probe = str(iface_name or "").lower()
        return any(marker in probe for marker in cls.VIRTUAL_IFACE_MARKERS)

    @classmethod
    def _interface_ipv4_records(cls) -> List[tuple[str, str, int]]:
        records: List[tuple[str, str, int]] = []
        seen: set[tuple[str, str]] = set()

        if ifaddr is not None:
            try:
                for adapter in ifaddr.get_adapters():
                    name = str(adapter.nice_name or adapter.name or "")
                    for item in adapter.ips:
                        ip = item.ip
                        if not isinstance(ip, str) or not cls._is_valid_local_ip_static(ip):
                            continue
                        key = (name, ip)
                        if key in seen:
                            continue
                        try:
                            prefix = int(item.network_prefix)
                        except (TypeError, ValueError):
                            prefix = 24
                        records.append((name, ip, min(32, max(0, prefix))))
                        seen.add(key)
            except Exception:
                records = []
                seen.clear()

        if records:
            return records

        for name, ip in cls._windows_interface_ip_pairs():
            if cls._is_valid_local_ip_static(ip) and (name, ip) not in seen:
                records.append((name, ip, 24))
                seen.add((name, ip))
        return records

    @classmethod
    def _lan_interface_records(cls) -> List[tuple[str, str, int]]:
        records = cls._interface_ipv4_records()
        physical = [
            record
            for record in records
            if not cls._is_vpn_iface_name(record[0])
            and not cls._is_virtual_iface_name(record[0])
        ]
        selected = physical or records

        def record_rank(record: tuple[str, str, int]) -> tuple[int, str]:
            ip = record[1]
            if ip.startswith("192.168.137."):
                return (0, ip)
            if ip.startswith("192.168."):
                return (1, ip)
            if ip.startswith("10."):
                return (2, ip)
            if ip.startswith("172."):
                return (3, ip)
            return (4, ip)

        return sorted(selected, key=record_rank)

    @classmethod
    def _windows_interface_ip_pairs(cls, timeout_sec: float = 1.8) -> List[tuple[str, str]]:
        if os.name != "nt":
            return []

        pairs: List[tuple[str, str]] = []
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            proc = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=timeout_sec,
                check=False,
            )
            output = proc.stdout or ""
            current_iface = ""
            for raw in output.splitlines():
                line = raw.rstrip()
                if not line:
                    continue
                stripped = line.strip()
                if stripped.endswith(":") and "." not in stripped:
                    current_iface = stripped[:-1]
                    continue
                if "IPv4" not in line or ":" not in line:
                    continue
                candidate = line.split(":", 1)[1].strip()
                if candidate:
                    pairs.append((current_iface, candidate))
        except Exception:
            pass
        return pairs

    @classmethod
    def detect_vpn_environment(cls) -> bool:
        for iface_name, ip, _prefix in cls._interface_ipv4_records():
            if cls._is_vpn_iface_name(iface_name) and cls._is_valid_local_ip_static(ip):
                return True
        return False

    @classmethod
    def detect_multi_network_environment(cls) -> bool:
        """
        Heuristic: if host has >=2 distinct private /24 subnets simultaneously,
        it's likely multi-homed (e.g. LAN + VPN/TUN). Enable compatibility mode.
        """
        subnets: set[str] = set()
        for _iface_name, ip, _prefix in cls._interface_ipv4_records():
            if not cls._is_valid_local_ip_static(ip):
                continue
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if not addr.is_private:
                continue
            parts = ip.split(".")
            if len(parts) == 4:
                subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
        return len(subnets) >= 2

    def _list_local_ipv4(self) -> List[str]:
        interface_ips = []
        for _name, ip, _prefix in self._lan_interface_records():
            if ip not in interface_ips:
                interface_ips.append(ip)
        if interface_ips:
            return interface_ips

        ips: set[str] = set()

        # Default route candidate (often current active interface).
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        except Exception:
            pass
        finally:
            s.close()

        # Hostname-based candidates.
        try:
            _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
            ips.update(host_ips)
        except Exception:
            pass

        # getaddrinfo candidates.
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(item[4][0])
        except Exception:
            pass

        # Windows fallback: parse all interface IPv4 (helps when VPN changes route).
        for _iface_name, candidate in self._windows_interface_ip_pairs(timeout_sec=1.8):
            ips.add(candidate)

        filtered = [ip for ip in ips if self._is_valid_local_ip(ip)]

        def ip_rank(ip: str) -> tuple[int, str]:
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                return (9, ip)
            if not addr.is_private:
                return (8, ip)
            if self._is_hotspot_ip(ip):
                return (0, ip)  # Windows mobile hotspot subnet
            if ip.startswith("192.168."):
                return (1, ip)  # typical home LAN
            if ip.startswith("10."):
                return (2, ip)
            if ip.startswith("172."):
                return (3, ip)  # often VPN or corporate segment
            return (4, ip)

        filtered.sort(key=ip_rank)
        return filtered

    def _local_networks(self) -> List[ipaddress.IPv4Network]:
        local_ips = set(self.get_local_ips())
        networks: List[ipaddress.IPv4Network] = []
        seen: set[str] = set()
        for _name, ip, prefix in self._lan_interface_records():
            if ip not in local_ips:
                continue
            try:
                network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
            except ValueError:
                continue
            key = str(network)
            if key not in seen:
                networks.append(network)
                seen.add(key)

        if not networks:
            for ip in local_ips:
                try:
                    networks.append(ipaddress.ip_network(f"{ip}/24", strict=False))
                except ValueError:
                    continue
        return networks

    def get_local_ips(self) -> List[str]:
        if not self._local_ips:
            self._local_ips = self._list_local_ipv4()
            self._local_ip = self._local_ips[0] if self._local_ips else "127.0.0.1"
        return list(self._local_ips)

    def get_local_ip(self) -> str:
        if not self._local_ip:
            self.get_local_ips()
        return self._local_ip or "127.0.0.1"

    def get_hostname(self) -> str:
        return socket.gethostname()

    def _is_self_candidate(self, name: str, port: int, ips: List[str], sender_ip: str = "") -> bool:
        local_set = set(self.get_local_ips())
        # Hostname alone is a strong self-indicator (port may differ due to fallback).
        if name == self.get_hostname():
            return True
        if sender_ip and sender_ip in local_set and port == self.port:
            return True
        if any(ip in local_set for ip in ips) and port == self.port:
            return True
        return False

    def _upsert_device(
        self,
        key: str,
        name: str,
        ip: str,
        ips: List[str],
        port: int,
        source: str,
        reachable: bool = True,
    ):
        now = time.monotonic()
        previous = self.devices.get(key)
        self.devices[key] = {
            'name': name,
            'ip': ip,
            'ips': list(ips),
            'port': int(port),
            'source': source,
            'reachable': bool(reachable),
            'last_seen': now,
        }

        changed = (
            previous is None
            or previous.get('ip') != ip
            or int(previous.get('port', 0)) != int(port)
            or previous.get('name') != name
            or bool(previous.get('reachable', True)) != bool(reachable)
        )
        if changed and self.on_device_added:
            self.on_device_added(name, ip, int(port))

    def _remove_device_by_key(self, key: str):
        if key not in self.devices:
            return
        device = self.devices.pop(key)
        replacements = [
            candidate
            for candidate in self.devices.values()
            if str(candidate.get('name', '')).casefold() == str(device.get('name', '')).casefold()
        ]
        if replacements:
            replacement = max(
                replacements,
                key=lambda candidate: (
                    bool(candidate.get('reachable', False)),
                    float(candidate.get('last_seen', 0.0)),
                ),
            )
            if self.on_device_added:
                self.on_device_added(
                    replacement['name'],
                    replacement['ip'],
                    int(replacement['port']),
                )
            return
        if self.on_device_removed:
            self.on_device_removed(device['name'], device['ip'])

    async def _register_service(self):
        if not self.zeroconf:
            return

        local_ips = self.get_local_ips()
        if not local_ips:
            local_ips = ["127.0.0.1"]

        hostname = self.get_hostname()
        self.service_info = ServiceInfo(
            SERVICE_TYPE,
            f"{hostname}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip) for ip in local_ips],
            port=self.port,
            properties={
                'name': hostname,
                'version': __version__,
                'txtvers': '1',
                'protovers': '1',
            },
        )

        try:
            await self.zeroconf.async_register_service(self.service_info)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Не удалось зарегистрировать сервис: {e}")

    def _zeroconf_kwargs(self, local_ips: List[str]) -> dict:
        kwargs = {}
        explicit_ips = [ip for ip in local_ips if self._is_valid_local_ip(ip)]
        if explicit_ips:
            kwargs["interfaces"] = explicit_ips
        elif InterfaceChoice is not None:
            kwargs["interfaces"] = InterfaceChoice.All
        if IPVersion is not None:
            kwargs["ip_version"] = IPVersion.V4Only
        return kwargs

    async def start(self):
        if self._running:
            return

        try:
            self._local_ips = self._list_local_ipv4()
            self._local_ip = self._local_ips[0] if self._local_ips else "127.0.0.1"

            self.zeroconf = AsyncZeroconf(**self._zeroconf_kwargs(self._local_ips))
            await self._register_service()
            self._running = True
            await self.resume_browsing()

        except Exception as e:
            self._running = False
            if self.on_error:
                self.on_error(f"Ошибка запуска discovery: {e}")
            raise

    async def reconfigure_if_needed(self) -> bool:
        """Refresh advertised local IPs if network changed (e.g. VPN toggled)."""
        if not self.zeroconf or not self.service_info:
            return False

        new_ips = self._list_local_ipv4()
        if not new_ips:
            new_ips = ["127.0.0.1"]

        if set(new_ips) == set(self._local_ips):
            return False

        browsing = self.browser is not None
        self._local_ips = new_ips
        self._local_ip = new_ips[0]

        update_interfaces = getattr(self.zeroconf, "async_update_interfaces", None)
        if callable(update_interfaces):
            kwargs = self._zeroconf_kwargs(new_ips)
            await update_interfaces(
                interfaces=kwargs.get("interfaces"),
                ip_version=kwargs.get("ip_version"),
            )
            self.service_info.addresses = [socket.inet_aton(ip) for ip in new_ips]
            await self.zeroconf.async_update_service(self.service_info)
        else:  # Compatibility with zeroconf versions before async interface updates.
            if self.browser:
                await self.browser.async_cancel()
                self.browser = None
            try:
                await self.zeroconf.async_unregister_service(self.service_info)
            except Exception:
                pass
            await self.zeroconf.async_close()
            self.zeroconf = AsyncZeroconf(**self._zeroconf_kwargs(new_ips))
            self.service_info = None
            await self._register_service()
            if browsing:
                await self.resume_browsing()

        if self.compatibility_mode:
            await self._send_compat_packet("announce")
        return True

    async def set_compatibility_mode(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        if enabled == self.compatibility_mode:
            return False

        self.compatibility_mode = enabled
        if not self._running:
            return True

        if enabled:
            await self._start_compatibility()
            await self._send_compat_packet("probe")
        else:
            await self._stop_compatibility()
            stale_keys = [
                key
                for key, device in self.devices.items()
                if str(device.get("source", "")).startswith("compat")
            ]
            for key in stale_keys:
                self._remove_device_by_key(key)
        return True

    async def resume_browsing(self):
        if self.zeroconf and not self.browser:
            class Listener(ServiceListener):
                def __init__(listener_self, discovery):
                    listener_self.discovery = discovery

                def add_service(listener_self, zc: Zeroconf, type_: str, name: str):
                    asyncio.create_task(listener_self.discovery._on_service_found(zc, type_, name))

                def remove_service(listener_self, zc: Zeroconf, type_: str, name: str):
                    listener_self.discovery._on_service_removed(name)

                def update_service(listener_self, zc: Zeroconf, type_: str, name: str):
                    asyncio.create_task(listener_self.discovery._on_service_found(zc, type_, name))

            self.browser = AsyncServiceBrowser(self.zeroconf.zeroconf, SERVICE_TYPE, Listener(self))

        if self.compatibility_mode:
            await self._start_compatibility()

    async def pause_browsing(self):
        if not self.browser:
            await self._stop_compatibility()
            return
        await self.browser.async_cancel()
        self.browser = None
        await self._stop_compatibility()

    async def _refresh_mdns_browser(self):
        if self.browser:
            await self.browser.async_cancel()
            self.browser = None
        await self.resume_browsing()

    def _check_output_hidden(self, command: List[str], timeout_sec: float = 1.2) -> str:
        startupinfo = None
        creationflags = 0
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        except Exception:
            startupinfo = None
            creationflags = 0

        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=timeout_sec,
            check=False,
        )
        return proc.stdout or ""

    def _build_compat_payload(self, packet_type: str) -> bytes:
        payload = {
            "app": "vlink",
            "type": packet_type,
            "name": self.get_hostname(),
            "port": self.port,
            "ips": self.get_local_ips(),
            "version": __version__,
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _broadcast_targets(self) -> List[tuple[str, int]]:
        targets: set[tuple[str, int]] = {("255.255.255.255", COMPAT_UDP_PORT)}
        for network in self._local_networks():
            targets.add((str(network.broadcast_address), COMPAT_UDP_PORT))
        return list(targets)

    async def _send_compat_packet(self, packet_type: str, target: Optional[tuple[str, int]] = None):
        if not self._compat_transport:
            return
        data = self._build_compat_payload(packet_type)

        targets = [target] if target else self._broadcast_targets()
        for t in targets:
            try:
                self._compat_transport.sendto(data, t)
            except Exception:
                continue

    async def _start_compatibility(self):
        if not self._running or not self.compatibility_mode:
            return
        if self._compat_transport is None:
            loop = asyncio.get_running_loop()
            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    lambda: _CompatDatagramProtocol(self),
                    local_addr=("0.0.0.0", COMPAT_UDP_PORT),
                    allow_broadcast=True,
                )
                self._compat_transport = transport
                self._compat_protocol = protocol
            except OSError as e:
                if self.on_error:
                    self.on_error(f"Compat discovery UDP недоступен: {e}")

        if self._compat_announce_task is None or self._compat_announce_task.done():
            self._compat_announce_task = asyncio.create_task(self._compat_announce_loop())
        if self._compat_probe_task is None or self._compat_probe_task.done():
            self._compat_probe_task = asyncio.create_task(self._compat_probe_loop())

    async def _stop_compatibility(self):
        tasks = [self._compat_announce_task, self._compat_probe_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
        self._compat_announce_task = None
        self._compat_probe_task = None

        if self._compat_transport:
            try:
                self._compat_transport.close()
            except Exception:
                pass
        self._compat_transport = None
        self._compat_protocol = None

    async def _compat_announce_loop(self):
        while self._running and self.compatibility_mode:
            try:
                await self._send_compat_packet("announce")
                self._cleanup_stale_compat_devices()
            except Exception:
                pass
            await asyncio.sleep(COMPAT_ANNOUNCE_INTERVAL)

    def _parse_arp_candidates(self) -> set[str]:
        candidates: set[str] = set()
        try:
            output = self._check_output_hidden(["arp", "-a"])
            for match in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", output):
                if self._is_valid_local_ip(match) and self._is_private_ip(match):
                    candidates.add(match)
        except Exception:
            pass
        return candidates

    def _scan_window_candidates(self) -> set[str]:
        local_set = set(self.get_local_ips())
        candidates: set[str] = set()
        hotspot_env = self._is_hotspot_environment()
        for network in self._local_networks():
            if network.num_addresses <= 2 or network.num_addresses > 1024:
                continue
            first_host = int(network.network_address) + 1
            host_count = int(network.num_addresses) - 2
            key = str(network)
            cursor = int(self._scan_cursor.get(key, 0)) % host_count
            # On hotspot / isolated Wi-Fi, scan a larger sliding window for faster peer pickup.
            window = min(120 if hotspot_env else 48, host_count)
            for i in range(window):
                candidate = str(ipaddress.ip_address(first_host + ((cursor + i) % host_count)))
                if candidate not in local_set:
                    candidates.add(candidate)
            self._scan_cursor[key] = (cursor + window) % host_count
        return candidates

    def _collect_probe_candidates(self) -> List[str]:
        local_set = set(self.get_local_ips())
        local_networks = self._local_networks()
        candidates = self._parse_arp_candidates()
        candidates.update(self._scan_window_candidates())

        for device in self.devices.values():
            ip = str(device.get("ip", "")).strip()
            if ip and ip not in local_set:
                candidates.add(ip)

        result = []
        for ip in candidates:
            if not ip or ip in local_set or not self._is_valid_local_ip(ip):
                continue
            try:
                address = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if any(address in network for network in local_networks):
                result.append(ip)
        result.sort()
        return result

    def _port_candidates(self) -> List[int]:
        ports = [self.port]
        alternates = [port for port in range(8765, 8775) if port != self.port]
        if alternates:
            index = self._port_scan_cursor % len(alternates)
            ports.append(alternates[index])
            self._port_scan_cursor = (index + 1) % len(alternates)
        return ports

    async def _probe_ip(self, ip: str, port: int) -> bool:
        info = await self._http_get_json(ip, port, "/info", timeout=0.65)
        if not info:
            return False

        name = str(info.get("name") or "Unknown")
        remote_port = int(info.get("port") or port)
        if self._is_self_candidate(name, remote_port, [ip], sender_ip=ip):
            return False

        self._upsert_device(
            key=f"compat-scan::{name}:{ip}:{remote_port}",
            name=name,
            ip=ip,
            ips=[ip],
            port=remote_port,
            source="compat-scan",
            reachable=True,
        )
        return True

    async def _run_compat_probe(self):
        if self._compat_probe_lock.locked():
            return
        async with self._compat_probe_lock:
            # Refresh local IPs each cycle so late-acquired addresses
            # (e.g. phone hotspot) are recognised as self.
            self._local_ips = self._list_local_ipv4()
            self._local_ip = self._local_ips[0] if self._local_ips else "127.0.0.1"

            candidates = self._collect_probe_candidates()
            ports = self._port_candidates()
            if candidates and ports:
                sem = asyncio.Semaphore(28)

                async def probe_candidate(candidate_ip: str):
                    async with sem:
                        for candidate_port in ports:
                            if await self._probe_ip(candidate_ip, candidate_port):
                                return

                await asyncio.gather(*(probe_candidate(ip) for ip in candidates))
            self._cleanup_stale_compat_devices()

    async def _compat_probe_loop(self):
        while self._running and self.compatibility_mode:
            try:
                await self._run_compat_probe()
            except Exception:
                pass
            await asyncio.sleep(8.0 if self._is_hotspot_environment() else COMPAT_PROBE_INTERVAL)

    def _cleanup_stale_compat_devices(self):
        now = time.monotonic()
        stale = [
            key for key, device in self.devices.items()
            if str(device.get("source", "")).startswith("compat")
            and (now - float(device.get("last_seen", now))) > COMPAT_DEVICE_TTL
        ]
        for key in stale:
            self._remove_device_by_key(key)

    async def _http_get_json(self, ip: str, port: int, path: str, timeout: float = 1.0) -> Optional[dict]:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, int(port)), timeout=timeout)
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {ip}:{port}\r\n"
                "Accept: application/json\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            writer.write(request)
            await asyncio.wait_for(writer.drain(), timeout=timeout)

            raw = await asyncio.wait_for(reader.read(8192), timeout=timeout)
            if not raw:
                return None
            head, _, body = raw.partition(b"\r\n\r\n")
            if b" 200 " not in head and not head.startswith(b"HTTP/1.1 200"):
                return None
            text = body.decode("utf-8", errors="ignore").strip()
            if not text:
                return None
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
        finally:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    async def _on_compat_datagram(self, data: bytes, addr):
        if not self.compatibility_mode or not self._running:
            return
        try:
            payload = json.loads(data.decode("utf-8", errors="ignore"))
            if not isinstance(payload, dict) or payload.get("app") != "vlink":
                return
        except Exception:
            return

        packet_type = str(payload.get("type", "")).strip().lower()
        name = str(payload.get("name", "Unknown")).strip() or "Unknown"
        port = int(payload.get("port", 0) or 0)
        if not (1 <= port <= 65535):
            return

        sender_ip = str(addr[0]).strip() if addr else ""
        announced_ips = payload.get("ips", [])
        if not isinstance(announced_ips, list):
            announced_ips = []
        announced_ips = [ip for ip in announced_ips if isinstance(ip, str) and self._is_valid_local_ip(ip)]

        candidates = []
        if sender_ip and self._is_valid_local_ip(sender_ip):
            candidates.append(sender_ip)
        for ip in announced_ips:
            if ip not in candidates:
                candidates.append(ip)
        if not candidates:
            return

        if self._is_self_candidate(name, port, candidates, sender_ip=sender_ip):
            return

        selected_ip, reachable = await self._pick_preferred_ip(candidates, port)
        if not selected_ip:
            return

        self._upsert_device(
            key=f"compat-udp::{name}:{selected_ip}:{port}",
            name=name,
            ip=selected_ip,
            ips=candidates,
            port=port,
            source="compat-udp",
            reachable=reachable,
        )

        if packet_type in ("announce", "probe") and sender_ip:
            sender_port = int(addr[1]) if addr and len(addr) > 1 else COMPAT_UDP_PORT
            await self._send_compat_packet("response", (sender_ip, sender_port))

    def _rank_candidate_ips(self, ips: List[str]) -> List[str]:
        local_ips = self.get_local_ips()

        def local_iface_rank(local_ip: str) -> int:
            if self._is_hotspot_ip(local_ip):
                return 0
            if local_ip.startswith("192.168."):
                return 1
            if local_ip.startswith("10."):
                return 2
            if local_ip.startswith("172."):
                return 3
            if self._is_private_ip(local_ip):
                return 4
            return 5

        def same_subnet_rank(candidate: str) -> Optional[int]:
            try:
                caddr = ipaddress.ip_address(candidate)
            except ValueError:
                return None
            ranks = []
            for lip in local_ips:
                try:
                    network = ipaddress.ip_network(f"{lip}/24", strict=False)
                    if caddr in network:
                        ranks.append(local_iface_rank(lip))
                except ValueError:
                    continue
            return min(ranks) if ranks else None

        # Ranking:
        # 1) Same /24 subnet as a preferred local interface (LAN before VPN-like ranges)
        # 2) Home/private blocks by preference
        # 3) Public/other
        def score(ip: str) -> tuple[int, str]:
            subnet_rank = same_subnet_rank(ip)
            if subnet_rank is not None:
                return (subnet_rank, ip)
            if self._is_hotspot_ip(ip):
                return (6, ip)
            if ip.startswith("192.168."):
                return (7, ip)
            if ip.startswith("10."):
                return (8, ip)
            if ip.startswith("172."):
                return (9, ip)
            if self._is_private_ip(ip):
                return (10, ip)
            return (11, ip)

        return sorted(ips, key=score)

    async def _pick_preferred_ip(self, ips: List[str], port: int) -> tuple[str, bool]:
        if not ips:
            return "", False

        async def can_connect(ip: str) -> bool:
            try:
                pong = await self._http_get_json(ip, port, "/ping", timeout=0.65)
                if isinstance(pong, dict) and str(pong.get("status", "")).lower() == "ok":
                    return True
            except Exception:
                return False
            return False

        ordered = self._rank_candidate_ips(ips)
        for ip in ordered:
            if await can_connect(ip):
                return ip, True

        # Keep device visible even if currently unreachable.
        # Availability is rechecked before transfer.
        return ordered[0], False

    async def _pick_reachable_ip(self, ips: List[str], port: int) -> str:
        selected, _reachable = await self._pick_preferred_ip(ips, port)
        return selected

    async def _on_service_found(self, zc: Zeroconf, type_: str, name: str):
        from zeroconf.asyncio import AsyncServiceInfo

        pending_removal = self._mdns_remove_tasks.pop(name, None)
        if pending_removal and not pending_removal.done():
            pending_removal.cancel()

        info = AsyncServiceInfo(type_, name)

        for attempt in range(SERVICE_INFO_RETRIES):
            try:
                await info.async_request(zc, SERVICE_INFO_TIMEOUT)

                if info.addresses:
                    ips = [socket.inet_ntoa(raw) for raw in info.addresses if raw]
                    ips = [ip for ip in ips if self._is_valid_local_ip(ip)]
                    if not ips:
                        return

                    device_name = info.properties.get(b'name', b'Unknown').decode('utf-8')

                    # Skip only exact self service / self addresses.
                    if self.service_info and name == self.service_info.name:
                        return
                    if self._is_self_candidate(device_name, info.port, ips):
                        return

                    selected_ip, reachable = await self._pick_preferred_ip(ips, info.port)
                    if not selected_ip:
                        return

                    self._upsert_device(
                        key=f"mdns::{name}",
                        name=device_name,
                        ip=selected_ip,
                        ips=ips,
                        port=info.port,
                        source="mdns",
                        reachable=reachable,
                    )
                    return

            except Exception as e:
                if attempt < SERVICE_INFO_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                elif self.on_error:
                    self.on_error(f"Не удалось получить info для {name}: {e}")

    async def _remove_mdns_after_grace(self, name: str):
        try:
            await asyncio.sleep(MDNS_REMOVE_GRACE)
            self._remove_device_by_key(f"mdns::{name}")
        except asyncio.CancelledError:
            return
        finally:
            current = self._mdns_remove_tasks.get(name)
            if current is asyncio.current_task():
                self._mdns_remove_tasks.pop(name, None)

    def _on_service_removed(self, name: str):
        previous = self._mdns_remove_tasks.pop(name, None)
        if previous and not previous.done():
            previous.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._remove_device_by_key(f"mdns::{name}")
        else:
            self._mdns_remove_tasks[name] = loop.create_task(
                self._remove_mdns_after_grace(name)
            )

    async def refresh(self):
        if not self._running:
            await self.start()
            return

        await self.reconfigure_if_needed()
        await self._refresh_mdns_browser()
        if self.compatibility_mode:
            await self._send_compat_packet("probe")
            await self._run_compat_probe()

    def get_devices(self) -> Dict[str, Dict]:
        return dict(self.devices)

    async def stop(self):
        self._running = False
        try:
            removal_tasks = list(self._mdns_remove_tasks.values())
            self._mdns_remove_tasks.clear()
            for task in removal_tasks:
                if not task.done():
                    task.cancel()
            if removal_tasks:
                await asyncio.gather(*removal_tasks, return_exceptions=True)

            await self._stop_compatibility()

            if self.browser:
                await self.browser.async_cancel()
                self.browser = None

            if self.service_info and self.zeroconf:
                try:
                    await self.zeroconf.async_unregister_service(self.service_info)
                except Exception:
                    pass

            if self.zeroconf:
                await self.zeroconf.async_close()
                self.zeroconf = None

        except Exception as e:
            if self.on_error:
                self.on_error(f"Ошибка остановки discovery: {e}")
