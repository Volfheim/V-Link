"""
V-Link - Settings Dialog
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from ui.custom_widgets import CheckBoxWithMark
from version import __version__
from core.i18n import t


class SettingsDialog(QDialog):
    """Application settings dialog."""

    check_updates_clicked = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings

        self.setWindowTitle(t("Настройки"))
        self.setMinimumSize(720, 700)
        self.resize(780, 740)
        self.setSizeGripEnabled(False)
        self.setStyleSheet(
            """
            QDialog { background-color: #1a1a2e; }
            QLabel { color: #f8fafc; font-size: 13px; }
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #c084fc;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 16px;
                padding-top: 16px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }
            QLineEdit, QSpinBox {
                background-color: #0f0f23;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px 12px;
                color: #f8fafc;
                font-size: 13px;
                min-height: 20px;
            }
            QLineEdit:focus, QSpinBox:focus { border: 1px solid #6b5ce7; }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6b5ce7, stop:1 #a855f7);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c6ef0, stop:1 #b366ff);
            }
            QPushButton#cancelBtn {
                background: transparent;
                border: 1px solid #6b5ce7;
                color: #c084fc;
            }
            QPushButton#cancelBtn:hover { background: rgba(107, 92, 231, 0.2); }
            QPushButton#browseBtn { padding: 10px 16px; min-width: 80px; }
            QScrollArea { border: none; background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            """
        )

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(16)

        network_group = QGroupBox(t("Сеть"))
        network_layout = QVBoxLayout(network_group)
        network_layout.setSpacing(12)

        port_layout = QHBoxLayout()
        port_label = QLabel(t("Порт для передачи:"))
        port_label.setMinimumWidth(180)
        port_layout.addWidget(port_label)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(8765)
        self.port_spin.setMinimumWidth(120)
        port_layout.addWidget(self.port_spin)
        port_layout.addStretch()
        network_layout.addLayout(port_layout)

        self.nonstandard_network_check = CheckBoxWithMark(
            t("Режим нестандартных сетей (вуз/гостевой Wi-Fi/хотспот)")
        )
        self.nonstandard_network_check.setChecked(True)
        network_layout.addWidget(self.nonstandard_network_check)

        network_hint = QLabel(
            t(
                "Основной режим для вузовских/гостевых Wi‑Fi и хотспотов. "
                "Не требует relay-сервера и работает в пределах локальной сети."
            )
        )
        network_hint.setWordWrap(True)
        network_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        network_layout.addWidget(network_hint)

        self.relay_mode_check = CheckBoxWithMark(
            t("Relay-режим для сетей с изоляцией клиентов (через сервер)")
        )
        self.relay_mode_check.toggled.connect(self._toggle_relay_fields)
        network_layout.addWidget(self.relay_mode_check)

        relay_url_row = QHBoxLayout()
        relay_url_label = QLabel("Relay URL:")
        relay_url_label.setMinimumWidth(180)
        relay_url_row.addWidget(relay_url_label)
        self.relay_url_edit = QLineEdit()
        self.relay_url_edit.setPlaceholderText(
            t("http://192.168.1.10:8090 или https://relay.example.com")
        )
        self.relay_url_edit.setToolTip(t("Адрес запущенного relay-сервера"))
        relay_url_row.addWidget(self.relay_url_edit)
        network_layout.addLayout(relay_url_row)

        relay_channel_row = QHBoxLayout()
        relay_channel_label = QLabel(t("Канал (одинаковый на обоих ПК):"))
        relay_channel_label.setMinimumWidth(180)
        relay_channel_row.addWidget(relay_channel_label)
        self.relay_channel_edit = QLineEdit()
        self.relay_channel_edit.setPlaceholderText(t("например: home, pgtu, group-a"))
        self.relay_channel_edit.setToolTip(t("Одинаковое имя канала на обоих устройствах"))
        relay_channel_row.addWidget(self.relay_channel_edit)
        network_layout.addLayout(relay_channel_row)

        relay_hint = QLabel(
            t(
                "Требуется отдельный relay-сервер (локальный ПК/NAS/VPS). "
                "Используется, когда прямое подключение в сети недоступно. "
                "Обычно медленнее, чем прямой LAN-режим."
            )
        )
        relay_hint.setWordWrap(True)
        relay_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        network_layout.addWidget(relay_hint)

        storage_group = QGroupBox(t("Хранилище"))
        storage_layout = QVBoxLayout(storage_group)
        storage_layout.setSpacing(12)

        folder_label = QLabel(t("Папка для загрузок:"))
        storage_layout.addWidget(folder_label)

        download_layout = QHBoxLayout()
        self.download_edit = QLineEdit()
        self.download_edit.setPlaceholderText(t("Выберите папку..."))
        self.download_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        download_layout.addWidget(self.download_edit)

        browse_btn = QPushButton(t("Обзор..."))
        browse_btn.setObjectName("browseBtn")
        browse_btn.clicked.connect(self._browse_folder)
        download_layout.addWidget(browse_btn)
        storage_layout.addLayout(download_layout)
        content_layout.addWidget(storage_group)

        security_group = QGroupBox(t("Безопасность"))
        security_layout = QVBoxLayout(security_group)
        security_layout.setSpacing(8)

        self.secure_mode_check = CheckBoxWithMark(t("Безопасный режим передачи (медленнее, но надёжнее)"))
        self.secure_mode_check.toggled.connect(self._toggle_secure_fields)
        security_layout.addWidget(self.secure_mode_check)

        secure_key_row = QHBoxLayout()
        secure_key_label = QLabel(t("Ключ безопасного режима:"))
        secure_key_label.setMinimumWidth(180)
        secure_key_row.addWidget(secure_key_label)
        self.secure_key_edit = QLineEdit()
        self.secure_key_edit.setPlaceholderText(t("Одинаковый ключ на обоих устройствах"))
        self.secure_key_edit.setToolTip(t("Скопируйте этот ключ на второе устройство, если включаете безопасный режим"))
        secure_key_row.addWidget(self.secure_key_edit)
        security_layout.addLayout(secure_key_row)

        secure_hint = QLabel(
            t(
                "Включает шифрование потока, проверку целостности и общий ключ между устройствами. "
                "Для передачи ключ должен совпадать на обоих ПК."
            )
        )
        secure_hint.setWordWrap(True)
        secure_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        security_layout.addWidget(secure_hint)

        content_layout.addWidget(security_group)

        behavior_group = QGroupBox(t("Поведение"))
        behavior_layout = QVBoxLayout(behavior_group)
        behavior_layout.setSpacing(8)

        self.minimize_check = CheckBoxWithMark(t("Запускать свёрнутым в трей"))
        behavior_layout.addWidget(self.minimize_check)

        self.autostart_check = CheckBoxWithMark(t("Запускать вместе с Windows"))
        behavior_layout.addWidget(self.autostart_check)

        self.close_to_tray_check = CheckBoxWithMark(t("При закрытии сворачивать в трей"))
        behavior_layout.addWidget(self.close_to_tray_check)

        auto_mode = QLabel(t("Режим передачи: автоматически оптимизируется приложением"))
        auto_mode.setWordWrap(True)
        auto_mode.setStyleSheet("color: #64748b; font-size: 11px;")
        behavior_layout.addWidget(auto_mode)

        content_layout.addWidget(behavior_group)

        language_group = QGroupBox(t("Язык"))
        language_layout = QVBoxLayout(language_group)
        language_layout.setSpacing(8)

        self.language_combo = QComboBox()
        self.language_combo.addItem(t("Как в системе"), "system")
        self.language_combo.addItem(t("Русский"), "ru")
        self.language_combo.addItem(t("Английский"), "en")
        language_layout.addWidget(self.language_combo)

        language_hint = QLabel(t("Требуется перезапуск для применения языка."))
        language_hint.setWordWrap(True)
        language_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        language_layout.addWidget(language_hint)

        content_layout.addWidget(language_group)

        clipboard_group = QGroupBox(t("Буфер обмена"))
        clipboard_layout = QVBoxLayout(clipboard_group)
        clipboard_layout.setSpacing(8)

        self.clipboard_sync_check = CheckBoxWithMark(t("Синхронизация текста между устройствами"))
        self.clipboard_sync_check.setChecked(True)
        self.clipboard_sync_check.toggled.connect(self._toggle_clipboard_options)
        clipboard_layout.addWidget(self.clipboard_sync_check)

        self.clipboard_image_check = CheckBoxWithMark(t("Синхронизация изображений (может быть медленнее)"))
        self.clipboard_image_check.setChecked(False)
        clipboard_layout.addWidget(self.clipboard_image_check)

        clipboard_hint = QLabel(
            t(
                "Работает только между устройствами с запущенным V-Link в одной сети. "
                "Для изображений действует ограничение по размеру, чтобы не нагружать сеть."
            )
        )
        clipboard_hint.setWordWrap(True)
        clipboard_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        clipboard_layout.addWidget(clipboard_hint)

        content_layout.addWidget(clipboard_group)
        content_layout.addWidget(network_group)

        about_group = QGroupBox(t("О программе"))
        about_layout = QVBoxLayout(about_group)
        about_layout.setSpacing(12)

        version_label = QLabel(f"V-Link v{__version__}")
        version_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        about_layout.addWidget(version_label)

        author_label = QLabel(t("Создано Volfheim © 2026"))
        author_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        about_layout.addWidget(author_label)

        check_updates_btn = QPushButton(t("Проверить обновления"))
        check_updates_btn.setToolTip(t("Принудительно проверить наличие новой версии на GitHub"))
        check_updates_btn.clicked.connect(self.check_updates_clicked.emit)
        check_updates_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                border: 1px solid #475569;
                color: #e2e8f0;
            }
            QPushButton:hover {
                background-color: #475569;
                border: 1px solid #64748b;
            }
        """)
        about_layout.addWidget(check_updates_btn)

        content_layout.addWidget(about_group)

        content_layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_btn = QPushButton(t("Отмена"))
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        save_btn = QPushButton(t("Сохранить"))
        save_btn.clicked.connect(self._save_and_close)
        buttons.addWidget(save_btn)

        root_layout.addLayout(buttons)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            t("Выберите папку для загрузок"),
            self.download_edit.text(),
        )
        if folder:
            self.download_edit.setText(folder)

    def _load_settings(self):
        self.port_spin.setValue(self.settings.get('port', 8765))
        self.download_edit.setText(self.settings.get('download_dir', ''))
        self.secure_mode_check.setChecked(self.settings.get('secure_mode', False))
        self.secure_key_edit.setText(self.settings.get('secure_shared_secret', ''))
        self.nonstandard_network_check.setChecked(self.settings.get('nonstandard_network_mode', True))
        self.relay_mode_check.setChecked(self.settings.get('relay_mode', False))
        self.relay_url_edit.setText(self.settings.get('relay_server_url', ''))
        self.relay_channel_edit.setText(self.settings.get('relay_channel', 'default'))
        self.minimize_check.setChecked(self.settings.get('start_minimized', False))
        self.autostart_check.setChecked(self.settings.get('autostart', False))
        self.close_to_tray_check.setChecked(self.settings.get('close_to_tray', True))
        current_lang = str(self.settings.get('language', 'system') or 'system').lower()
        idx = self.language_combo.findData(current_lang)
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.clipboard_sync_check.setChecked(self.settings.get('clipboard_sync_enabled', True))
        self.clipboard_image_check.setChecked(self.settings.get('clipboard_sync_images', False))
        self._toggle_relay_fields(self.relay_mode_check.isChecked())
        self._toggle_secure_fields(self.secure_mode_check.isChecked())
        self._toggle_clipboard_options(self.clipboard_sync_check.isChecked())

    def _toggle_relay_fields(self, enabled: bool):
        self.relay_url_edit.setEnabled(enabled)
        self.relay_channel_edit.setEnabled(enabled)

    def _toggle_secure_fields(self, enabled: bool):
        self.secure_key_edit.setEnabled(enabled)

    def _toggle_clipboard_options(self, enabled: bool):
        self.clipboard_image_check.setEnabled(enabled)

    def _save_and_close(self):
        relay_url = self.relay_url_edit.text().strip()
        relay_channel = self.relay_channel_edit.text().strip() or "default"
        secure_secret = self.secure_key_edit.text().strip()
        if self.secure_mode_check.isChecked() and not secure_secret:
            secure_secret = self.settings.ensure_secure_shared_secret()
        if self.relay_mode_check.isChecked() and not relay_url:
            QMessageBox.warning(
                self,
                "V-Link",
                t("Для Relay-режима укажите Relay URL."),
            )
            return

        self.settings.set_many({
            'port': self.port_spin.value(),
            'download_dir': self.download_edit.text(),
            'secure_mode': self.secure_mode_check.isChecked(),
            'secure_shared_secret': secure_secret,
            'nonstandard_network_mode': self.nonstandard_network_check.isChecked(),
            'relay_mode': self.relay_mode_check.isChecked(),
            'relay_server_url': relay_url,
            'relay_channel': relay_channel,
            'start_minimized': self.minimize_check.isChecked(),
            'autostart': self.autostart_check.isChecked(),
            'close_to_tray': self.close_to_tray_check.isChecked(),
            'language': str(self.language_combo.currentData() or "system"),
            'clipboard_sync_enabled': self.clipboard_sync_check.isChecked(),
            'clipboard_sync_images': self.clipboard_image_check.isChecked(),
        })
        self.accept()
