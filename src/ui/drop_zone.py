"""
V-Link - Drop Zone Widget
Зона для перетаскивания файлов с визуальными эффектами
"""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QFileDialog
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent


class DropZone(QFrame):
    """Зона Drag & Drop для файлов"""
    
    files_dropped = pyqtSignal(list)  # Сигнал при перетаскивании файлов
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Настройка UI"""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)
        
        # Иконка (текстовый блок)
        self.icon_label = QLabel("[ + ]")
        self.icon_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #6b5ce7;")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        
        # Основной текст
        self.main_label = QLabel("Перетащите файлы сюда")
        self.main_label.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #f8fafc;
        """)
        self.main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.main_label)
        
        # Подсказка
        self.hint_label = QLabel("или нажмите для выбора")
        self.hint_label.setStyleSheet("""
            font-size: 13px;
            color: #94a3b8;
        """)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.hint_label)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Файл входит в зону"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("dropZoneActive")
            self.style().unpolish(self)
            self.style().polish(self)
            self.icon_label.setText("[ >>> ]")
            self.main_label.setText("Отпустите для добавления")
    
    def dragLeaveEvent(self, event):
        """Файл покидает зону"""
        self.setObjectName("dropZone")
        self.style().unpolish(self)
        self.style().polish(self)
        self.icon_label.setText("[ + ]")
        self.main_label.setText("Перетащите файлы сюда")
    
    def dropEvent(self, event: QDropEvent):
        """Файлы сброшены"""
        self.setObjectName("dropZone")
        self.style().unpolish(self)
        self.style().polish(self)
        self.icon_label.setText("[ + ]")
        self.main_label.setText("Перетащите файлы сюда")
        
        files = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                files.append(path)
        
        if files:
            self.files_dropped.emit(files)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Клик для открытия диалога выбора файлов"""
        if event.button() == Qt.MouseButton.LeftButton:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "Выберите файлы для передачи",
                "",
                "Все файлы (*.*)"
            )
            if files:
                self.files_dropped.emit(files)
