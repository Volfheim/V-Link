"""
V-Link - Main Window
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from typing import Any, Coroutine, Dict, List, Optional

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import Settings, Updater, i18n, set_autostart, t
from core.clipboard_sync import ClipboardSyncManager
from core.explorer import reveal_in_explorer
from crash_reporter import record_exception, record_message
from version import __version__
from network import DeviceDiscovery, RelayClient, TransferClient, TransferServer
from ui import DeviceList, DropZone, TransferList, TransferSummaryDialog, get_stylesheet
from ui.settings_dialog import SettingsDialog

class MainWindow(QMainWindow):
    """Main window for V-Link."""

    def __init__(self, settings: Optional[Settings] = None):
        super().__init__()

        self.settings = settings or Settings()
        i18n.load(self.settings.language)
        self._ensure_autostart_registration()
        self.discovery: Optional[DeviceDiscovery] = None
        self.server: Optional[TransferServer] = None
        self.client: Optional[TransferClient] = None
        self.relay: Optional[RelayClient] = None
        self.updater: Optional[Updater] = None
        self.clipboard_sync: Optional[ClipboardSyncManager] = None
        self.mobile_dialog: Optional[object] = None
        self.relay_peers: Dict[str, Dict] = {}
        self.selected_device: Optional[tuple] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._low_power_mode = False
        self._last_security_warning_ts = 0.0
        self._hotspot_detected = False
        self._vpn_detected = False
        self._multinet_detected = False
        self._effective_nonstandard_mode = False
        self._services_ready = False
        self._services_starting = False
        self._quitting = False
        self._transfer_directions: Dict[str, tuple] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._notification_target_path = ""
        # Keep reference to manual update check dialog to prevent GC
        self._progress_dialog = None
        self._check_task = None

        self._network_timer = QTimer(self)
        self._network_timer.setInterval(15000)
        self._network_timer.timeout.connect(self._schedule_network_sync)

        self._setup_window()
        self._setup_ui()
        self._setup_tray()
        self._connect_signals()

        self.clipboard_sync = ClipboardSyncManager(
            self.settings,
            peer_provider=self._clipboard_peer_endpoints,
            parent=self,
        )

    def _ensure_autostart_registration(self):
        try:
            # Normalize autostart state on every startup:
            # rewrites stale registry command (e.g. legacy "--autostart") and
            # removes old Startup-folder scripts from previous versions.
            set_autostart(bool(self.settings.autostart))
        except Exception as e:
            # Non-fatal: app should continue even if OS startup registration failed.
            print(f"Autostart state sync failed: {e}")

    def _setup_window(self):
        self.setWindowTitle("V-Link")
        self.setMinimumSize(600, 700)
        self.resize(650, 750)
        app = QApplication.instance()
        if app and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())
        else:
            icon_candidates = []
            if hasattr(sys, "_MEIPASS"):
                icon_candidates.append(os.path.join(sys._MEIPASS, "app_icon.ico"))
            icon_candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app_icon.ico"))
            icon_candidates.append("app_icon.ico")
            for candidate in icon_candidates:
                try:
                    if os.path.exists(candidate):
                        icon = QIcon(candidate)
                        if not icon.isNull():
                            self.setWindowIcon(icon)
                            break
                except Exception:
                    continue
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
        title.setMinimumWidth(120)
        title.setObjectName("titleLabel")
        title_layout.addWidget(title)

        subtitle = QLabel(t("Быстрая передача файлов в локальной сети"))
        subtitle.setMinimumWidth(250)
        subtitle.setObjectName("subtitleLabel")
        title_layout.addWidget(subtitle)

        header.addLayout(title_layout)
        header.addStretch()

        self.update_btn = QPushButton(t("⬆ Обновить"))
        self.update_btn.setToolTip(t("Доступно обновление V-Link"))
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

        self.mobile_btn = QPushButton(t("Мобильник"))
        self.mobile_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: 1px solid #22c55e;
                color: #86efac;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(34, 197, 94, 0.15); }
            """
        )
        self.mobile_btn.setToolTip(t("Подключить телефон через веб-интерфейс"))
        self.mobile_btn.clicked.connect(self._open_mobile_connect)
        header.addWidget(self.mobile_btn)

        self.settings_btn = QPushButton(t("Настройки"))
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
        self.settings_btn.setToolTip(t("Открыть настройки"))
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)

        return header

    def _create_status_bar(self) -> QHBoxLayout:
        status = QHBoxLayout()

        self.status_label = QLabel(t("● Готов к работе"))
        self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
        status.addWidget(self.status_label)

        status.addStretch()

        self.ip_label = QLabel("")
        self.ip_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        status.addWidget(self.ip_label)

        return status

    def show_startup_state(self, message: str = ""):
        if not message:
            message = t("● Запуск сервисов...")
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")

    @pyqtSlot()
    def _show_services_starting(self):
        QMessageBox.information(
            self,
            "V-Link",
            t("Сетевые сервисы ещё запускаются. Попробуйте через пару секунд."),
        )

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        app = QApplication.instance()
        if app and not app.windowIcon().isNull():
            self.tray_icon.setIcon(app.windowIcon())
        else:
            icon_path = "app_icon.ico"
            if hasattr(sys, '_MEIPASS'):
                icon_path = os.path.join(sys._MEIPASS, icon_path)
            if os.path.exists(icon_path):
                self.tray_icon.setIcon(QIcon(icon_path))
            else:
                self.tray_icon.setIcon(QIcon("app_icon.ico"))
        self.tray_icon.setToolTip(f"V-Link v{__version__}")

        tray_menu = QMenu()

        show_action = QAction(t("Показать"), self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)

        hotspot_action = QAction(t("Хот-спот Windows"), self)
        hotspot_action.triggered.connect(self._open_hotspot_settings)
        tray_menu.addAction(hotspot_action)

        downloads_action = QAction(t("Открыть папку загрузок"), self)
        downloads_action.triggered.connect(self._open_downloads_folder)
        tray_menu.addAction(downloads_action)

        tray_menu.addSeparator()

        quit_action = QAction(t("Выход"), self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.messageClicked.connect(self._open_notification_target)
        self.tray_icon.show()

    def _show_tray_message(
        self,
        message: str,
        timeout_ms: int,
        target_path: str = "",
        title: str = "V-Link",
    ):
        self._notification_target_path = str(target_path or "").strip()
        self.tray_icon.showMessage(
            title,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            timeout_ms,
        )

    @pyqtSlot()
    def _open_notification_target(self):
        target_path = self._notification_target_path
        if not target_path:
            self._show_window()
            return
        if reveal_in_explorer(target_path):
            return

        self._show_window()
        QMessageBox.warning(
            self,
            "V-Link",
            t("Не удалось открыть файл в Проводнике:\n{path}", path=target_path),
        )

    def _connect_signals(self):
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.device_list.device_selected.connect(self._on_device_selected)
        self.device_list.refresh_clicked.connect(self._refresh_devices)

    def _schedule_task(
        self,
        coroutine: Coroutine[Any, Any, Any],
        source: str,
    ) -> Optional[asyncio.Task]:
        """Schedule a GUI-originated coroutine and always consume its exception."""
        if not self.loop or self.loop.is_closed():
            coroutine.close()
            record_message(source, "Task was not scheduled because the event loop is unavailable")
            return None

        try:
            task = self.loop.create_task(coroutine)
        except Exception as exc:
            coroutine.close()
            record_exception(source, exc)
            return None

        self._background_tasks.add(task)

        def task_done(done_task: asyncio.Task):
            self._background_tasks.discard(done_task)
            if done_task.cancelled():
                return
            try:
                error = done_task.exception()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                record_exception(f"{source}:inspect", exc)
                return
            if error:
                record_exception(source, error)

        task.add_done_callback(task_done)
        return task

    @staticmethod
    def _is_hotspot_ip(ip: str) -> bool:
        return str(ip).startswith("192.168.137.")

    def _detect_hotspot_environment(self) -> bool:
        try:
            ips: set[str] = set()

            # Fast route check, avoids heavy shell probes on startup.
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                ips.add(s.getsockname()[0])
            except Exception:
                pass
            finally:
                s.close()

            try:
                _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
                ips.update(host_ips)
            except Exception:
                pass

            return any(self._is_hotspot_ip(ip) for ip in ips if ip and not ip.startswith("127."))
        except Exception:
            return False

    def _open_hotspot_settings(self):
        try:
            os.startfile("ms-settings:network-mobilehotspot")
        except Exception:
            QMessageBox.information(
                self,
                "V-Link",
                t("Откройте вручную:\nПараметры Windows -> Сеть и Интернет -> Мобильный хот-спот"),
            )

    def _open_downloads_folder(self):
        folder = self.settings.download_dir
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except Exception:
            QMessageBox.warning(self, "V-Link", t("Не удалось открыть папку:\n{folder}", folder=folder))

    def _best_mobile_ip(self) -> str:
        try:
            ips = TransferServer._physical_lan_ips()
            if ips:
                return ips[0]
        except Exception:
            pass

        ips = self._mobile_ip_candidates()
        return ips[0] if ips else "127.0.0.1"

    @staticmethod
    def _probe_local_lan_endpoint(host: str, port: int) -> Optional[str]:
        host = str(host or "").strip()
        if not host or host.startswith("127."):
            return None
        try:
            with socket.create_connection((host, int(port)), timeout=0.8):
                return None
        except OSError as e:
            return str(e)

    @staticmethod
    def _mobile_iface_score(iface_name: str, ip: str) -> tuple[int, int, str]:
        name = str(iface_name or "").lower()
        ip = str(ip or "").strip()
        vpn_penalty = 10 if DeviceDiscovery._is_vpn_iface_name(name) else 0
        lan_bonus = 0
        lan_markers = (
            "wi-fi",
            "wifi",
            "wireless",
            "wlan",
            "ethernet",
            "local area",
            "беспровод",
            "локальная сеть",
        )
        if any(marker in name for marker in lan_markers):
            lan_bonus = -2
        if ip.startswith("192.168.137."):
            block_rank = 0
        elif ip.startswith("192.168."):
            block_rank = 1
        elif ip.startswith("10."):
            block_rank = 2
        elif ip.startswith("172."):
            block_rank = 3
        else:
            block_rank = 4
        return (vpn_penalty + lan_bonus, block_rank, ip)

    def _mobile_ip_candidates(self) -> List[str]:
        if not self.discovery:
            return []

        fallback_ips = self.discovery.get_local_ips()
        pairs = []
        try:
            pairs = DeviceDiscovery._windows_interface_ip_pairs(timeout_sec=1.8)
        except Exception:
            pairs = []

        local_set = set(fallback_ips)
        ranked: list[tuple[tuple[int, int, str], str]] = []
        seen: set[str] = set()

        for iface_name, ip in pairs:
            ip = str(ip or "").strip()
            if ip not in local_set or ip in seen:
                continue
            if not DeviceDiscovery._is_valid_local_ip_static(ip):
                continue
            seen.add(ip)
            ranked.append((self._mobile_iface_score(iface_name, ip), ip))

        for ip in fallback_ips:
            ip = str(ip or "").strip()
            if not ip or ip in seen:
                continue
            seen.add(ip)
            ranked.append((self._mobile_iface_score("", ip), ip))

        ranked.sort(key=lambda item: item[0])
        return [ip for _score, ip in ranked]

    def _open_mobile_connect(self):
        from ui.mobile_connect_dialog import MobileConnectDialog

        if not self.server or not self.server.is_running():
            QMessageBox.information(
                self,
                "V-Link",
                t("Сервисы ещё запускаются. Подождите несколько секунд и повторите."),
            )
            return

        if self.mobile_dialog and self.mobile_dialog.isVisible():
            self.mobile_dialog.raise_()
            self.mobile_dialog.activateWindow()
            return

        token = self.server.enable_mobile_share(ttl_sec=0)
        host_ip = self._best_mobile_ip()
        url = self.server.get_mobile_url(host_ip)

        probe_error = self._probe_local_lan_endpoint(host_ip, self.server.port)
        if probe_error:
            QMessageBox.warning(
                self,
                "V-Link",
                t(
                    "ПК сейчас сам не может открыть свой LAN-адрес:\n"
                    "{url}\n\n"
                    "Скорее всего, VPN или его firewall на ПК блокирует локальную сеть.\n"
                    "Включите в VPN параметр Allow LAN traffic / Разрешить локальную сеть "
                    "или временно отключите VPN-firewall, затем откройте это окно заново.\n\n"
                    "Ошибка проверки: {error}",
                    url=url,
                    error=probe_error,
                ),
            )

        dialog = MobileConnectDialog(url=url, token=token, parent=self)
        dialog.finished.connect(self._on_mobile_dialog_closed)
        self.mobile_dialog = dialog
        self.mobile_dialog.show()

        self.status_label.setText(t("● Мобильный доступ активен"))
        self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

    def _on_mobile_dialog_closed(self):
        if self.server:
            self.server.disable_mobile_share()
        self.mobile_dialog = None
        if not self._low_power_mode:
            self.status_label.setText(t("● Активен"))
            self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

    def _clipboard_peer_endpoints(self) -> List[tuple[str, int]]:
        if not self.discovery:
            return []
        devices = self.discovery.get_devices()
        local_ips = set(self.discovery.get_local_ips())
        seen: set[tuple[str, int]] = set()
        endpoints: List[tuple[str, int]] = []
        for dev in devices.values():
            if not bool(dev.get("reachable", True)):
                continue
            port = int(dev.get("port", self.settings.port) or self.settings.port)
            ips = []
            first_ip = str(dev.get("ip", "")).strip()
            if first_ip:
                ips.append(first_ip)
            for alt_ip in dev.get("ips", []) or []:
                alt = str(alt_ip).strip()
                if alt:
                    ips.append(alt)
            for ip in ips:
                if ip in local_ips or ip.startswith("127."):
                    continue
                pair = (ip, port)
                if pair in seen:
                    continue
                seen.add(pair)
                endpoints.append(pair)
        return endpoints

    def _on_clipboard_payload(self, payload: dict):
        if self.clipboard_sync:
            self.clipboard_sync.apply_remote_payload(payload)

    def _refresh_devices(self):
        if self.discovery and self.loop:
            async def do_refresh():
                await self.discovery.refresh()
                if self.relay:
                    try:
                        await self.relay.refresh_peers()
                    except Exception as e:
                        self._on_server_error(f"Relay refresh error: {e}")
            self._schedule_task(do_refresh(), "refresh_devices")

    def _open_settings(self):
        old_port = self.settings.port
        old_secure_mode = self.settings.secure_mode
        old_nonstandard_mode = self.settings.nonstandard_network_mode
        old_relay_mode = self.settings.relay_mode
        old_relay_url = self.settings.relay_server_url
        old_relay_channel = self.settings.relay_channel
        old_dir = self.settings.download_dir
        old_autostart = self.settings.autostart
        old_clipboard_sync = self.settings.clipboard_sync_enabled
        old_clipboard_images = self.settings.clipboard_sync_images
        old_language = self.settings.language

        dialog = SettingsDialog(self.settings, self)
        dialog.check_updates_clicked.connect(lambda: self._manual_update_check(dialog))
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.device_list.default_port = self.settings.port

        if old_autostart != self.settings.autostart:
            try:
                set_autostart(self.settings.autostart)
            except Exception as e:
                self.settings.set('autostart', old_autostart)
                QMessageBox.warning(self, "V-Link", t("Не удалось изменить автозапуск: {error}", error=e))

        if self.clipboard_sync and (
            old_clipboard_sync != self.settings.clipboard_sync_enabled
            or old_clipboard_images != self.settings.clipboard_sync_images
        ):
            self.clipboard_sync.refresh_from_settings()

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
            self._schedule_task(restart_flow(), "restart_services")

        if old_language != self.settings.language:
            i18n.load(self.settings.language)
            self._prompt_language_restart(old_language)

    def _prompt_language_restart(self, previous_language: str):
        answer = QMessageBox.question(
            self,
            "V-Link",
            t("Обнаружено изменение языка. Перезапустить приложение сейчас, чтобы применить локализацию?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._restart_app_for_language()
            return
        i18n.load(previous_language)
        QMessageBox.information(self, "V-Link", t("Язык будет применён после следующего запуска."))

    def _restart_app_for_language(self):
        try:
            Updater._reset_windows_dll_directory()
            env = Updater._sanitized_child_env()

            if getattr(sys, "frozen", False):
                exe_path = os.path.abspath(sys.executable)
                workdir = os.path.dirname(exe_path)
                arg_list = "@('--show-after-update')"
            else:
                exe_path = os.path.abspath(sys.executable)
                workdir = os.path.dirname(os.path.abspath(__file__))
                main_py = os.path.join(workdir, "main.py")
                arg_list = "@('" + main_py.replace("'", "''") + "')"

            pid_to_wait = int(os.getpid())
            exe_path_ps = exe_path.replace("'", "''")
            workdir_ps = workdir.replace("'", "''")
            ps_command = (
                f"$pidToWait={pid_to_wait}; "
                "for ($i=0; $i -lt 120; $i++) { "
                "if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) { break }; "
                "Start-Sleep -Milliseconds 250 "
                "}; "
                f"Start-Process -FilePath '{exe_path_ps}' "
                f"-WorkingDirectory '{workdir_ps}' "
                f"-ArgumentList {arg_list}"
            )

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

            subprocess.Popen(
                [
                    Updater._powershell_exe(),
                    "-NoProfile",
                    "-WindowStyle",
                    "Hidden",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps_command,
                ],
                env=env,
                startupinfo=startupinfo,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                close_fds=True,
            )
        except Exception:
            try:
                if getattr(sys, "frozen", False):
                    subprocess.Popen([sys.executable, "--show-after-update"])
                else:
                    main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
                    subprocess.Popen([sys.executable, main_py])
            except Exception:
                pass
        self._quit_app()

    def _manual_update_check(self, settings_dialog):
        if not self.updater:
            return

        # Модальный прогресс поверх настроек
        self._progress_dialog = QProgressDialog(
            t("Поиск обновлений..."),
            t("Отмена"),
            0,
            0,
            settings_dialog,
        )
        self._progress_dialog.setWindowTitle("V-Link")
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.setMinimumDuration(0)
        
        # Connect cancel button
        self._progress_dialog.canceled.connect(self._on_manual_check_canceled)
        
        self._progress_dialog.show()

        # Run the check in the shared Qt/asyncio loop.
        if self.loop:
            self._check_task = self._schedule_task(
                self._run_manual_check(settings_dialog),
                "manual_update_check",
            )

    def _on_manual_check_canceled(self):
        if hasattr(self, '_check_task') and self._check_task:
            self._check_task.cancel()

    async def _run_manual_check(self, settings_dialog):
        try:
            # Force check ignoring 12h timer
            info = await self.updater.check_for_update(force=True)
            
            if self._progress_dialog:
                self._progress_dialog.close()
                self._progress_dialog = None

            if info:
                # Close settings dialog so user can see download progress in main window
                if settings_dialog:
                    settings_dialog.close()
                # If update found, show the update dialog immediately
                self._show_update_dialog()
            else:
                QMessageBox.information(
                    settings_dialog, 
                    "V-Link", 
                    t("У вас установлена последняя версия.")
                )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self._progress_dialog:
                self._progress_dialog.close()
                self._progress_dialog = None
            
            QMessageBox.warning(
                settings_dialog, 
                "V-Link", 
                t("Ошибка проверки:\n{error}", error=e)
            )
        finally:
            self._check_task = None

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
            address_list = "\n".join(f"• {ip}:{port}" for ip in ips)
            self.ip_label.setToolTip(t("Локальные адреса:\n{addresses}", addresses=address_list))
        else:
            self.ip_label.setToolTip(t("Локальный адрес: {address}", address=f"{primary}:{port}"))

    def _schedule_network_sync(self):
        if self.loop and self.discovery:
            self._schedule_task(self._sync_network_state(), "network_sync")

    async def _sync_network_state(self):
        if not self.discovery:
            return

        changed = await self.discovery.reconfigure_if_needed()
        vpn_detected = DeviceDiscovery.detect_vpn_environment()
        multinet_detected = DeviceDiscovery.detect_multi_network_environment()
        hotspot_detected = self._detect_hotspot_environment()
        compatibility_mode = (
            self.settings.nonstandard_network_mode
            or hotspot_detected
            or vpn_detected
            or multinet_detected
        )
        mode_changed = await self.discovery.set_compatibility_mode(compatibility_mode)
        self._vpn_detected = vpn_detected
        self._multinet_detected = multinet_detected
        self._hotspot_detected = hotspot_detected
        self._effective_nonstandard_mode = compatibility_mode

        if changed or mode_changed:
            QMetaObject.invokeMethod(self, "_on_network_changed", Qt.ConnectionType.QueuedConnection)

        QMetaObject.invokeMethod(self, "_on_ip_refresh", Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _on_network_changed(self):
        self.status_label.setText(t("● Сеть изменилась, адрес обновлён"))
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
        try:
            secure_mode = self.settings.secure_mode
            manual_nonstandard_mode = self.settings.nonstandard_network_mode
            self._hotspot_detected = self._detect_hotspot_environment()
            self._vpn_detected = DeviceDiscovery.detect_vpn_environment()
            self._multinet_detected = DeviceDiscovery.detect_multi_network_environment()
            compatibility_mode = (
                manual_nonstandard_mode
                or self._hotspot_detected
                or self._vpn_detected
                or self._multinet_detected
            )
            self._effective_nonstandard_mode = compatibility_mode
            relay_mode = self.settings.relay_mode
            relay_url = self.settings.relay_server_url
            auth_secret = self.settings.secure_shared_secret if secure_mode else ""
            verify_checksum = secure_mode
            requested_port = int(self.settings.port)

            self.server = TransferServer(
                requested_port,
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
            self.server.on_clipboard_update = self._on_clipboard_payload
            actual_port = await self.server.start()

            if actual_port != requested_port:
                self.settings.set("port", int(actual_port))
                self.device_list.default_port = int(actual_port)
                self._on_server_error(
                    t(
                        "Порт {requested_port} недоступен, автоматически выбран {actual_port}",
                        requested_port=requested_port,
                        actual_port=actual_port,
                    )
                )

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

            if self.clipboard_sync:
                self.clipboard_sync.configure(self.loop, auth_secret)
                self.clipboard_sync.refresh_from_settings()

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
                self.status_label.setText(t("● Активен (Relay включён, но URL не задан)"))
                self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
            elif self._hotspot_detected and not manual_nonstandard_mode:
                self.status_label.setText(t("● Активен (обнаружен хот-спот, включён совместимый режим)"))
                self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
            elif self._vpn_detected and not manual_nonstandard_mode:
                self.status_label.setText(t("● Активен (обнаружен VPN, включён совместимый режим)"))
                self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
            elif compatibility_mode and relay_ready:
                self.status_label.setText(t("● Активен (нестандартные сети + Relay)"))
                self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
            elif compatibility_mode:
                self.status_label.setText(t("● Активен (режим нестандартных сетей)"))
                self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
            elif relay_ready:
                self.status_label.setText(t("● Активен (Relay)"))
                self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")
            else:
                self.status_label.setText(t("● Активен"))
                self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

            if not self._network_timer.isActive():
                self._network_timer.start()

            self._services_ready = True

            # Auto-update check (non-blocking, respects 12h cache unless forced on startup?)
            # User requested: "check updates at program launch, cache 12h only for tray restore"
            # So we force check here.
            self._init_updater()
            self._schedule_task(self._check_for_update(force=True), "startup_update_check")
        except Exception:
            self._services_ready = False
            await self.stop_services()
            raise
        finally:
            self._services_starting = False

    async def stop_services(self):
        self._services_ready = False
        self._services_starting = False
        if self._network_timer.isActive():
            self._network_timer.stop()

        if self.mobile_dialog:
            try:
                self.mobile_dialog.close()
            except Exception:
                pass
            self.mobile_dialog = None

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

        if self.clipboard_sync:
            await self.clipboard_sync.stop()

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
        self.status_label.setText(t("● Фон: экономия ресурсов"))
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
        self.status_label.setText(t("● Активен"))
        self.status_label.setStyleSheet("color: #22c55e; font-size: 12px;")

    def _on_server_error(self, error: str):
        if "Relay" in (error or ""):
            self.status_label.setText(t("● Relay временно недоступен"))
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
        else:
            self.status_label.setText(t("● Ошибка"))
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

    def _collect_transfer_files(self, paths: List[str]) -> tuple[list[tuple[str, str]], int]:
        valid_files: list[tuple[str, str]] = []
        folder_count = 0
        seen: set[str] = set()

        for item in paths:
            if not os.path.exists(item):
                continue
            if os.path.isfile(item):
                key = os.path.abspath(item)
                if key not in seen:
                    seen.add(key)
                    valid_files.append((item, os.path.basename(item)))
                continue

            if not os.path.isdir(item):
                continue

            folder_count += 1
            base_dir = os.path.dirname(item)
            for root, _dirs, filenames in os.walk(item):
                for filename in filenames:
                    filepath = os.path.join(root, filename)
                    if not os.path.isfile(filepath):
                        continue
                    key = os.path.abspath(filepath)
                    if key in seen:
                        continue
                    seen.add(key)
                    rel_path = os.path.relpath(filepath, start=base_dir).replace("\\", "/")
                    valid_files.append((filepath, rel_path))

        return valid_files, folder_count

    @pyqtSlot(str, str, int)
    def _on_device_selected(self, name: str, ip: str, port: int):
        self.selected_device = (name, ip, port)
        if str(ip).startswith("relay:"):
            self.status_label.setText(t("● Выбрано Relay: {name}", name=name))
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
                self.status_label.setText(t("● Выбрано: {name}", name=name))
            else:
                self.status_label.setText(t("● Выбрано: {name} (может быть недоступно)", name=name))
                self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")

    @pyqtSlot(list)
    def _on_files_dropped(self, files: List[str]):
        if self._low_power_mode and self.loop:
            self._schedule_task(self.exit_low_power_mode(), "drop_exit_low_power")
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
                QMessageBox.information(self, "V-Link", t("Сначала выберите устройство из списка"))
                return

        valid_files, folder_count = self._collect_transfer_files(files)

        if not valid_files:
            QMessageBox.warning(self, "V-Link", t("Файлы не найдены"))
            return

        name, ip, port = self.selected_device

        if folder_count > 0:
            dialog = TransferSummaryDialog(name, valid_files, folder_count, parent=self)
            if dialog.exec() != dialog.DialogCode.Accepted:
                return

        async def send_with_ping():
            relay_peer_id = self._relay_peer_from_selection()
            if relay_peer_id:
                if not self.relay or not self.relay.has_peer(relay_peer_id):
                    QMetaObject.invokeMethod(self, "_show_relay_unavailable", Qt.ConnectionType.QueuedConnection)
                    return
                try:
                    self.status_label.setText(t("● Передача через Relay..."))
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
                    self.status_label.setText(
                        t("● Проверка маршрута: {ip}:{port}", ip=candidate_ip, port=candidate_port)
                    )
                    await self.client.send_files(valid_files, candidate_ip, candidate_port, target_name=name)
                    if (candidate_ip, candidate_port) != (ip, port):
                        self.selected_device = (name, candidate_ip, candidate_port)
                        self.status_label.setText(
                            t("● Обновлён адрес: {name} ({ip}:{port})", name=name, ip=candidate_ip, port=candidate_port)
                        )
                    self.settings.set('adaptive_profile', self.client.get_adaptive_profile())
                    return
                except Exception as e:
                    last_error = str(e)
                    continue

            if self.relay:
                relay_peer_id = self.relay.find_peer_by_name(name)
                if relay_peer_id and self.relay.has_peer(relay_peer_id):
                    try:
                        self.status_label.setText(t("● Прямой маршрут недоступен, пробуем Relay..."))
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
            self._schedule_task(send_with_ping(), "send_files")

    @pyqtSlot()
    def _show_device_unavailable(self):
        device_info = ""
        if self.selected_device:
            name, ip, port = self.selected_device
            device_info = "\n\n" + t("Устройство: {name}\nIP: {ip}:{port}", name=name, ip=ip, port=port)

        QMessageBox.warning(
            self,
            "V-Link",
            t(
                "Устройство обнаружено, но сейчас не отвечает.\n\n"
                "Возможные причины:\n"
                "• V-Link не запущен на другом устройстве\n"
                "• Брандмауэр или VPN блокируют соединение\n"
                "• Устройства в разных сетях\n"
                "• Сеть с изоляцией клиентов (guest/AP isolation) запрещает прямые подключения\n"
                "• Для вузов/хотспотов включите «Режим нестандартных сетей» в настройках\n"
                "• Если один ноутбук раздаёт Wi‑Fi, профиль хот-спота включается автоматически\n"
                "• Relay-режим нужен только как дополнительный вариант, если прямой режим недоступен{device_info}",
                device_info=device_info,
            ),
        )
        self.selected_device = None
        self.device_list.clear_selection()
        self.status_label.setText(t("● Готов к работе"))

    @pyqtSlot()
    def _show_relay_unavailable(self):
        QMessageBox.warning(
            self,
            "V-Link",
            t(
                "Relay-устройство недоступно.\n\n"
                "Проверьте:\n"
                "• Оба устройства онлайн и подключены к одному Relay-каналу\n"
                "• Relay URL одинаковый на обоих устройствах\n"
                "• Relay-сервер запущен"
            ),
        )
        self.selected_device = None
        self.device_list.clear_selection()
        self.status_label.setText(t("● Готов к работе"))

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
        units = (t("Б"), t("КБ"), t("МБ"), t("ГБ"))
        bytes_unit = t("Б")
        for unit in units:
            if abs(size_bytes) < 1024:
                return f"{size_bytes:.1f} {unit}" if unit != bytes_unit else f"{size_bytes} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} {t('ТБ')}"

    def _on_transfer_complete(self, transfer_id: str, filepath: str):
        self.transfer_list.complete_transfer(transfer_id, filepath)
        direction, size = self._transfer_directions.pop(transfer_id, ("in", 0))
        if self.tray_icon.isVisible():
            name = os.path.basename(os.path.normpath(filepath)) or filepath
            if direction == "in":
                title = t("Получен файл · Открыть")
            else:
                title = t("Файл отправлен · Показать")
            msg = f"{self._human_size(size)} · {name}" if size > 0 else name
            self._show_tray_message(
                msg,
                timeout_ms=6000,
                target_path=filepath,
                title=title,
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
            t(
                "Передача отклонена из-за несовпадения Безопасного режима.\n\n"
                "Проверьте, что на обоих устройствах этот режим либо включен, либо выключен, "
                "и что ключ безопасного режима одинаковый."
            ),
        )

    @pyqtSlot(str)
    def _show_transfer_failed(self, error: str):
        short = (error or "").strip()
        if len(short) > 300:
            short = short[:300] + "..."
        self.status_label.setText(t("● Ошибка передачи"))
        self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
        QMessageBox.warning(
            self,
            "V-Link",
            t("Передача не выполнена.\n\nПричина: {error}", error=short),
        )

    def _on_transfer_error(self, transfer_id: str, error: str):
        self.transfer_list.error_transfer(transfer_id, error)
        if self._is_security_mismatch_error(error):
            self.status_label.setText(t("● Проверьте, что Безопасный режим одинаков на обоих устройствах"))
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
            QMetaObject.invokeMethod(self, "_show_security_mismatch_warning", Qt.ConnectionType.QueuedConnection)

    def closeEvent(self, event: QCloseEvent):
        if self._quitting:
            event.accept()
            return

        if self.settings.close_to_tray:
            event.ignore()
            self.hide()
            if self.loop:
                self._schedule_task(self.enter_low_power_mode(), "tray_enter_low_power")
            self._show_tray_message(
                t("Программа свёрнута в трей"),
                timeout_ms=2000,
            )
            return

        event.ignore()
        self._quit_app()

    def _on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _show_window(self):
        try:
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()
            if self.loop:
                self._schedule_task(self.exit_low_power_mode(), "tray_exit_low_power")
                self._schedule_task(self._check_for_update(), "tray_update_check")
        except Exception as exc:
            record_exception("show_window", exc)

    @pyqtSlot()
    def _finalize_quit(self):
        QApplication.quit()



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
        self.update_btn.setToolTip(t("Доступно обновление V-Link {version}", version=version))
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
        body = self.updater.update_body or t("Нет описания.")

        msg = QMessageBox(self)
        msg.setWindowTitle(t("V-Link — Обновление"))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(t("Доступна новая версия: <b>{version}</b>", version=version))
        # Strip markdown formatting for plain-text QMessageBox display
        import re
        clean_body = body
        clean_body = re.sub(r'^#{1,6}\s*', '', clean_body, flags=re.MULTILINE)  # ## headers
        clean_body = re.sub(r'\*\*(.+?)\*\*', r'\1', clean_body)  # **bold**
        clean_body = re.sub(r'\*(.+?)\*', r'\1', clean_body)  # *italic*
        clean_body = re.sub(r'^\s*[-\*]\s+', '• ', clean_body, flags=re.MULTILINE)  # - list items
        clean_body = clean_body.strip()
        msg.setInformativeText(clean_body[:800])
        btn_update = msg.addButton(t("Обновить"), QMessageBox.ButtonRole.AcceptRole)
        btn_skip = msg.addButton(t("Пропустить"), QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(btn_update)
        msg.exec()

        if msg.clickedButton() == btn_update:
            if self.loop:
                self._schedule_task(self._do_update(), "download_update")
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
        self.status_label.setText(t("● Скачивание обновления: {percent}%", percent=percent))
        self.status_label.setStyleSheet("color: #6b5ce7; font-size: 12px;")

    @pyqtSlot()
    def _update_status_downloading(self):
        self.status_label.setText(t("● Скачивание обновления..."))
        self.status_label.setStyleSheet("color: #6b5ce7; font-size: 12px;")
        self.update_btn.setEnabled(False)

    @pyqtSlot()
    def _update_status_error(self):
        self.status_label.setText(t("● Ошибка загрузки обновления"))
        self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
        self.update_btn.setEnabled(True)

    @pyqtSlot(str)
    def _apply_update(self, downloaded_path: str):
        from pathlib import Path

        if not self.updater:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("V-Link")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(t("Обновление скачано. Перезапустить приложение?"))
        msg.setInformativeText(
            t(
                "V-Link закроется, обновится и запустится заново.\n"
                "Настройки будут сохранены."
            )
        )
        btn_yes = msg.addButton(t("Да"), QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton(t("Нет"), QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_yes)
        msg.exec()

        if msg.clickedButton() != btn_yes:
            self.status_label.setText(t("● Обновление отложено"))
            self.status_label.setStyleSheet("color: #f59e0b; font-size: 12px;")
            self.update_btn.setEnabled(True)
            return

        self.status_label.setText(t("● Применение обновления..."))
        self.status_label.setStyleSheet("color: #6b5ce7; font-size: 12px;")

        started = self.updater.apply_update(Path(downloaded_path))
        if not started:
            self.status_label.setText(t("● Не удалось запустить обновление"))
            self.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
            self.update_btn.setEnabled(True)
            return
        self._quit_for_update()

    def _quit_for_update(self):
        """
        Update path must release process quickly.
        We still try graceful shutdown, but enforce hard exit timeout.
        """
        if self._quitting:
            return
        self._quitting = True
        self.status_label.setText(t("● Перезапуск для обновления..."))
        self.status_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.tray_icon.hide()

        if self.loop:
            self._schedule_task(self.stop_services(), "update_stop_services")

        QTimer.singleShot(50, self.close)
        QTimer.singleShot(700, QApplication.quit)
        QTimer.singleShot(2500, lambda: os._exit(0))

    def _quit_app(self):
        if self._quitting:
            return
        self._quitting = True
        self.status_label.setText(t("● Завершение..."))
        self.status_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.tray_icon.hide()

        if self.loop:
            task = self._schedule_task(self.stop_services(), "quit_stop_services")
            if not task:
                self._finalize_quit()
                return
            task.add_done_callback(
                lambda _f: QMetaObject.invokeMethod(
                    self,
                    "_finalize_quit",
                    Qt.ConnectionType.QueuedConnection,
                )
            )
            return

        self._finalize_quit()
