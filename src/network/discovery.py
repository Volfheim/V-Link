"""
V-Link - Discovery Service
mDNS/Zeroconf device discovery.
"""

import asyncio
import ipaddress
import socket
import subprocess
from typing import Callable, Dict, List, Optional

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
SERVICE_INFO_RETRIES = 3
SERVICE_INFO_TIMEOUT = 3000  # ms


class DeviceDiscovery:
    """Device discovery with registration and pausable browsing."""

    def __init__(self, port: int = 8765):
        self.port = port
        self.zeroconf: Optional[AsyncZeroconf] = None
        self.browser: Optional[AsyncServiceBrowser] = None
        self.service_info: Optional[ServiceInfo] = None
        self.devices: Dict[str, Dict] = {}
        self._running = False

        self._local_ips: List[str] = []
        self._local_ip: Optional[str] = None

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

    def _list_local_ipv4(self) -> List[str]:
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
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            output = subprocess.check_output(
                ["ipconfig"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                startupinfo=startupinfo,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            for line in output.splitlines():
                if "IPv4" in line:
                    if ":" in line:
                        candidate = line.split(":", 1)[1].strip()
                        if candidate:
                            ips.add(candidate)
        except Exception:
            pass

        filtered = [ip for ip in ips if self._is_valid_local_ip(ip)]

        def ip_rank(ip: str) -> tuple[int, str]:
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                return (9, ip)
            if not addr.is_private:
                return (8, ip)
            if ip.startswith("192.168."):
                return (0, ip)  # typical home LAN
            if ip.startswith("10."):
                return (1, ip)
            if ip.startswith("172."):
                return (2, ip)  # often VPN or corporate segment
            return (3, ip)

        filtered.sort(key=ip_rank)
        return filtered

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
            },
        )

        try:
            await self.zeroconf.async_register_service(self.service_info)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Не удалось зарегистрировать сервис: {e}")

    async def start(self):
        if self._running:
            return

        try:
            self._local_ips = self._list_local_ipv4()
            self._local_ip = self._local_ips[0] if self._local_ips else "127.0.0.1"

            zc_kwargs = {}
            if InterfaceChoice is not None:
                zc_kwargs["interfaces"] = InterfaceChoice.All
            if IPVersion is not None:
                zc_kwargs["ip_version"] = IPVersion.V4Only
            self.zeroconf = AsyncZeroconf(**zc_kwargs)
            await self._register_service()
            await self.resume_browsing()
            self._running = True

        except Exception as e:
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

        try:
            await self.zeroconf.async_unregister_service(self.service_info)
        except Exception:
            pass

        self._local_ips = new_ips
        self._local_ip = new_ips[0]
        await self._register_service()
        return True

    async def resume_browsing(self):
        if not self.zeroconf or self.browser:
            return

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

    async def pause_browsing(self):
        if not self.browser:
            return
        await self.browser.async_cancel()
        self.browser = None

    async def _pick_reachable_ip(self, ips: List[str], port: int) -> str:
        if not ips:
            return ""

        async def can_connect(ip: str) -> bool:
            for _ in range(2):
                try:
                    conn = asyncio.open_connection(ip, port)
                    r, w = await asyncio.wait_for(conn, timeout=0.8)
                    w.close()
                    try:
                        await w.wait_closed()
                    except Exception:
                        pass
                    return True
                except Exception:
                    continue
            return False

        local_ips = self.get_local_ips()

        def in_same_subnet(candidate: str) -> bool:
            try:
                caddr = ipaddress.ip_address(candidate)
            except ValueError:
                return False
            for lip in local_ips:
                try:
                    network = ipaddress.ip_network(f"{lip}/24", strict=False)
                    if caddr in network:
                        return True
                except ValueError:
                    continue
            return False

        # Ranking:
        # 1) Same /24 subnet as any local interface (best for LAN/VPN mixed setups)
        # 2) Home/private blocks by preference
        # 3) Public/other
        def score(ip: str) -> tuple[int, str]:
            if in_same_subnet(ip):
                return (0, ip)
            if ip.startswith("192.168."):
                return (1, ip)
            if ip.startswith("10."):
                return (2, ip)
            if ip.startswith("172."):
                return (3, ip)
            if self._is_private_ip(ip):
                return (4, ip)
            return (5, ip)

        ordered = sorted(ips, key=score)
        for ip in ordered:
            if await can_connect(ip):
                return ip
        return ""

    async def _on_service_found(self, zc: Zeroconf, type_: str, name: str):
        from zeroconf.asyncio import AsyncServiceInfo

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

                    # Skip only exact self service to avoid false positives with VPN/virtual adapters.
                    if self.service_info and name == self.service_info.name:
                        return

                    selected_ip = await self._pick_reachable_ip(ips, info.port)
                    if not selected_ip:
                        # Do not show unreachable peers as online devices.
                        return

                    self.devices[name] = {
                        'name': device_name,
                        'ip': selected_ip,
                        'ips': ips,
                        'port': info.port,
                    }

                    if self.on_device_added:
                        self.on_device_added(device_name, selected_ip, info.port)
                    return

            except Exception as e:
                if attempt < SERVICE_INFO_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                elif self.on_error:
                    self.on_error(f"Не удалось получить info для {name}: {e}")

    def _on_service_removed(self, name: str):
        if name in self.devices:
            device = self.devices.pop(name)
            if self.on_device_removed:
                self.on_device_removed(device['name'], device['ip'])

    async def refresh(self):
        await self.stop()
        self._local_ips = []
        self._local_ip = None
        self.devices.clear()
        await asyncio.sleep(0.4)
        await self.start()

    def get_devices(self) -> Dict[str, Dict]:
        return dict(self.devices)

    async def stop(self):
        self._running = False
        try:
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
