"""
V-Link - Mobile connect dialog.
Shows URL and QR code for web-based mobile file transfer.
"""

from io import BytesIO

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

_QR_IMPORT_ERROR = ""
try:
    import qrcode
except Exception as e:
    qrcode = None
    _QR_IMPORT_ERROR = str(e)


class MobileConnectDialog(QDialog):
    """Dialog with QR and URL for mobile web access."""

    def __init__(self, url: str, token: str, parent=None):
        super().__init__(parent)
        self._url = (url or "").strip()
        self._token = (token or "").strip()

        self.setWindowTitle("Подключение телефона")
        self.setMinimumSize(460, 520)
        self.resize(520, 560)
        self.setModal(False)
        self.setStyleSheet(
            """
            QDialog { background-color: #1a1a2e; color: #f8fafc; }
            QLabel { color: #f8fafc; font-size: 13px; }
            QLineEdit {
                background-color: #0f0f23;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px 12px;
                color: #f8fafc;
                font-size: 12px;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6b5ce7, stop:1 #a855f7);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c6ef0, stop:1 #b366ff);
            }
            QPushButton#secondary {
                background: transparent;
                border: 1px solid #6b5ce7;
                color: #c084fc;
            }
            QPushButton#secondary:hover { background: rgba(107, 92, 231, 0.2); }
            """
        )

        self._build_ui()
        self._render_qr()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Откройте на телефоне")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(title)

        subtitle = QLabel(
            "1. Подключите телефон к той же Wi-Fi сети.\n"
            "2. Отсканируйте QR-код или откройте ссылку вручную.\n"
            "3. Передавайте файлы через браузер."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #cbd5e1;")
        root.addWidget(subtitle)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(320)
        self.qr_label.setStyleSheet(
            "background:#0f0f23; border:1px solid #334155; border-radius:10px; padding:8px;"
        )
        root.addWidget(self.qr_label)

        self.url_edit = QLineEdit(self._url)
        self.url_edit.setReadOnly(True)
        self.url_edit.setCursorPosition(0)
        root.addWidget(self.url_edit)

        token_label = QLabel(f"Токен сессии: {self._token}")
        token_label.setStyleSheet("color:#94a3b8; font-size:12px;")
        root.addWidget(token_label)

        hint = QLabel("Ссылка работает, пока это окно открыто.")
        hint.setStyleSheet("color:#94a3b8; font-size:12px;")
        root.addWidget(hint)

        actions = QHBoxLayout()
        copy_btn = QPushButton("Копировать ссылку")
        copy_btn.clicked.connect(self._copy_url)
        actions.addWidget(copy_btn)

        close_btn = QPushButton("Закрыть")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.close)
        actions.addWidget(close_btn)
        root.addLayout(actions)

    def _copy_url(self):
        from PyQt6.QtGui import QGuiApplication

        cb = QGuiApplication.clipboard()
        cb.setText(self._url)
        QMessageBox.information(self, "V-Link", "Ссылка скопирована в буфер обмена.")

    def _render_qr(self):
        if not self._url:
            self.qr_label.setText("URL не задан")
            return
        if qrcode is None:
            details = f" ({_QR_IMPORT_ERROR})" if _QR_IMPORT_ERROR else ""
            self.qr_label.setText(
                f"QR-код недоступен: не загружен модуль qrcode{details}"
            )
            return

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(self._url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buff = BytesIO()
        img.save(buff, format="PNG")
        raw = buff.getvalue()

        pix = QPixmap()
        pix.loadFromData(raw, "PNG")
        if pix.isNull():
            self.qr_label.setText("Не удалось построить QR-код.")
            return

        scaled = pix.scaled(
            320,
            320,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.qr_label.setPixmap(scaled)
