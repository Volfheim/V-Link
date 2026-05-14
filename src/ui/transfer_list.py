"""
V-Link - Transfer List Widget
"""

import os
import subprocess
import time
from typing import Dict

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.i18n import t


class TransferItem(QFrame):
    cancel_requested = pyqtSignal(str)

    def __init__(self, transfer_id: str, filename: str, total_size: int, is_upload: bool = True, parent=None):
        super().__init__(parent)
        self.transfer_id = transfer_id
        self.filename = filename
        self.total_size = total_size
        self.is_upload = is_upload
        self.transferred = 0
        self.start_time = time.perf_counter()
        self.end_time = None
        self.filepath = None
        self.state = "in_progress"

        self.setStyleSheet(
            """
            QFrame {
                background-color: rgba(22, 33, 62, 0.8);
                border-radius: 8px;
                padding: 8px;
            }
            """
        )
        self._setup_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_time)
        self.timer.start(1000)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        top_row = QHBoxLayout()

        icon = QLabel("[UP]" if self.is_upload else "[DN]")
        icon.setStyleSheet(
            """
            font-size: 10px;
            font-weight: bold;
            color: #6b5ce7;
            background: rgba(107, 92, 231, 0.2);
            padding: 2px 4px;
            border-radius: 3px;
            """
        )
        top_row.addWidget(icon)

        name_label = QLabel(self._truncate_filename(self.filename, 25))
        name_label.setStyleSheet("font-weight: bold; color: #f8fafc; font-size: 12px;")
        name_label.setToolTip(self.filename)
        top_row.addWidget(name_label)

        top_row.addStretch()

        self.size_label = QLabel(self._format_progress_size(0, self.total_size))
        self.size_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        top_row.addWidget(self.size_label)

        layout.addLayout(top_row)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        progress_row.addWidget(self.progress_bar)
        layout.addLayout(progress_row)

        bottom_row = QHBoxLayout()

        self.time_label = QLabel(t("0 сек"))
        self.time_label.setStyleSheet("color: #64748b; font-size: 10px;")
        bottom_row.addWidget(self.time_label)
        bottom_row.addStretch()

        self.status_label = QLabel("0 MB/s")
        self.status_label.setStyleSheet("color: #c084fc; font-size: 11px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        bottom_row.addWidget(self.status_label)

        self.open_btn = QPushButton()
        self.open_btn.setToolTip(t("Показать в проводнике"))
        self.open_btn.setFixedSize(24, 24)
        style = self.open_btn.style()
        self.open_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_DirOpenIcon))
        self.open_btn.setStyleSheet(
            """
            QPushButton { background: rgba(107, 92, 231, 0.3); border: none; border-radius: 4px; }
            QPushButton:hover { background: rgba(107, 92, 231, 0.6); }
            """
        )
        self.open_btn.clicked.connect(self._show_in_explorer)
        self.open_btn.hide()
        bottom_row.addWidget(self.open_btn)

        layout.addLayout(bottom_row)

    def _update_time(self):
        elapsed = (self.end_time - self.start_time) if self.end_time else (time.perf_counter() - self.start_time)
        self.time_label.setText(self._format_time(elapsed))

    def update_progress(self, transferred: int, speed: float):
        self.transferred = transferred
        percent = int((transferred / self.total_size) * 100) if self.total_size > 0 else 0
        self.progress_bar.setValue(percent)
        self.size_label.setText(self._format_progress_size(transferred, self.total_size))
        self.status_label.setText(self._format_speed(speed))

    def mark_complete(self):
        self.timer.stop()
        self.end_time = time.perf_counter()
        self.state = "completed"
        elapsed = self.end_time - self.start_time

        self.progress_bar.setValue(100)
        final_size = max(self.total_size, self.transferred)
        self.size_label.setText(self._format_progress_size(final_size, final_size))
        self.time_label.setText(self._format_time(elapsed))
        self.status_label.setText("OK")
        self.status_label.setStyleSheet("color: #22c55e; font-size: 11px; font-weight: bold;")

        if not self.is_upload and self.filepath and os.path.exists(self.filepath):
            self.open_btn.show()

    def set_filepath(self, filepath: str):
        self.filepath = filepath

    def _show_in_explorer(self):
        if self.filepath and os.path.exists(self.filepath):
            if os.path.isdir(self.filepath):
                subprocess.run(['explorer', self.filepath])
            else:
                subprocess.run(['explorer', '/select,', self.filepath])

    def mark_error(self, error: str):
        self.timer.stop()
        self.end_time = time.perf_counter()
        self.state = "error"
        self.status_label.setText(t("Ошибка"))
        self.status_label.setStyleSheet("color: #ef4444; font-size: 11px; font-weight: bold;")
        self.setToolTip(error)

    def set_low_power_mode(self, enabled: bool):
        if self.end_time:
            return
        if enabled:
            self.timer.stop()
        elif not self.timer.isActive():
            self.timer.start(1000)

    @staticmethod
    def _truncate_filename(filename: str, max_len: int) -> str:
        name = str(filename or "").replace("\\", "/")
        if "/" not in name:
            name = os.path.basename(name)
        if len(name) <= max_len:
            return name
        return name[: max_len - 3] + "..."

    @staticmethod
    def _format_size_only(size: int) -> str:
        size = max(0, int(size or 0))
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @classmethod
    def _format_progress_size(cls, transferred: int, total: int) -> str:
        transferred = max(0, int(transferred or 0))
        total = max(0, int(total or 0))
        if total > 0:
            return f"{cls._format_size_only(transferred)} / {cls._format_size_only(total)}"
        return cls._format_size_only(transferred)

    @staticmethod
    def _format_speed(speed: float) -> str:
        if speed < 1024:
            return f"{speed:.0f} B/s"
        if speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        return f"{speed / 1024 / 1024:.1f} MB/s"

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 1:
            return t("<1 сек")
        if seconds < 60:
            return t("{seconds} сек", seconds=int(round(seconds)))
        if seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return t("{mins} мин {secs} сек", mins=mins, secs=secs)
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return t("{hours} ч {mins} мин", hours=hours, mins=mins)


