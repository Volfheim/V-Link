"""
V-Link - Drop Zone Widget
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.i18n import t


class DropZone(QFrame):
    """Drag-and-drop zone for files and folders."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(190)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        self.icon_label = QLabel("[ + ]")
        self.icon_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #6b5ce7;")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        self.main_label = QLabel(t("Перетащите файлы или папки сюда"))
        self.main_label.setStyleSheet(
            """
            font-size: 16px;
            font-weight: bold;
            color: #f8fafc;
            """
        )
        self.main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.main_label)

        self.hint_label = QLabel(t("или выберите вручную"))
        self.hint_label.setStyleSheet(
            """
            font-size: 13px;
            color: #94a3b8;
            """
        )
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)

        files_btn = QPushButton(t("Файлы"))
        files_btn.setToolTip(t("Выбрать файлы для передачи"))
        files_btn.clicked.connect(self._choose_files)
        buttons.addWidget(files_btn)

        folder_btn = QPushButton(t("Папка"))
        folder_btn.setToolTip(t("Выбрать папку для передачи без архивации"))
        folder_btn.clicked.connect(self._choose_folder)
        buttons.addWidget(folder_btn)

        layout.addLayout(buttons)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("dropZoneActive")
            self.style().unpolish(self)
            self.style().polish(self)
            self.icon_label.setText("[ >>> ]")
            self.main_label.setText(t("Отпустите для добавления"))

    def dragLeaveEvent(self, event):
        self._reset_state()

    def dropEvent(self, event: QDropEvent):
        self._reset_state()

        files = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                files.append(path)

        if files:
            self.files_dropped.emit(files)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._choose_files()

    def _reset_state(self):
        self.setObjectName("dropZone")
        self.style().unpolish(self)
        self.style().polish(self)
        self.icon_label.setText("[ + ]")
        self.main_label.setText(t("Перетащите файлы или папки сюда"))

    def _choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            t("Выберите файлы для передачи"),
            "",
            t("Все файлы (*.*)"),
        )
        if files:
            self.files_dropped.emit(files)

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            t("Выберите папку для передачи"),
            "",
        )
        if folder:
            self.files_dropped.emit([folder])
