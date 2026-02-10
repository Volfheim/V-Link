"""
V-Link - Main Window
"""

import asyncio
import os
import sys
import time
from typing import Dict, List, Optional

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import Settings, Updater, set_autostart
from version import __version__
from network import DeviceDiscovery, RelayClient, TransferClient, TransferServer
from ui import DeviceList, DropZone, TransferList, get_stylesheet
from ui.settings_dialog import SettingsDialog

SECURE_SHARED_SECRET = "vlink-secure-mode-v1"


class MainWindow(QMainWindow):
    """Main window for V-Link."""

    def __init__(self):
        super().__init__()

        self.settings = Settings()
        self.discovery: Optional[DeviceDiscovery] = None
        self.server: Optional[TransferServer] = None
        self.client: Optional[TransferClient] = None
        self.relay: Optional[RelayClient] = None
        self.updater: Optional[Updater] = None
        self.relay_peers: Dict[str, Dict] = {}
        self.selected_device: Optional[tuple] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._low_power_mode = False
        self._last_security_warning_ts = 0.0
        self._hotspot_detected = False
        self._effective_nonstandard_mode = False
        self._services_ready = False
        self._services_starting = False
        self._quitting = False
        self._transfer_directions: Dict[str, tuple] = {}

        self._network_timer = QTimer(self)
        self._network_timer.setInterval(15000)
        self._network_timer.timeout.connect(self._schedule_network_sync)

        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._connect_signals()

    def _setup_window(self):
        self.setWindowTitle("V-Link")
        self.setMinimumSize(600, 700)
        self.resize(650, 750)
        self.setStyleSheet(get_stylesheet())

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addLayout(self._create_header())

        self.device_list = DeviceList(default_port=self.settings.port)
        layout.addWidget(self.device_list)

        self.drop_zone = DropZone()
        layout.addWidget(self.drop_zone)

        self.transfer_list = TransferList()
        layout.addWidget(self.transfer_list)

        layout.addLayout(self._create_status_bar())

    def _create_header(self) -> QHBoxLayout:
        header = QHBoxLayout()

        title_layout = QVBoxLayout()
        title = QLabel("V-Link")
        title.setObjectName("titleLabel")
        title_layout.addWidget(title)

        subtitle = QLabel("Быстрая передача файлов в локальной сети")
        subtitle.setObjectName("subtitleLabel")
        title_layout.addWidget(subtitle)

        header.addLayout(title_layout)
        header.addStretch()

        self.update_btn = QPushButton("⬆ Обновить")
        self.update_btn.setToolTip("Доступно обновление V-Link")
        self.update_btn.setStyleSheet(
            """
            QPushButton {
                background: rgba(34, 197, 94, 0.15);
                border: 1px solid #22c55e;
                color: #22c55e;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(34, 197, 94, 0.3); }
            """
        )
        self.update_btn.clicked.connect(self._show_update_dialog)
        self.update_btn.setVisible(False)
        header.addWidget(self.update_btn)

        self.refresh_btn = QPushButton()
        self.refresh_btn.setToolTip("Обновить список устройств")
        self.refresh_btn.setFixedSize(36, 36)
        style = self.refresh_btn.style()
        self.refresh_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_BrowserReload))
        self.refresh_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: 1px solid #6b5ce7;
                border-radius: 6px;
            }
            QPushButton:hover { background: rgba(107, 92, 231, 0.2); }
            """
        )
        self.refresh_btn.clicked.connect(self._refresh_devices)
        header.addWidget(self.refresh_btn)

        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: 1px solid #6b5ce7;
                color: #c084fc;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(107, 92, 231, 0.2); }
            """
        )
        self.settings_btn.setToolTip("Открыть настройки")
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)

        return header

    def _create_status_bar(self) -> QHBoxLayout:
        status = QHBoxLayout()

        self.status_label = QLabel("● Готов к работе")
        self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
        status.addWidget(self.status_label)

        status.addStretch()

        self.ip_label = QLabel("")
        self.ip_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        status.addWidget(self.ip_label)

        return status

    def show_startup_state(self, message: str = "● Запуск сервисов..."):
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")

    @pyqtSlot()
    def _show_services_starting(self):
        QMessageBox.information(
            self,
            "V-Link",
            "Сетевые сервисы ещё запускаются. Попробуйте через пару секунд.",
        )

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        icon_path = "app_icon.ico"
        if hasattr(sys, '_MEIPASS'):
            icon_path = os.path.join(sys._MEIPASS, icon_path)

        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(QIcon("app_icon.ico"))
        self.tray_icon.setToolTip(f"V-Link v{__version__}")

        tray_menu = QMenu()

        show_action = QAction("Показать", self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)

        hotspot_action = QAction("Хот-спот Windows", self)
        hotspot_action.triggered.connect(self._open_hotspot_settings)
        tray_menu.addAction(hotspot_action)

        downloads_action = QAction("Открыть папку загрузок", self)
        downloads_action.triggered.connect(self._open_downloads_folder)
        tray_menu.addAction(downloads_action)

        tray_menu.addSeparator()

        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _connect_signals(self):
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.device_list.device_selected.connect(self._on_device_selected)

    @staticmethod
    def _is_hotspot_ip(ip: str) -> bool:
        return str(ip).startswith("192.168.137.")

    def _detect_hotspot_environment(self) -> bool:
        try:
            probe = DeviceDiscovery(self.settings.port, compatibility_mode=False)
            ips = probe._list_local_ipv4()  # local probe only, no network actions
            return any(self._is_hotspot_ip(ip) for ip in ips)
        except Exception:
            return False

    def _open_hotspot_settings(self):
        try:
            os.startfile("ms-settings:network-mobilehotspot")
        except Exception:
            QMessageBox.information(
                self,
                "V-Link",
                "Откройте вручную:\nПараметры Windows -> Сеть и Интернет -> Мобильный хот-спот",
            )

    def _open_downloads_folder(self):
        folder = self.settings.download_dir
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except Exception:
            QMessageBox.warning(self, "V-Link", f"Не удалось открыть папку:\n{folder}")

    def _refresh_devices(self):
        if self.discovery and self.loop:
            self.device_list.clear_devices()
            self.selected_device = None
            self.status_label.setText("● Обновление...")
            async def do_refresh():
                await self.discovery.refresh()
                if self.relay:
                    try:
                        await self.relay.refresh_peers()
                    except Exception as e:
                        self._on_server_error(f"Relay refresh error: {e}")
            asyncio.run_coroutine_threadsafe(do_refresh(), self.loop)

    def _open_settings(self):
        old_port = self.settings.port
        old_secure_mode = self.settings.secure_mode
        old_nonstandard_mode = self.settings.nonstandard_network_mode
        old_relay_mode = self.settings.relay_mode
        old_relay_url = self.settings.relay_server_url
        old_relay_channel = self.settings.relay_channel
        old_dir = self.settings.download_dir
        old_autostart = self.settings.autostart

        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.device_list.default_port = self.settings.port

        if old_autostart != self.settings.autostart:
            try:
                set_autostart(self.settings.autostart)
            except Exception as e:
                self.settings.set('autostart', old_autostart)
                QMessageBox.warning(self, "V-Link", f"Не удалось изменить автозапуск: {e}")

        restart_needed = (
            old_port != self.settings.port
            or old_secure_mode != self.settings.secure_mode
            or old_nonstandard_mode != self.settings.nonstandard_network_mode
            or old_relay_mode != self.settings.relay_mode
            or old_relay_url != self.settings.relay_server_url
            or old_relay_channel != self.settings.relay_channel
            or old_dir != self.settings.download_dir
        )
        if restart_needed and self.loop:
            async def restart_flow():
                await self._restart_services()
                if self._low_power_mode:
                    await self.enter_low_power_mode()
            asyncio.run_coroutine_threadsafe(restart_flow(), self.loop)

    async def _restart_services(self):
        await self.stop_services()
        await self.start_services()

    def _update_ip_label(self):
        if not self.discovery:
            self.ip_label.setText("")
            self.ip_label.setToolTip("")
            return

        ips = self.discovery.get_local_ips()
        primary = self.discovery.get_local_ip()
        port = self.server.port if self.server else self.settings.port

        self.ip_label.setText(f"IP: {primary}:{port}")
        if len(ips) > 1:
            self.ip_label.setToolTip("Локальные адреса:\n" + "\n".join(f"• {ip}:{port}" for ip in ips))
        else:
            self.ip_label.setToolTip(f"Локальный адрес: {primary}:{port}")

    def _schedule_network_sync(self):
        if self.loop and self.discovery:
            asyncio.run_coroutine_threadsafe(self._sync_network_state(), self.loop)

    async def _sync_network_state(self):
        if not self.discovery:
            return

        changed = await self.discovery.reconfigure_if_needed()
        if changed:
            QMetaObject.invokeMethod(self, "_on_network_changed", Qt.ConnectionType.QueuedConnection)

        QMetaObject.invokeMethod(self, "_on_ip_refresh", Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _on_network_changed(self):
        self.status_label.setText("● Сеть изменилась, адрес обновлён")
        self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")

    @pyqtSlot()
    def _on_ip_refresh(self):
        self._update_ip_label()
        if self.status_label.text().startswith("● Relay"):
            return
        if not self._low_power_mode and not (self.settings.relay_mode and not self.settings.relay_server_url):
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

    async def start_services(self):
        self._services_starting = True
        self._services_ready = False
        self.loop = asyncio.get_event_loop()
        secure_mode = self.settings.secure_mode
        manual_nonstandard_mode = self.settings.nonstandard_network_mode
        self._hotspot_detected = self._detect_hotspot_environment()
        compatibility_mode = manual_nonstandard_mode or self._hotspot_detected
        self._effective_nonstandard_mode = compatibility_mode
        relay_mode = self.settings.relay_mode
        relay_url = self.settings.relay_server_url
        auth_secret = SECURE_SHARED_SECRET if secure_mode else ""
        verify_checksum = secure_mode

        self.server = TransferServer(
            self.settings.port,
            self.settings.download_dir,
            auth_token=auth_secret,
            chunk_size_bytes=4 * 1024 * 1024,
            verify_checksum=verify_checksum,
            enable_encryption=secure_mode,
        )
        self.server.on_transfer_start = self._on_incoming_transfer_start
        self.server.on_transfer_progress = self._on_transfer_progress
        self.server.on_transfer_complete = self._on_transfer_complete
        self.server.on_transfer_error = self._on_transfer_error
        self.server.on_server_error = self._on_server_error
        actual_port = await self.server.start()

        self.discovery = DeviceDiscovery(actual_port, compatibility_mode=compatibility_mode)
        self.discovery.on_device_added = self._on_device_added
        self.discovery.on_device_removed = self._on_device_removed
        self.discovery.on_error = self._on_server_error
        await self.discovery.start()

        self.client = TransferClient(
            auth_token=auth_secret,
            base_chunk_size_bytes=4 * 1024 * 1024,
            verify_checksum=verify_checksum,
            auto_tune=True,
            adaptive_profile=self.settings.adaptive_profile,
            enable_encryption=secure_mode,
            compatibility_mode=compatibility_mode,
        )
        self.client.on_transfer_start = self._on_outgoing_transfer_start
        self.client.on_transfer_progress = self._on_transfer_progress
        self.client.on_transfer_complete = self._on_transfer_complete
        self.client.on_transfer_error = self._on_transfer_error
        await self.client.start()

        self.relay_peers.clear()
        relay_ready = False
        if relay_mode and relay_url:
            try:
                self.relay = RelayClient(
                    server_url=relay_url,
                    channel=self.settings.relay_channel,
                    client_id=self.settings.relay_client_id,
                    display_name=self.discovery.get_hostname() if self.discovery else "V-Link",
                    download_dir=self.settings.download_dir,
                    secure_mode=secure_mode,
                    auth_token=auth_secret,
                )
                self.relay.on_peer_added = self._on_relay_peer_added
                self.relay.on_peer_removed = self._on_relay_peer_removed
                self.relay.on_error = self._on_server_error
                self.relay.on_transfer_start = self._on_relay_transfer_start
                self.relay.on_transfer_progress = self._on_transfer_progress
                self.relay.on_transfer_complete = self._on_transfer_complete
                self.relay.on_transfer_error = self._on_transfer_error
                await self.relay.start()
                relay_ready = True
            except Exception as e:
                self._on_server_error(f"Relay init error: {e}")
                if self.relay:
                    try:
                        await self.relay.stop()
                    except Exception:
                        pass
                self.relay = None
                self.relay_peers.clear()
                self._clear_relay_devices()
        else:
            self.relay = None
            self._clear_relay_devices()

        self._update_ip_label()
        if relay_mode and not relay_url:
            self.status_label.setText("● Активен (Relay включён, но URL не задан)")
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
        elif self._hotspot_detected and not manual_nonstandard_mode:
            self.status_label.setText("● Активен (обнаружен хот-спот, включён совместимый режим)")
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
        elif compatibility_mode and relay_ready:
            self.status_label.setText("● Активен (нестандартные сети + Relay)")
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
        elif compatibility_mode:
            self.status_label.setText("● Активен (режим нестандартных сетей)")
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
        elif relay_ready:
            self.status_label.setText("● Активен (Relay)")
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
        else:
            self.status_label.setText("● Активен")
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

        if not self._network_timer.isActive():
            self._network_timer.start()

        self._services_ready = True
        self._services_starting = False

        # Auto-update check (non-blocking, respects 12h cache unless forced on startup?)
        # User requested: "check updates at program launch, cache 12h only for tray restore"
        # So we force check here.
        self._init_updater()
        asyncio.ensure_future(self._check_for_update(force=True))

    async def stop_services(self):
        self._services_ready = False
        self._services_starting = False
        if self._network_timer.isActive():
            self._network_timer.stop()

        if self.relay:
            await self.relay.stop()
            self.relay = None
            self.relay_peers.clear()

        if self.client:
            await self.client.stop()
            self.client = None
        if self.server:
            await self.server.stop()
            self.server = None
        if self.discovery:
            await self.discovery.stop()
            self.discovery = None

    async def enter_low_power_mode(self):
        if self._low_power_mode:
            return
        self._low_power_mode = True

        if self._network_timer.isActive():
            self._network_timer.stop()

        if self.client:
            await self.client.stop()
        if self.discovery:
            await self.discovery.pause_browsing()
        if self.relay:
            self.relay.set_low_power_mode(True)

        self.transfer_list.set_low_power_mode(True)
        self.status_label.setText("● Фон: экономия ресурсов")
        self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")

    async def exit_low_power_mode(self):
        if not self._low_power_mode:
            return
        self._low_power_mode = False

        if self.client:
            await self.client.start()
        if self.discovery:
            await self.discovery.resume_browsing()
        if self.relay:
            self.relay.set_low_power_mode(False)

        if not self._network_timer.isActive():
            self._network_timer.start()

        self.transfer_list.set_low_power_mode(False)
        self.status_label.setText("● Активен")
        self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

    def _on_server_error(self, error: str):
        if "Relay" in (error or ""):
            self.status_label.setText("● Relay временно недоступен")
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
        else:
            self.status_label.setText("● Ошибка")
            self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
        print(error)

    def _on_device_added(self, name: str, ip: str, port: int):
        is_online = True
        if self.discovery:
            try:
                for device in self.discovery.get_devices().values():
                    if (
                        str(device.get("name", "")) == name
                        and str(device.get("ip", "")) == ip
                        and int(device.get("port", 0) or 0) == int(port)
                    ):
                        is_online = bool(device.get("reachable", True))
                        break
            except Exception:
                is_online = True

        QMetaObject.invokeMethod(
            self.device_list,
            "add_device",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, name),
            Q_ARG(str, ip),
            Q_ARG(int, port),
            Q_ARG(bool, is_online),
        )

    def _on_device_removed(self, name: str, ip: str):
        if self.selected_device and self.selected_device[1] == ip:
            self.selected_device = None
        QMetaObject.invokeMethod(
            self.device_list,
            "remove_device",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, ip),
        )

    def _on_relay_peer_added(self, peer: Dict):
        peer_id = str(peer.get("id", "")).strip()
        if not peer_id:
            return

        self.relay_peers[peer_id] = dict(peer)
        peer_name = str(peer.get("name", "")).strip() or peer_id

        QMetaObject.invokeMethod(
            self.device_list,
            "add_device",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, f"[Relay] {peer_name}"),
            Q_ARG(str, f"relay:{peer_id}"),
            Q_ARG(int, 0),
            Q_ARG(bool, True),
        )

    def _on_relay_peer_removed(self, peer: Dict):
        peer_id = str(peer.get("id", "")).strip()
        if not peer_id:
            return
        self.relay_peers.pop(peer_id, None)
        relay_ip = f"relay:{peer_id}"
        if self.selected_device and self.selected_device[1] == relay_ip:
            self.selected_device = None

        QMetaObject.invokeMethod(
            self.device_list,
            "remove_device",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, relay_ip),
        )

    @pyqtSlot()
    def _clear_relay_devices(self):
        if self.selected_device and str(self.selected_device[1]).startswith("relay:"):
            self.selected_device = None
            self.device_list.clear_selection()
        relay_ips = [
            card.device_ip
            for card in list(self.device_list.devices)
            if str(card.device_ip).startswith("relay:")
        ]
        for relay_ip in relay_ips:
            self.device_list.remove_device(relay_ip)

    def _relay_peer_from_selection(self) -> Optional[str]:
        if not self.selected_device:
            return None
        _name, ip, _port = self.selected_device
        if isinstance(ip, str) and ip.startswith("relay:"):
            return ip.split(":", 1)[1].strip() or None
        return None

    @pyqtSlot(str, str, int)
    def _on_device_selected(self, name: str, ip: str, port: int):
        self.selected_device = (name, ip, port)
        if str(ip).startswith("relay:"):
            self.status_label.setText(f"● Выбрано Relay: {name}")
        else:
            is_online = True
            if self.discovery:
                for device in self.discovery.get_devices().values():
                    if (
                        str(device.get("name", "")) == name
                        and str(device.get("ip", "")) == ip
                        and int(device.get("port", 0) or 0) == int(port)
                    ):
                        is_online = bool(device.get("reachable", True))
                        break
            if is_online:
                self.status_label.setText(f"● Выбрано: {name}")
            else:
                self.status_label.setText(f"● Выбрано: {name} (может быть недоступно)")
                self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")

    @pyqtSlot(list)
    def _on_files_dropped(self, files: List[str]):
        if self._low_power_mode and self.loop:
            asyncio.run_coroutine_threadsafe(self.exit_low_power_mode(), self.loop)
            QMetaObject.invokeMethod(self, "_show_services_starting", Qt.ConnectionType.QueuedConnection)
            return

        if self._services_starting or not self._services_ready:
            QMetaObject.invokeMethod(self, "_show_services_starting", Qt.ConnectionType.QueuedConnection)
            return

        if not self.selected_device:
            fallback_selected = self.device_list.get_selected_device()
            if fallback_selected:
                self.selected_device = fallback_selected
            else:
                QMessageBox.information(self, "V-Link", "Сначала выберите устройство из списка")
                return

        if not self.selected_device:
            QMessageBox.information(self, "V-Link", "Сначала выберите устройство из списка")
            return

        valid_files = [f for f in files if os.path.exists(f)]
        if not valid_files:
            QMessageBox.warning(self, "V-Link", "Файлы не найдены")
            return

        name, ip, port = self.selected_device

        async def send_with_ping():
            relay_peer_id = self._relay_peer_from_selection()
            if relay_peer_id:
                if not self.relay or not self.relay.has_peer(relay_peer_id):
                    QMetaObject.invokeMethod(self, "_show_relay_unavailable", Qt.ConnectionType.QueuedConnection)
                    return
                try:
                    self.status_label.setText("● Передача через Relay...")
                    await self.relay.send_files(valid_files, relay_peer_id, target_name=name)
                    return
                except Exception as e:
                    relay_error = str(e)
                    if self._is_security_mismatch_error(relay_error):
                        QMetaObject.invokeMethod(self, "_show_security_mismatch_warning", Qt.ConnectionType.QueuedConnection)
                        return
                    QMetaObject.invokeMethod(
                        self,
                        "_show_transfer_failed",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, f"Relay: {relay_error}"),
                    )
                    return

            if not self.client:
                return

            candidates: list[tuple[str, int]] = [(ip, port)]
            if self.discovery:
                for device in self.discovery.get_devices().values():
                    same_name = device.get('name') == name
                    same_endpoint = (
                        str(device.get('ip', '')) == str(ip)
                        and int(device.get('port', port) or port) == int(port)
                    )
                    if same_name or same_endpoint:
                        dev_port = int(device.get('port', port) or port)
                        for alt_ip in device.get('ips', []):
                            candidate = (alt_ip, dev_port)
                            if candidate not in candidates:
                                candidates.append(candidate)

            ranked: list[tuple[str, int]] = []
            ping_timeout = 3.5 if self._effective_nonstandard_mode else 2.0
            ping_retries = 2 if self._effective_nonstandard_mode else 1
            for candidate_ip, candidate_port in candidates:
                ok = await self.client.ping(candidate_ip, candidate_port, timeout=ping_timeout, retries=ping_retries)
                if ok:
                    ranked.insert(0, (candidate_ip, candidate_port))
                else:
                    ranked.append((candidate_ip, candidate_port))

            last_error = None
            for candidate_ip, candidate_port in ranked:
                try:
                    self.status_label.setText(f"● Проверка маршрута: {candidate_ip}:{candidate_port}")
                    await self.client.send_files(valid_files, candidate_ip, candidate_port, target_name=name)
                    if (candidate_ip, candidate_port) != (ip, port):
                        self.selected_device = (name, candidate_ip, candidate_port)
                        self.status_label.setText(f"● Обновлён адрес: {name} ({candidate_ip}:{candidate_port})")
                    self.settings.set('adaptive_profile', self.client.get_adaptive_profile())
                    return
                except Exception as e:
                    last_error = str(e)
                    continue

            if self.relay:
                relay_peer_id = self.relay.find_peer_by_name(name)
                if relay_peer_id and self.relay.has_peer(relay_peer_id):
                    try:
                        self.status_label.setText("● Прямой маршрут недоступен, пробуем Relay...")
                        await self.relay.send_files(valid_files, relay_peer_id, target_name=name)
                        self.selected_device = (name, f"relay:{relay_peer_id}", 0)
                        return
                    except Exception as e:
                        last_error = str(e)

            if last_error:
                if self._is_security_mismatch_error(last_error):
                    QMetaObject.invokeMethod(self, "_show_security_mismatch_warning", Qt.ConnectionType.QueuedConnection)
                    return
                if self._is_connectivity_error(last_error):
                    QMetaObject.invokeMethod(self, "_show_device_unavailable", Qt.ConnectionType.QueuedConnection)
                    return
                QMetaObject.invokeMethod(
                    self,
                    "_show_transfer_failed",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, last_error),
                )
                return

            QMetaObject.invokeMethod(self, "_show_device_unavailable", Qt.ConnectionType.QueuedConnection)

        if self.loop:
            asyncio.run_coroutine_threadsafe(send_with_ping(), self.loop)

    @pyqtSlot()
    def _show_device_unavailable(self):
        device_info = ""
        if self.selected_device:
            name, ip, port = self.selected_device
            device_info = f"\n\nУстройство: {name}\nIP: {ip}:{port}"

        QMessageBox.warning(
            self,
            "V-Link",
            "Устройство обнаружено, но сейчас не отвечает.\n\n"
            "Возможные причины:\n"
            "• V-Link не запущен на другом устройстве\n"
            "• Брандмауэр или VPN блокируют соединение\n"
            "• Устройства в разных сетях\n"
            "• Сеть с изоляцией клиентов (guest/AP isolation) запрещает прямые подключения\n"
            "• Для вузов/хотспотов включите «Режим нестандартных сетей» в настройках\n"
            "• Если один ноутбук раздаёт Wi‑Fi, профиль хот-спота включается автоматически\n"
            "• Relay-режим нужен только как дополнительный вариант, если прямой режим недоступен"
            f"{device_info}",
        )
        self.selected_device = None
        self.device_list.clear_selection()
        self.status_label.setText("● Готов к работе")

    @pyqtSlot()
    def _show_relay_unavailable(self):
        QMessageBox.warning(
            self,
            "V-Link",
            "Relay-устройство недоступно.\n\n"
            "Проверьте:\n"
            "• Оба устройства онлайн и подключены к одному Relay-каналу\n"
            "• Relay URL одинаковый на обоих устройствах\n"
            "• Relay-сервер запущен",
        )
        self.selected_device = None
        self.device_list.clear_selection()
        self.status_label.setText("● Готов к работе")

    def _on_incoming_transfer_start(self, transfer_id: str, filename: str, total_size: int, is_upload: bool):
        item = self.transfer_list.add_transfer(transfer_id, filename, total_size, False)
        if self._low_power_mode:
            item.set_low_power_mode(True)
        self._transfer_directions[transfer_id] = ("in", total_size)

    def _on_outgoing_transfer_start(self, transfer_id: str, filename: str, total_size: int, is_upload: bool):
        item = self.transfer_list.add_transfer(transfer_id, filename, total_size, True)
        if self._low_power_mode:
            item.set_low_power_mode(True)
        self._transfer_directions[transfer_id] = ("out", total_size)

    def _on_relay_transfer_start(self, transfer_id: str, filename: str, total_size: int, is_upload: bool):
        if is_upload:
            self._on_outgoing_transfer_start(transfer_id, filename, total_size, is_upload)
        else:
            self._on_incoming_transfer_start(transfer_id, filename, total_size, is_upload)

    def _on_transfer_progress(self, transfer_id: str, transferred: int, speed: float):
        self.transfer_list.update_transfer(transfer_id, transferred, speed)

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if abs(size_bytes) < 1024:
                return f"{size_bytes:.1f} {unit}" if unit != "Б" else f"{size_bytes} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} ТБ"

    def _on_transfer_complete(self, transfer_id: str, filepath: str):
        self.transfer_list.complete_transfer(transfer_id, filepath)
        if self.tray_icon.isVisible():
            direction, size = self._transfer_directions.pop(transfer_id, ("in", 0))
            name = os.path.basename(filepath)
            if direction == "in":
                msg = f"📥 Получен: {name}"
            else:
                msg = f"📤 Отправлен: {name}"
            if size > 0:
                msg += f" ({self._human_size(size)})"
            self.tray_icon.showMessage(
                "V-Link",
                msg,
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def _is_security_mismatch_error(self, error: str) -> bool:
        lower = (error or "").lower()
        return (
            "unauthorized" in lower
            or "401" in lower
            or "encrypted mode is not enabled on receiver" in lower
            or "security mode mismatch" in lower
            or "secure_mode_mismatch" in lower
        )

    def _is_connectivity_error(self, error: str) -> bool:
        lower = (error or "").lower()
        patterns = [
            "cannot connect",
            "connection refused",
            "no route",
            "timed out",
            "timeout",
            "server disconnected",
            "clientconnectorerror",
            "name or service not known",
        ]
        return any(p in lower for p in patterns)

    @pyqtSlot()
    def _show_security_mismatch_warning(self):
        now = time.monotonic()
        if now - self._last_security_warning_ts < 1.5:
            return
        self._last_security_warning_ts = now
        QMessageBox.warning(
            self,
            "V-Link",
            "Передача отклонена из-за несовпадения Безопасного режима.\n\n"
            "Проверьте, что на обоих устройствах этот режим либо включен, либо выключен.",
        )

    @pyqtSlot(str)
    def _show_transfer_failed(self, error: str):
        short = (error or "").strip()
        if len(short) > 300:
            short = short[:300] + "..."
        self.status_label.setText("● Ошибка передачи")
        self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
        QMessageBox.warning(
            self,
            "V-Link",
            "Передача не выполнена.\n\n"
            f"Причина: {short}",
        )

    def _on_transfer_error(self, transfer_id: str, error: str):
        self.transfer_list.error_transfer(transfer_id, error)
        if self._is_security_mismatch_error(error):
            self.status_label.setText("● Проверьте, что Безопасный режим одинаков на обоих устройствах")
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
            QMetaObject.invokeMethod(self, "_show_security_mismatch_warning", Qt.ConnectionType.QueuedConnection)

    def closeEvent(self, event: QCloseEvent):
        if self.settings.close_to_tray:
            event.ignore()
            self.hide()
            if self.loop:
                asyncio.run_coroutine_threadsafe(self.enter_low_power_mode(), self.loop)
            self.tray_icon.showMessage(
                "V-Link",
                "Программа свёрнута в трей",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            return

        event.accept()
        self._quit_app()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _show_window(self):
        self.show()
        self.activateWindow()
        self.raise_()
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.exit_low_power_mode(), self.loop)
            asyncio.run_coroutine_threadsafe(self._check_for_update(), self.loop)

    @pyqtSlot()
    def _finalize_quit(self):
        QApplication.quit()

    # ------------------------------------------------------------------
    # Auto-update
    # ------------------------------------------------------------------

    def _init_updater(self):
        if self.updater:
            return
        self.updater = Updater(self.settings)
        self.updater.on_update_available = self._on_update_available

    def _on_update_available(self, version: str, body: str):
        QMetaObject.invokeMethod(
            self, "_show_update_button",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, version),
        )

    @pyqtSlot(str)
    def _show_update_button(self, version: str):
        self.update_btn.setText(f"⬆ {version}")
        self.update_btn.setToolTip(f"Доступно обновление V-Link {version}")
        self.update_btn.setVisible(True)

    async def _check_for_update(self, force: bool = False):
        if self._low_power_mode:
            return
        if not self.updater:
            return
        try:
            await self.updater.check_for_update(force=force)
        except Exception:
            pass

    @pyqtSlot()
    def _show_update_dialog(self):
        if not self.updater or not self.updater.has_update:
            return

        version = self.updater.update_version
        body = self.updater.update_body or "Нет описания."

        msg = QMessageBox(self)
        msg.setWindowTitle("V-Link — Обновление")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(f"Доступна новая версия: <b>{version}</b>")
        # Strip markdown formatting for plain-text QMessageBox display
        import re
        clean_body = body
        clean_body = re.sub(r'^#{1,6}\s*', '', clean_body, flags=re.MULTILINE)  # ## headers
        clean_body = re.sub(r'\*\*(.+?)\*\*', r'\1', clean_body)  # **bold**
        clean_body = re.sub(r'\*(.+?)\*', r'\1', clean_body)  # *italic*
        clean_body = re.sub(r'^\s*[-\*]\s+', '• ', clean_body, flags=re.MULTILINE)  # - list items
        clean_body = clean_body.strip()
        msg.setInformativeText(clean_body[:800])
        btn_update = msg.addButton("Обновить", QMessageBox.ButtonRole.AcceptRole)
        btn_skip = msg.addButton("Пропустить", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(btn_update)
        msg.exec()

        if msg.clickedButton() == btn_update:
            if self.loop:
                asyncio.run_coroutine_threadsafe(self._do_update(), self.loop)
        elif msg.clickedButton() == btn_skip:
            self.updater.skip_version()
            self.update_btn.setVisible(False)

    async def _do_update(self):
        if not self.updater:
            return

        QMetaObject.invokeMethod(self, "_update_status_downloading",
                                 Qt.ConnectionType.QueuedConnection)

        self.updater.on_download_progress = self._on_update_download_progress

        downloaded = await self.updater.download_update()

        if not downloaded:
            QMetaObject.invokeMethod(self, "_update_status_error",
                                     Qt.ConnectionType.QueuedConnection)
            return

        QMetaObject.invokeMethod(self, "_apply_update",
                                 Qt.ConnectionType.QueuedConnection,
                                 Q_ARG(str, str(downloaded)))

    def _on_update_download_progress(self, percent: int):
        QMetaObject.invokeMethod(
            self, "_update_download_progress_ui",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, percent),
        )

    @pyqtSlot(int)
    def _update_download_progress_ui(self, percent: int):
        self.status_label.setText(f"● Скачивание обновления: {percent}%")
        self.status_label.setStyleSheet("color: #6b5ce7; font-size: 12px;")

    @pyqtSlot()
    def _update_status_downloading(self):
        self.status_label.setText("● Скачивание обновления...")
        self.status_label.setStyleSheet("color: #6b5ce7; font-size: 12px;")
        self.update_btn.setEnabled(False)

    @pyqtSlot()
    def _update_status_error(self):
        self.status_label.setText("● Ошибка загрузки обновления")
        self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
        self.update_btn.setEnabled(True)

    @pyqtSlot(str)
    def _apply_update(self, downloaded_path: str):
        from pathlib import Path

        reply = QMessageBox.question(
            self,
            "V-Link",
            "Обновление скачано. Перезапустить приложение?\n\n"
            "V-Link закроется, обновится и запустится заново.\n"
            "Настройки будут сохранены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.status_label.setText("● Обновление отложено")
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
            self.update_btn.setEnabled(True)
            return

        self.status_label.setText("● Применение обновления...")
        self.status_label.setStyleSheet("color: #6b5ce7; font-size: 12px;")

        self.updater.apply_update(Path(downloaded_path))
        self._quit_app()

    def _quit_app(self):
        if self._quitting:
            return
        self._quitting = True
        self.status_label.setText("● Завершение...")
        self.status_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.tray_icon.hide()

        if self.loop:
            future = asyncio.run_coroutine_threadsafe(self.stop_services(), self.loop)
            future.add_done_callback(
                lambda _f: QMetaObject.invokeMethod(
                    self,
                    "_finalize_quit",
                    Qt.ConnectionType.QueuedConnection,
                )
            )
            return

        self._finalize_quit()