class TransferList(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.transfers: Dict[str, TransferItem] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(t("Передачи"))
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        header.addWidget(title)

        self.count_label = QLabel(t("Нет активных"))
        self.count_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        header.addStretch()
        header.addWidget(self.count_label)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()

        scroll.setWidget(self.list_container)
        layout.addWidget(scroll)

    def add_transfer(self, transfer_id: str, filename: str, total_size: int, is_upload: bool = True) -> TransferItem:
        item = TransferItem(transfer_id, filename, total_size, is_upload)
        self.transfers[transfer_id] = item
        self.list_layout.insertWidget(self.list_layout.count() - 1, item)
        self._update_count()
        return item

    def update_transfer(self, transfer_id: str, transferred: int, speed: float):
        if transfer_id in self.transfers:
            self.transfers[transfer_id].update_progress(transferred, speed)

    def complete_transfer(self, transfer_id: str, filepath: str = None):
        if transfer_id in self.transfers:
            if filepath:
                self.transfers[transfer_id].set_filepath(filepath)
            self.transfers[transfer_id].mark_complete()
            self._update_count()

    def error_transfer(self, transfer_id: str, error: str):
        if transfer_id in self.transfers:
            self.transfers[transfer_id].mark_error(error)
            self._update_count()

    def remove_transfer(self, transfer_id: str):
        if transfer_id in self.transfers:
            item = self.transfers.pop(transfer_id)
            item.deleteLater()
            self._update_count()

    def _update_count(self):
        active = sum(1 for t in self.transfers.values() if t.state == "in_progress")
        if active == 0:
            self.count_label.setText(t("Нет активных"))
        else:
            self.count_label.setText(t("{count} активных", count=active))

    def set_low_power_mode(self, enabled: bool):
        for transfer in self.transfers.values():
            transfer.set_low_power_mode(enabled)
