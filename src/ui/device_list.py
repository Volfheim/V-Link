"""
V-Link - Device List Widget
"""

import ipaddress

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.i18n import i18n, t


def plural_devices(count: int) -> str:
    if i18n.language == "en":
        unit = t("device") if count == 1 else t("devices")
        return f"{count} {unit}"
    if count % 100 in (11, 12, 13, 14):
        return f"{count} {t('устройств')}"
    if count % 10 == 1:
        return f"{count} {t('устройство')}"
    if count % 10 in (2, 3, 4):
        return f"{count} {t('устройства')}"
    return f"{count} {t('устройств')}"


class ManualConnectDialog(QDialog):
    def __init__(self, default_port: int = 8765, parent=None):
        super().__init__(parent)
        self.default_port = default_port
        self.setWindowTitle(t("Подключение по IP"))
        self.setMinimumWidth(380)
        self.setStyleSheet(
            """
            QDialog { background-color: #1a1a2e; }
            QLabel { color: #f8fafc; font-size: 13px; }
            QLineEdit {
                background-color: #0f0f23;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px 12px;
                color: #f8fafc;
                font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #6b5ce7; }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6b5ce7, stop:1 #a855f7);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-weight: bold;
            }
            QPushButton#cancelBtn {
                background: transparent;
                border: 1px solid #6b5ce7;
                color: #c084fc;
            }
        """
        )

        self.ip_address = ""
        self.port = default_port
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        hint = QLabel(t("Введите IP-адрес или IP:порт устройства:"))
        layout.addWidget(hint)

        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText(f"192.168.1.100:{self.default_port}")
        layout.addWidget(self.ip_edit)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_btn = QPushButton(t("Отмена"))
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        connect_btn = QPushButton(t("Подключить"))
        connect_btn.clicked.connect(self._connect)
        buttons.addWidget(connect_btn)

        layout.addLayout(buttons)

    def _connect(self):
        raw = self.ip_edit.text().strip()
        if not raw:
            return

        if ":" in raw:
            ip, port_text = raw.rsplit(":", 1)
            ip = ip.strip()
            try:
                port = int(port_text.strip())
            except ValueError:
                return
            if not (1 <= port <= 65535):
                return
            self.ip_address = ip
            self.port = port
        else:
            self.ip_address = raw
            self.port = self.default_port

        try:
            ipaddress.ip_address(self.ip_address)
        except ValueError:
            self.ip_edit.setToolTip(t("Некорректный IP-адрес"))
            self.ip_edit.setStyleSheet(
                """
                QLineEdit {
                    background-color: #0f0f23;
                    border: 1px solid #ef4444;
                    border-radius: 6px;
                    padding: 10px 12px;
                    color: #f8fafc;
                    font-size: 14px;
                }
                """
            )
            return

        self.ip_edit.setToolTip("")
        self.ip_edit.setStyleSheet("")

        if self.ip_address:
            self.accept()


class DeviceCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, name: str, ip: str, port: int = 8765, is_online: bool = True, is_manual: bool = False, parent=None):
        super().__init__(parent)
        self.device_name = name
        self.device_ip = ip
        self.device_port = port
        self.is_online = is_online
        self.is_manual = is_manual
        self._selected = False

        self.setFixedHeight(52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self._setup_ui()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(
                """
                DeviceCard {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(107, 92, 231, 0.4), stop:1 rgba(168, 85, 247, 0.3));
                    border: 1px solid #6b5ce7;
                    border-radius: 8px;
                }
                """
            )
        else:
            self.setStyleSheet(
                """
                DeviceCard {
                    background: rgba(15, 15, 35, 0.6);
                    border: 1px solid #334155;
                    border-radius: 8px;
                }
                DeviceCard:hover {
                    background: rgba(107, 92, 231, 0.15);
                    border: 1px solid #6b5ce7;
                }
                """
            )

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        if self._is_relay():
            icon_text = "RLY"
            tooltip = t("Relay-устройство")
        else:
            icon_text = "IP" if self.is_manual else "PC"
            tooltip = t("Ручное подключение") if self.is_manual else t("Устройство в сети")

        icon = QLabel(icon_text)
        icon.setToolTip(tooltip)
        icon.setFixedSize(32, 24)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            """
            QLabel {
                font-size: 10px;
                font-weight: bold;
                color: #6b5ce7;
                background: rgba(107, 92, 231, 0.3);
                border-radius: 4px;
            }
            """
        )
        layout.addWidget(icon)

        self.name_label = QLabel(self.device_name)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #f8fafc; background: transparent;")
        layout.addWidget(self.name_label)

        self.ip_label = QLabel(self._format_endpoint())
        self.ip_label.setStyleSheet("font-size: 11px; color: #64748b; background: transparent; padding-top: 2px;")
        layout.addWidget(self.ip_label)

        layout.addStretch()

        self.status = QLabel("OK" if self.is_online else "--")
        color = '#22c55e' if self.is_online else '#64748b'
        self.status.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; background: transparent;")
        layout.addWidget(self.status)

    def update_device(self, name: str, ip: str, port: int, is_online: bool):
        self.device_name = name
        self.device_ip = ip
        self.device_port = port
        self.is_online = is_online
        self.name_label.setText(name)
        self.ip_label.setText(self._format_endpoint())
        self.status.setText("OK" if is_online else "--")
        color = '#22c55e' if is_online else '#64748b'
        self.status.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; background: transparent;")

    def _is_relay(self) -> bool:
        return isinstance(self.device_ip, str) and self.device_ip.startswith("relay:")

    def _format_endpoint(self) -> str:
        if self._is_relay():
            return "relay-cloud"
        return f"{self.device_ip}:{self.device_port}"

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DeviceList(QFrame):
    device_selected = pyqtSignal(str, str, int)
    refresh_clicked = pyqtSignal()

    def __init__(self, default_port: int = 8765, parent=None):
        super().__init__(parent)
        self.default_port = default_port
        self.setObjectName("panel")
        self.devices: list[DeviceCard] = []
        self._selected_card: DeviceCard = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(t("Устройства в сети"))
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        header.addWidget(title)
        header.addStretch()

        self.count_label = QLabel(plural_devices(0))
        self.count_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        add_btn = QPushButton("+ IP")
        add_btn.setToolTip(t("Добавить устройство по IP-адресу"))
        add_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: 1px solid #6b5ce7;
                color: #c084fc;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(107, 92, 231, 0.2); }
            """
        )
        add_btn.clicked.connect(self._show_manual_connect)
        header.addWidget(add_btn)

        self.refresh_btn = QPushButton()
        self.refresh_btn.setToolTip(t("Обновить список устройств"))
        self.refresh_btn.setFixedSize(28, 28)
        self.refresh_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_BrowserReload))
        self.refresh_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: 1px solid #6b5ce7;
                border-radius: 4px;
            }
            QPushButton:hover { background: rgba(107, 92, 231, 0.2); }
            """
        )
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        header.addWidget(self.refresh_btn)
        
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            """
            QScrollArea { border: none; background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            """
        )

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()

        scroll.setWidget(self.cards_container)
        layout.addWidget(scroll)

    def _show_manual_connect(self):
        dialog = ManualConnectDialog(default_port=self.default_port, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            ip = dialog.ip_address
            port = dialog.port
            name = t("Manual ({ip})", ip=ip)
            self.add_device(name, ip, port, True, is_manual=True)
            self.device_selected.emit(name, ip, port)

    @pyqtSlot(str, str, int, bool)
    def add_device(self, name: str, ip: str, port: int = 8765, is_online: bool = True, is_manual: bool = False):
        for card in self.devices:
            if card.device_ip == ip and card.device_port == port:
                card.update_device(name, ip, port, is_online)
                if card is self._selected_card:
                    self.device_selected.emit(card.device_name, card.device_ip, card.device_port)
                return
            if card.device_name == name and not card.is_manual:
                card.update_device(name, ip, port, is_online)
                if card is self._selected_card:
                    self.device_selected.emit(card.device_name, card.device_ip, card.device_port)
                return

        card = DeviceCard(name, ip, port, is_online, is_manual)
        card.clicked.connect(lambda: self._on_card_clicked(card))
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.devices.append(card)
        self._update_count()

    @pyqtSlot(str)
    def remove_device(self, ip: str):
        for card in list(self.devices):
            if card.device_ip == ip:
                if card is self._selected_card:
                    self._selected_card = None
                self.devices.remove(card)
                card.deleteLater()
        self._update_count()

    def clear_devices(self):
        for card in self.devices:
            card.deleteLater()
        self.devices.clear()
        self._selected_card = None
        self._update_count()

    def clear_selection(self):
        if self._selected_card:
            self._selected_card.set_selected(False)
            self._selected_card = None

    def _update_count(self):
        self.count_label.setText(plural_devices(len(self.devices)))

    def _on_card_clicked(self, card: DeviceCard):
        if self._selected_card:
            self._selected_card.set_selected(False)

        card.set_selected(True)
        self._selected_card = card
        self.device_selected.emit(card.device_name, card.device_ip, card.device_port)

    def get_selected_device(self):
        if not self._selected_card:
            return None
        return (
            self._selected_card.device_name,
            self._selected_card.device_ip,
            self._selected_card.device_port,
        )
