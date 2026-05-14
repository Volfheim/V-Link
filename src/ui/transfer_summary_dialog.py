"""
V-Link - transfer summary dialog.
"""

import os
from typing import Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from core.i18n import t


class TransferSummaryDialog(QDialog):
    """Detailed confirmation for folder and multi-file transfers."""

    def __init__(
        self,
        target_name: str,
        files: Iterable[tuple[str, str]],
        folder_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.files = list(files)
        self.folder_count = int(folder_count or 0)
        self.total_size = sum(self._safe_size(path) for path, _rel in self.files)

        self.setWindowTitle(t("Подробности передачи"))
        self.setMinimumSize(560, 460)
        self.setStyleSheet(
            """
            QDialog { background-color: #1a1a2e; }
            QLabel { color: #f8fafc; font-size: 13px; }
            QListWidget {
                background-color: #0f0f23;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px;
                color: #e2e8f0;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6b5ce7, stop:1 #a855f7);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                font-weight: bold;
            }
            QPushButton#cancelBtn {
                background: transparent;
                border: 1px solid #6b5ce7;
                color: #c084fc;
            }
            """
        )

        self._setup_ui(target_name)

    def _setup_ui(self, target_name: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        title = QLabel(t("Отправка папки") if self.folder_count else t("Отправка файлов"))
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #f8fafc;")
        root.addWidget(title)

        summary = QLabel(
            t(
                "Получатель: {target}\nФайлов: {files}\nПапок: {folders}\nОбщий размер: {size}",
                target=target_name or t("выбранное устройство"),
                files=len(self.files),
                folders=self.folder_count,
                size=self._format_size(self.total_size),
            )
        )
        summary.setStyleSheet("color: #cbd5e1; line-height: 1.4;")
        root.addWidget(summary)

        hint = QLabel(t("Структура папок будет сохранена на принимающем устройстве без архивации."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(hint)

        self.file_list = QListWidget()
        preview_limit = 250
        for _path, rel_path in self.files[:preview_limit]:
            self.file_list.addItem(str(rel_path).replace("\\", "/"))
        if len(self.files) > preview_limit:
            self.file_list.addItem(t("...и ещё {count} файлов", count=len(self.files) - preview_limit))
        root.addWidget(self.file_list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton(t("Отмена"))
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        send_btn = QPushButton(t("Отправить"))
        send_btn.clicked.connect(self.accept)
        buttons.addWidget(send_btn)
        root.addLayout(buttons)

    @staticmethod
    def _safe_size(path: str) -> int:
        try:
            return int(os.path.getsize(path))
        except OSError:
            return 0

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(max(0, int(size or 0)))
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"
