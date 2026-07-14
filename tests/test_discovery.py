from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from zeroconf import IPVersion

from main_window import MainWindow
from network.discovery import COMPAT_UDP_PORT, DeviceDiscovery


def install_interface_records(monkeypatch, records):
    monkeypatch.setattr(
        DeviceDiscovery,
        "_interface_ipv4_records",
        classmethod(lambda cls: list(records)),
        raising=False,
    )


def test_discovery_uses_physical_lan_and_real_network_prefix(monkeypatch):
    install_interface_records(
        monkeypatch,
        [
            ("sing-tun Tunnel", "172.18.0.1", 30),
            ("Realtek Gaming Ethernet", "192.168.0.24", 23),
        ],
    )
    discovery = DeviceDiscovery(8765, compatibility_mode=True)

    assert discovery.get_local_ips() == ["192.168.0.24"]
    assert set(discovery._broadcast_targets()) == {
        ("255.255.255.255", COMPAT_UDP_PORT),
        ("192.168.1.255", COMPAT_UDP_PORT),
    }


def test_fallback_probe_ignores_vpn_subnet_and_limits_ports(monkeypatch):
    install_interface_records(
        monkeypatch,
        [
            ("sing-tun Tunnel", "172.18.0.1", 30),
            ("Intel Wi-Fi", "192.168.50.20", 24),
        ],
    )
    discovery = DeviceDiscovery(8765, compatibility_mode=True)
    monkeypatch.setattr(
        discovery,
        "_parse_arp_candidates",
        lambda: {"172.18.0.2", "192.168.50.1", "192.168.50.42"},
    )
    monkeypatch.setattr(discovery, "_scan_window_candidates", lambda: set())

    assert discovery._collect_probe_candidates() == ["192.168.50.1", "192.168.50.42"]
    ports = discovery._port_candidates()
    assert ports[0] == 8765
    assert len(ports) <= 2


@pytest.mark.asyncio
async def test_refresh_keeps_known_devices(monkeypatch):
    discovery = DeviceDiscovery(8765, compatibility_mode=True)
    discovery._running = True
    discovery.devices["mdns::peer"] = {
        "name": "Peer",
        "ip": "192.168.0.31",
        "ips": ["192.168.0.31"],
        "port": 8765,
        "source": "mdns",
        "reachable": True,
        "last_seen": 1.0,
    }
    discovery.stop = AsyncMock()
    discovery.start = AsyncMock()
    monkeypatch.setattr(discovery, "reconfigure_if_needed", AsyncMock(return_value=False))
    monkeypatch.setattr(discovery, "_refresh_mdns_browser", AsyncMock(), raising=False)
    monkeypatch.setattr(discovery, "_send_compat_packet", AsyncMock())
    monkeypatch.setattr(discovery, "_run_compat_probe", AsyncMock(), raising=False)

    await discovery.refresh()

    assert "mdns::peer" in discovery.devices
    discovery.stop.assert_not_awaited()
    discovery.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_network_change_updates_zeroconf_interfaces_without_unregistering(monkeypatch):
    discovery = DeviceDiscovery(8765)
    discovery._local_ips = ["192.168.0.24"]
    discovery._local_ip = "192.168.0.24"
    discovery.service_info = SimpleNamespace(addresses=[])
    discovery.zeroconf = SimpleNamespace(
        async_update_interfaces=AsyncMock(),
        async_update_service=AsyncMock(),
        async_unregister_service=AsyncMock(),
    )
    monkeypatch.setattr(discovery, "_list_local_ipv4", lambda: ["192.168.50.20"])

    changed = await discovery.reconfigure_if_needed()

    assert changed is True
    discovery.zeroconf.async_update_interfaces.assert_awaited_once_with(
        interfaces=["192.168.50.20"],
        ip_version=IPVersion.V4Only,
    )
    discovery.zeroconf.async_update_service.assert_awaited_once_with(discovery.service_info)
    discovery.zeroconf.async_unregister_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_compatibility_mode_changes_without_restarting_discovery(monkeypatch):
    discovery = DeviceDiscovery(8765, compatibility_mode=False)
    discovery._running = True
    start_compatibility = AsyncMock()
    stop_compatibility = AsyncMock()
    send_packet = AsyncMock()
    monkeypatch.setattr(discovery, "_start_compatibility", start_compatibility)
    monkeypatch.setattr(discovery, "_stop_compatibility", stop_compatibility)
    monkeypatch.setattr(discovery, "_send_compat_packet", send_packet)

    assert await discovery.set_compatibility_mode(True) is True
    start_compatibility.assert_awaited_once()
    send_packet.assert_awaited_once_with("probe")

    assert await discovery.set_compatibility_mode(False) is True
    stop_compatibility.assert_awaited_once()


@pytest.mark.asyncio
async def test_preferred_ip_checks_each_candidate_once(monkeypatch):
    discovery = DeviceDiscovery(8765)
    discovery._local_ips = ["192.168.0.24"]
    get_json = AsyncMock(return_value=None)
    monkeypatch.setattr(discovery, "_http_get_json", get_json)

    selected, reachable = await discovery._pick_preferred_ip(
        ["192.168.0.31", "192.168.0.32"],
        8765,
    )

    assert selected == "192.168.0.31"
    assert reachable is False
    assert get_json.await_count == 2


def test_removing_one_source_keeps_other_source_visible():
    discovery = DeviceDiscovery(8765, compatibility_mode=True)
    discovery.devices = {
        "mdns::peer": {
            "name": "Peer",
            "ip": "192.168.0.31",
            "ips": ["192.168.0.31"],
            "port": 8765,
            "source": "mdns",
            "reachable": True,
        },
        "compat-udp::peer": {
            "name": "Peer",
            "ip": "192.168.0.31",
            "ips": ["192.168.0.31"],
            "port": 8765,
            "source": "compat-udp",
            "reachable": True,
        },
    }
    added = []
    removed = []
    discovery.on_device_added = lambda name, ip, port: added.append((name, ip, port))
    discovery.on_device_removed = lambda name, ip: removed.append((name, ip))

    discovery._remove_device_by_key("mdns::peer")

    assert removed == []
    assert added == [("Peer", "192.168.0.31", 8765)]


def test_manual_refresh_does_not_clear_device_list():
    scheduled = []
    device_list = Mock()
    status_label = Mock()
    status_label.text.return_value = "active"
    window = SimpleNamespace(
        discovery=object(),
        loop=object(),
        device_list=device_list,
        selected_device=("Peer", "192.168.0.31", 8765),
        status_label=status_label,
        relay=None,
        _schedule_task=lambda coroutine, name: scheduled.append(coroutine),
    )

    MainWindow._refresh_devices(window)

    device_list.clear_devices.assert_not_called()
    assert window.selected_device == ("Peer", "192.168.0.31", 8765)
    for coroutine in scheduled:
        coroutine.close()
