"""
V-Link - Main Window
"""

import asyncio
import os
import sys
import time
from typing import List, Optional

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

from core import Settings, set_autostart
from network import DeviceDiscovery, TransferClient, TransferServer
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
        self.selected_device: Optional[tuple] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._low_power_mode = False
        self._last_security_warning_ts = 0.0

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

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        icon_path = "app_icon.ico"
        if hasattr(sys, '_MEIPASS'):
            icon_path = os.path.join(sys._MEIPASS, icon_path)

        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(QIcon("app_icon.ico"))
        self.tray_icon.setToolTip("V-Link")

        tray_menu = QMenu()

        show_action = QAction("Показать", self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)

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

    def _refresh_devices(self):
        if self.discovery and self.loop:
            self.device_list.clear_devices()
            self.status_label.setText("● Обновление...")
            asyncio.run_coroutine_threadsafe(self.discovery.refresh(), self.loop)

    def _open_settings(self):
        old_port = self.settings.port
        old_secure_mode = self.settings.secure_mode
        old_nonstandard_mode = self.settings.nonstandard_network_mode
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
        if not self._low_power_mode:
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

    async def start_services(self):
        self.loop = asyncio.get_event_loop()
        secure_mode = self.settings.secure_mode
        compatibility_mode = self.settings.nonstandard_network_mode
        auth_secret = SECURE_SHARED_SECRET if secure_mode else ""
        verify_checksum = secure_mode

        self.server = TransferServer(
            self.settings.port,
            self.settings.download_dir,
            auth_token=auth_secret,
            chunk_size_bytes=512 * 1024 if compatibility_mode else 4 * 1024 * 1024,
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
            base_chunk_size_bytes=512 * 1024 if compatibility_mode else 4 * 1024 * 1024,
            verify_checksum=verify_checksum,
            auto_tune=not compatibility_mode,
            adaptive_profile=self.settings.adaptive_profile,
            enable_encryption=secure_mode,
            compatibility_mode=compatibility_mode,
        )
        self.client.on_transfer_start = self._on_outgoing_transfer_start
        self.client.on_transfer_progress = self._on_transfer_progress
        self.client.on_transfer_complete = self._on_transfer_complete
        self.client.on_transfer_error = self._on_transfer_error
        await self.client.start()

        self._update_ip_label()
        if compatibility_mode:
            self.status_label.setText("● Активен (режим нестандартных сетей)")
        else:
            self.status_label.setText("● Активен")
        self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

        if not self._network_timer.isActive():
            self._network_timer.start()

    async def stop_services(self):
        if self._network_timer.isActive():
            self._network_timer.stop()

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

        if not self._network_timer.isActive():
            self._network_timer.start()

        self.transfer_list.set_low_power_mode(False)
        self.status_label.setText("● Активен")
        self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

    def _on_server_error(self, error: str):
        self.status_label.setText("● Ошибка")
        self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
        print(error)

    def _on_device_added(self, name: str, ip: str, port: int):
        QMetaObject.invokeMethod(
            self.device_list,
            "add_device",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, name),
            Q_ARG(str, ip),
            Q_ARG(int, port),
            Q_ARG(bool, True),
        )

    def _on_device_removed(self, name: str, ip: str):
        QMetaObject.invokeMethod(
            self.device_list,
            "remove_device",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, ip),
        )

    @pyqtSlot(str, str, int)
    def _on_device_selected(self, name: str, ip: str, port: int):
        self.selected_device = (name, ip, port)
        self.status_label.setText(f"● Выбрано: {name}")

    @pyqtSlot(list)
    def _on_files_dropped(self, files: List[str]):
        if self._low_power_mode and self.loop:
            asyncio.run_coroutine_threadsafe(self.exit_low_power_mode(), self.loop)

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
            if not self.client:
                return

            candidates: list[tuple[str, int]] = [(ip, port)]
            if self.discovery:
                for device in self.discovery.get_devices().values():
                    if device.get('name') == name:
                        dev_port = int(device.get('port', port) or port)
                        for alt_ip in device.get('ips', []):
                            candidate = (alt_ip, dev_port)
                            if candidate not in candidates:
                                candidates.append(candidate)

            # Quick availability ranking, but don't block on ping-only failures.
            ranked: list[tuple[str, int]] = []
            ping_timeout = 3.5 if self.settings.nonstandard_network_mode else 2.0
            ping_retries = 2 if self.settings.nonstandard_network_mode else 1
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
            "Устройство не отвечает.\n\n"
            "Возможные причины:\n"
            "• V-Link не запущен на другом устройстве\n"
            "• Брандмауэр или VPN блокируют соединение\n"
            "• Устройства в разных сетях\n"
            "• Сеть с изоляцией клиентов (guest/AP isolation) запрещает прямые подключения"
            f"{device_info}",
        )
        self.selected_device = None
        self.device_list.clear_selection()
        self.status_label.setText("● Готов к работе")

    def _on_incoming_transfer_start(self, transfer_id: str, filename: str, total_size: int, is_upload: bool):
        item = self.transfer_list.add_transfer(transfer_id, filename, total_size, False)
        if self._low_power_mode:
            item.set_low_power_mode(True)

    def _on_outgoing_transfer_start(self, transfer_id: str, filename: str, total_size: int, is_upload: bool):
        item = self.transfer_list.add_transfer(transfer_id, filename, total_size, True)
        if self._low_power_mode:
            item.set_low_power_mode(True)

    def _on_transfer_progress(self, transfer_id: str, transferred: int, speed: float):
        self.transfer_list.update_transfer(transfer_id, transferred, speed)

    def _on_transfer_complete(self, transfer_id: str, filepath: str):
        self.transfer_list.complete_transfer(transfer_id, filepath)
        if self.tray_icon.isVisible():
            self.tray_icon.showMessage(
                "V-Link",
                f"Файл обработан: {os.path.basename(filepath)}",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def _is_security_mismatch_error(self, error: str) -> bool:
        lower = (error or "").lower()
        return (
            "unauthorized" in lower
            or "401" in lower
            or "encrypted mode is not enabled on receiver" in lower
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

    def _quit_app(self):
        if self.loop:
            future = asyncio.run_coroutine_threadsafe(self.stop_services(), self.loop)
            try:
                future.result(timeout=2)
            except Exception:
                pass

        self.tray_icon.hide()
        QApplication.quit()
