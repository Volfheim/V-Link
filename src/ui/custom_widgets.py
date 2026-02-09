"""
V-Link - Custom Widgets
Кастомные виджеты с улучшенным отображением
"""

from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt, pyqtSignal


class CheckBoxWithMark(QWidget):
    """Checkbox с видимой галочкой"""
    
    toggled = pyqtSignal(bool)
    
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._checked = False
        self.text = text
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)
        
        # Кастомный индикатор
        self.indicator = QLabel("  ")
        self.indicator.setFixedSize(20, 20)
        self._update_style()
        layout.addWidget(self.indicator)
        
        # Текст
        self.label = QLabel(self.text)
        self.label.setStyleSheet("color: #f8fafc; font-size: 13px;")
        layout.addWidget(self.label)
        layout.addStretch()
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def _update_style(self):
        if self._checked:
            self.indicator.setStyleSheet("""
                background-color: #6b5ce7;
                border: 2px solid #6b5ce7;
                border-radius: 4px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            """)
            self.indicator.setText("✓")
            self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.indicator.setStyleSheet("""
                background-color: #0f0f23;
                border: 2px solid #334155;
                border-radius: 4px;
            """)
            self.indicator.setText("")
    
    def isChecked(self) -> bool:
        return self._checked
    
    def setChecked(self, checked: bool):
        self._checked = checked
        self._update_style()
    
    def setToolTip(self, tip: str):
        super().setToolTip(tip)
        self.indicator.setToolTip(tip)
        self.label.setToolTip(tip)
    
    def mousePressEvent(self, event):
        self._checked = not self._checked
        self._update_style()
        self.toggled.emit(self._checked)
