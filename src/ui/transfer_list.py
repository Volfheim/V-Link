"""
V-Link - compact transfer activity list.
"""

import os
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.explorer import reveal_in_explorer
from core.i18n import t


class TransferItem(QFrame):
    cancel_requested = pyqtSignal(str)

    def __init__(self, transfer_id: str, filename: str, total_size: int, is_upload: bool = True, parent=None):
        super().__init__(parent)
        self.transfer_id = transfer_id
        self.filename = str(filename or "")
        self.total_size = max(0, int(total_size or 0))
        self.is_upload = is_upload
        self.transferred = 0
        self.start_time = time.perf_counter()
        self.end_time = None
        self.filepath = None
        self.state = "in_progress"

        self.setObjectName("transferItem")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(88)
        self.setStyleSheet(
            """
            QFrame#transferItem {
                background-color: #101a2e;
                border: 1px solid #2b3b58;
                border-radius: 7px;
            }
            QLabel#directionBadge {
                background-color: #25345b;
                color: #9ea8ff;
                border: 1px solid #394a7a;
                border-radius: 15px;
                font-family: 'Segoe UI Symbol';
                font-size: 18px;
                font-weight: 600;
            }
            QLabel#directionBadge[direction="download"] {
                background-color: #123b3a;
                color: #5ee3c2;
                border-color: #23605a;
            }
            QLabel#transferName {
                color: #f4f7fb;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#transferMeta, QLabel#transferSize {
                color: #8290a8;
                font-size: 10px;
            }
            QLabel#transferStatus {
                color: #b4a7ff;
                font-size: 10px;
                font-weight: 600;
            }
            QLabel#transferPercent {
                color: #c7d0df;
                font-size: 10px;
                font-weight: 600;
            }
            QProgressBar#transferProgress {
                min-height: 5px;
                max-height: 5px;
                background-color: #263249;
                border: none;
                border-radius: 2px;
            }
            QProgressBar#transferProgress::chunk {
                background-color: #786cf2;
                border-radius: 2px;
            }
            QProgressBar#transferProgress[state="completed"]::chunk {
                background-color: #2fcf91;
            }
            QProgressBar#transferProgress[state="error"]::chunk {
                background-color: #ef6464;
            }
            QPushButton#revealButton {
                background-color: transparent;
                border: 1px solid #34445f;
                border-radius: 5px;
                padding: 0;
            }
            QPushButton#revealButton:hover {
                background-color: #23324a;
                border-color: #556987;
            }
            """
        )
        self._setup_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_time)
        self.timer.start(1000)

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 10, 10, 10)
        outer.setSpacing(10)

        self.direction_badge = QLabel("↑" if self.is_upload else "↓")
        self.direction_badge.setObjectName("directionBadge")
        self.direction_badge.setProperty("direction", "upload" if self.is_upload else "download")
        self.direction_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.direction_badge.setFixedSize(30, 30)
        outer.addWidget(self.direction_badge, alignment=Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.name_label = QLabel(self._truncate_filename(self.filename, 46))
        self.name_label.setObjectName("transferName")
        self.name_label.setToolTip(self.filename)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.name_label.setMinimumWidth(80)
        title_row.addWidget(self.name_label, 1)

        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("transferPercent")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.percent_label.setMinimumWidth(34)
        title_row.addWidget(self.percent_label)
        body.addLayout(title_row)

        details_row = QHBoxLayout()
        details_row.setSpacing(8)
        self.time_label = QLabel(self._meta_text(0))
        self.time_label.setObjectName("transferMeta")
        details_row.addWidget(self.time_label)

        self.status_label = QLabel(t("Ожидание"))
        self.status_label.setObjectName("transferStatus")
        details_row.addWidget(self.status_label)
        details_row.addStretch()

        self.size_label = QLabel(self._format_progress_size(0, self.total_size))
        self.size_label.setObjectName("transferSize")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        details_row.addWidget(self.size_label)
        body.addLayout(details_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("transferProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        body.addWidget(self.progress_bar)
        outer.addLayout(body, 1)

        self.open_btn = QPushButton()
        self.open_btn.setObjectName("revealButton")
        self.open_btn.setToolTip(t("Показать в проводнике"))
        self.open_btn.setFixedSize(28, 28)
        style = self.open_btn.style()
        self.open_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_DirOpenIcon))
        self.open_btn.clicked.connect(self._show_in_explorer)
        self.open_btn.hide()
        outer.addWidget(self.open_btn, alignment=Qt.AlignmentFlag.AlignTop)

    def _direction_text(self) -> str:
        return t("Отправка") if self.is_upload else t("Получение")

    def _meta_text(self, elapsed: float) -> str:
        return f"{self._direction_text()} · {self._format_time(elapsed)}"

    def _update_time(self):
        elapsed = (self.end_time - self.start_time) if self.end_time else (time.perf_counter() - self.start_time)
        self.time_label.setText(self._meta_text(elapsed))

    def update_progress(self, transferred: int, speed: float):
        self.transferred = max(0, int(transferred or 0))
        percent = int((self.transferred / self.total_size) * 100) if self.total_size > 0 else 0
        percent = max(0, min(100, percent))
        self.progress_bar.setValue(percent)
        self.percent_label.setText(f"{percent}%")
        self.size_label.setText(self._format_progress_size(self.transferred, self.total_size))
        self.status_label.setText(self._format_speed(speed))

    def mark_complete(self):
        self.timer.stop()
        self.end_time = time.perf_counter()
        self.state = "completed"
        elapsed = self.end_time - self.start_time

        self.progress_bar.setValue(100)
        self._set_progress_state("completed")
        self.percent_label.setText("100%")
        final_size = max(self.total_size, self.transferred)
        self.size_label.setText(self._format_progress_size(final_size, final_size))
        self.time_label.setText(self._meta_text(elapsed))
        self.status_label.setText(t("Готово"))
        self.status_label.setStyleSheet("color: #4adea3;")

        if self.filepath and os.path.exists(self.filepath):
            self.open_btn.show()

    def set_filepath(self, filepath: str):
        self.filepath = filepath

    def _show_in_explorer(self):
        if self.filepath:
            reveal_in_explorer(self.filepath)

    def mark_error(self, error: str):
        self.timer.stop()
        self.end_time = time.perf_counter()
        self.state = "error"
        self.percent_label.setText("!")
        self.status_label.setText(t("Ошибка"))
        self.status_label.setStyleSheet("color: #f47b7b;")
        self._set_progress_state("error")
        self.setToolTip(error)

    def _set_progress_state(self, state: str):
        self.progress_bar.setProperty("state", state)
        self.progress_bar.style().unpolish(self.progress_bar)
        self.progress_bar.style().polish(self.progress_bar)
        self.progress_bar.update()

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
        if len(name) <= max_len:
            return name
        edge = max(1, (max_len - 3) // 2)
        return f"{name[:edge]}...{name[-edge:]}"

    @staticmethod
    def _format_size_only(size: int) -> str:
        size = max(0, int(size or 0))
        for unit in ["B", "KB", "MB", "GB"]:
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
        speed = max(0.0, float(speed or 0.0))
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
        self.setObjectName("transferPanel")
        self.setMinimumHeight(205)
        self.transfers: Dict[str, TransferItem] = {}
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(
            """
            QFrame#transferPanel {
                background-color: #121d32;
                border: 1px solid #30415e;
                border-radius: 8px;
            }
            QLabel#transferPanelTitle {
                color: #f4f7fb;
                font-size: 14px;
                font-weight: 650;
            }
            QLabel#transferCount {
                color: #8998af;
                font-size: 11px;
            }
            QLabel#transferEmpty {
                color: #66758d;
                font-size: 11px;
                padding: 22px;
            }
            QPushButton#clearTransfers {
                background-color: transparent;
                color: #8d9bb1;
                border: 1px solid transparent;
                border-radius: 5px;
                font-size: 18px;
                font-weight: 400;
                padding: 0;
            }
            QPushButton#clearTransfers:hover {
                background-color: #24324a;
                color: #f1f5f9;
                border-color: #3a4b66;
            }
            QScrollArea#transferScroll, QScrollArea#transferScroll QWidget#qt_scrollarea_viewport {
                border: none;
                background-color: transparent;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 10, 10)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel(t("Передачи"))
        title.setObjectName("transferPanelTitle")
        header.addWidget(title)

        self.count_label = QLabel(t("Нет активных"))
        self.count_label.setObjectName("transferCount")
        header.addStretch()
        header.addWidget(self.count_label)

        self.clear_btn = QPushButton("×")
        self.clear_btn.setObjectName("clearTransfers")
        self.clear_btn.setToolTip(t("Очистить завершённые"))
        self.clear_btn.setFixedSize(26, 26)
        self.clear_btn.clicked.connect(self.clear_completed)
        self.clear_btn.hide()
        header.addWidget(self.clear_btn)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("transferScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.list_container = QWidget()
        self.list_container.setObjectName("transferListContainer")
        self.list_container.setStyleSheet("QWidget#transferListContainer { background: transparent; }")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(7)

        self.empty_label = QLabel(t("История передач пуста"))
        self.empty_label.setObjectName("transferEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.list_container)
        layout.addWidget(self.scroll)

    def add_transfer(self, transfer_id: str, filename: str, total_size: int, is_upload: bool = True) -> TransferItem:
        if transfer_id in self.transfers:
            self.remove_transfer(transfer_id)
        item = TransferItem(transfer_id, filename, total_size, is_upload)
        self.transfers[transfer_id] = item
        self.list_layout.insertWidget(0, item)
        self._update_count()
        return item

    def update_transfer(self, transfer_id: str, transferred: int, speed: float):
        if transfer_id in self.transfers:
            self.transfers[transfer_id].update_progress(transferred, speed)

    def complete_transfer(self, transfer_id: str, filepath: str = None):
        if transfer_id in self.transfers:
            item = self.transfers[transfer_id]
            if filepath:
                item.set_filepath(filepath)
            item.mark_complete()
            self._move_after_active(item)
            self._update_count()

    def error_transfer(self, transfer_id: str, error: str):
        if transfer_id in self.transfers:
            item = self.transfers[transfer_id]
            item.mark_error(error)
            self._move_after_active(item)
            self._update_count()

    def _move_after_active(self, item: TransferItem):
        self.list_layout.removeWidget(item)
        active_count = sum(1 for transfer in self.transfers.values() if transfer.state == "in_progress")
        self.list_layout.insertWidget(active_count, item)

    def remove_transfer(self, transfer_id: str):
        item = self.transfers.pop(transfer_id, None)
        if item:
            self.list_layout.removeWidget(item)
            item.deleteLater()
            self._update_count()

    def clear_completed(self):
        completed = [
            transfer_id
            for transfer_id, item in self.transfers.items()
            if item.state != "in_progress"
        ]
        for transfer_id in completed:
            self.remove_transfer(transfer_id)
        self._update_count()

    def _update_count(self):
        active = sum(1 for item in self.transfers.values() if item.state == "in_progress")
        finished = len(self.transfers) - active
        if active and finished:
            self.count_label.setText(
                t("В процессе: {active} · Завершено: {finished}", active=active, finished=finished)
            )
        elif active:
            self.count_label.setText(t("В процессе: {count}", count=active))
        else:
            self.count_label.setText(t("Нет активных"))
        self.clear_btn.setVisible(finished > 0)
        self.empty_label.setVisible(not self.transfers)

    def set_low_power_mode(self, enabled: bool):
        for transfer in self.transfers.values():
            transfer.set_low_power_mode(enabled)
