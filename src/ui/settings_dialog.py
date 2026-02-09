"""
V-Link - Settings Dialog
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
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


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings

        self.setWindowTitle("Настройки")
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

        network_group = QGroupBox("Сеть")
        network_layout = QVBoxLayout(network_group)
        network_layout.setSpacing(12)

        port_layout = QHBoxLayout()
        port_label = QLabel("Порт для передачи:")
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
            "Режим нестандартных сетей (вуз/гостевой Wi-Fi/хотспот)"
        )
        network_layout.addWidget(self.nonstandard_network_check)

        network_hint = QLabel(
            "Использует совместимый режим обнаружения и передачи для сетей, "
            "где multicast/mDNS может быть ограничен."
        )
        network_hint.setWordWrap(True)
        network_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        network_layout.addWidget(network_hint)

        self.relay_mode_check = CheckBoxWithMark(
            "Relay-режим для сетей с изоляцией клиентов (через сервер)"
        )
        self.relay_mode_check.toggled.connect(self._toggle_relay_fields)
        network_layout.addWidget(self.relay_mode_check)

        relay_url_row = QHBoxLayout()
        relay_url_label = QLabel("Relay URL:")
        relay_url_label.setMinimumWidth(180)
        relay_url_row.addWidget(relay_url_label)
        self.relay_url_edit = QLineEdit()
        self.relay_url_edit.setPlaceholderText("http://your-relay-host:8090")
        relay_url_row.addWidget(self.relay_url_edit)
        network_layout.addLayout(relay_url_row)

        relay_channel_row = QHBoxLayout()
        relay_channel_label = QLabel("Канал (одинаковый на обоих ПК):")
        relay_channel_label.setMinimumWidth(180)
        relay_channel_row.addWidget(relay_channel_label)
        self.relay_channel_edit = QLineEdit()
        self.relay_channel_edit.setPlaceholderText("default")
        relay_channel_row.addWidget(self.relay_channel_edit)
        network_layout.addLayout(relay_channel_row)

        relay_hint = QLabel(
            "Используется только если прямое подключение в сети недоступно. "
            "Может быть медленнее обычного LAN-режима."
        )
        relay_hint.setWordWrap(True)
        relay_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        network_layout.addWidget(relay_hint)

        content_layout.addWidget(network_group)

        storage_group = QGroupBox("Хранилище")
        storage_layout = QVBoxLayout(storage_group)
        storage_layout.setSpacing(12)

        folder_label = QLabel("Папка для загрузок:")
        storage_layout.addWidget(folder_label)

        download_layout = QHBoxLayout()
        self.download_edit = QLineEdit()
        self.download_edit.setPlaceholderText("Выберите папку...")
        self.download_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        download_layout.addWidget(self.download_edit)

        browse_btn = QPushButton("Обзор...")
        browse_btn.setObjectName("browseBtn")
        browse_btn.clicked.connect(self._browse_folder)
        download_layout.addWidget(browse_btn)
        storage_layout.addLayout(download_layout)
        content_layout.addWidget(storage_group)

        security_group = QGroupBox("Безопасность")
        security_layout = QVBoxLayout(security_group)
        security_layout.setSpacing(8)

        self.secure_mode_check = CheckBoxWithMark("Безопасный режим передачи (медленнее, но надёжнее)")
        security_layout.addWidget(self.secure_mode_check)

        secure_hint = QLabel(
            "Включает проверку целостности и подтверждение между устройствами. "
            "Может немного снижать скорость, особенно на больших файлах."
        )
        secure_hint.setWordWrap(True)
        secure_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        security_layout.addWidget(secure_hint)

        content_layout.addWidget(security_group)

        behavior_group = QGroupBox("Поведение")
        behavior_layout = QVBoxLayout(behavior_group)
        behavior_layout.setSpacing(8)

        self.minimize_check = CheckBoxWithMark("Запускать свёрнутым в трей")
        behavior_layout.addWidget(self.minimize_check)

        self.autostart_check = CheckBoxWithMark("Запускать вместе с Windows")
        behavior_layout.addWidget(self.autostart_check)

        self.close_to_tray_check = CheckBoxWithMark("При закрытии сворачивать в трей")
        behavior_layout.addWidget(self.close_to_tray_check)

        auto_mode = QLabel("Режим передачи: автоматически оптимизируется приложением")
        auto_mode.setWordWrap(True)
        auto_mode.setStyleSheet("color: #64748b; font-size: 11px;")
        behavior_layout.addWidget(auto_mode)

        content_layout.addWidget(behavior_group)
        content_layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        footer = QLabel("Powered by Volfheim")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color: #64748b; font-size: 11px;")
        root_layout.addWidget(footer)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self._save_and_close)
        buttons.addWidget(save_btn)

        root_layout.addLayout(buttons)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для загрузок",
            self.download_edit.text(),
        )
        if folder:
            self.download_edit.setText(folder)

    def _load_settings(self):
        self.port_spin.setValue(self.settings.get('port', 8765))
        self.download_edit.setText(self.settings.get('download_dir', ''))
        self.secure_mode_check.setChecked(self.settings.get('secure_mode', False))
        self.nonstandard_network_check.setChecked(self.settings.get('nonstandard_network_mode', False))
        self.relay_mode_check.setChecked(self.settings.get('relay_mode', False))
        self.relay_url_edit.setText(self.settings.get('relay_server_url', ''))
        self.relay_channel_edit.setText(self.settings.get('relay_channel', 'default'))
        self.minimize_check.setChecked(self.settings.get('start_minimized', False))
        self.autostart_check.setChecked(self.settings.get('autostart', False))
        self.close_to_tray_check.setChecked(self.settings.get('close_to_tray', True))
        self._toggle_relay_fields(self.relay_mode_check.isChecked())

    def _toggle_relay_fields(self, enabled: bool):
        self.relay_url_edit.setEnabled(enabled)
        self.relay_channel_edit.setEnabled(enabled)

    def _save_and_close(self):
        relay_url = self.relay_url_edit.text().strip()
        relay_channel = self.relay_channel_edit.text().strip() or "default"
        if self.relay_mode_check.isChecked() and not relay_url:
            QMessageBox.warning(
                self,
                "V-Link",
                "Для Relay-режима укажите Relay URL.",
            )
            return

        self.settings.set_many({
            'port': self.port_spin.value(),
            'download_dir': self.download_edit.text(),
            'secure_mode': self.secure_mode_check.isChecked(),
            'nonstandard_network_mode': self.nonstandard_network_check.isChecked(),
            'relay_mode': self.relay_mode_check.isChecked(),
            'relay_server_url': relay_url,
            'relay_channel': relay_channel,
            'start_minimized': self.minimize_check.isChecked(),
            'autostart': self.autostart_check.isChecked(),
            'close_to_tray': self.close_to_tray_check.isChecked(),
        })
        self.accept()
