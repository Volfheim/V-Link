"""
V-Link - Стили QSS с фиолетовыми градиентами
"""

# Цветовая палитра
COLORS = {
    'bg_primary': '#1a1a2e',
    'bg_secondary': '#16213e',
    'bg_tertiary': '#0f0f23',
    'gradient_start': '#6b5ce7',
    'gradient_end': '#a855f7',
    'accent': '#c084fc',
    'accent_hover': '#d8b4fe',
    'text_primary': '#f8fafc',
    'text_secondary': '#94a3b8',
    'text_muted': '#64748b',
    'success': '#22c55e',
    'warning': '#f59e0b',
    'error': '#ef4444',
    'border': '#334155',
}

MAIN_STYLE = """
QMainWindow {
    background-color: #1a1a2e;
}

QWidget {
    color: #f8fafc;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* Заголовки */
QLabel#titleLabel {
    font-size: 24px;
    font-weight: bold;
    color: #f8fafc;
}

QLabel#subtitleLabel {
    font-size: 14px;
    color: #94a3b8;
}

/* Панели */
QFrame#panel {
    background-color: #16213e;
    border: 1px solid #334155;
    border-radius: 12px;
}

QFrame#dropZone {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(107, 92, 231, 0.1),
        stop:1 rgba(168, 85, 247, 0.1));
    border: 2px dashed #6b5ce7;
    border-radius: 16px;
}

QFrame#dropZone:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(107, 92, 231, 0.2),
        stop:1 rgba(168, 85, 247, 0.2));
    border: 2px dashed #a855f7;
}

QFrame#dropZoneActive {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(107, 92, 231, 0.3),
        stop:1 rgba(168, 85, 247, 0.3));
    border: 2px solid #c084fc;
}

/* Кнопки */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6b5ce7, stop:1 #a855f7);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: bold;
    font-size: 13px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7c6ef0, stop:1 #b366ff);
}

QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5a4dd6, stop:1 #9744e6);
}

QPushButton:disabled {
    background: #334155;
    color: #64748b;
}

QPushButton#secondaryBtn {
    background: transparent;
    border: 1px solid #6b5ce7;
    color: #c084fc;
}

QPushButton#secondaryBtn:hover {
    background: rgba(107, 92, 231, 0.2);
}

/* Список устройств */
QListWidget {
    background-color: #16213e;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}

QListWidget::item {
    background-color: transparent;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 2px 0;
}

QListWidget::item:hover {
    background-color: rgba(107, 92, 231, 0.2);
}

QListWidget::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(107, 92, 231, 0.4), stop:1 rgba(168, 85, 247, 0.4));
    border: 1px solid #6b5ce7;
}

/* Прогресс бар */
QProgressBar {
    background-color: #0f0f23;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: #f8fafc;
    font-size: 11px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6b5ce7, stop:1 #a855f7);
    border-radius: 6px;
}

/* Скроллбар */
QScrollBar:vertical {
    background-color: #1a1a2e;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #334155;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #6b5ce7;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #1a1a2e;
    height: 8px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #334155;
    border-radius: 4px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #6b5ce7;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Поля ввода */
QLineEdit {
    background-color: #0f0f23;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 12px;
    color: #f8fafc;
}

QLineEdit:focus {
    border: 1px solid #6b5ce7;
}

/* Меню */
QMenu {
    background-color: #16213e;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 4px;
}

QMenu::item {
    padding: 8px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: rgba(107, 92, 231, 0.3);
}

/* Тулбар заголовка */
QFrame#titleBar {
    background-color: #0f0f23;
    border-bottom: 1px solid #334155;
}

/* Статус индикатор */
QLabel#statusOnline {
    color: #22c55e;
}

QLabel#statusOffline {
    color: #64748b;
}

/* Таблица передач */
QTableWidget {
    background-color: #16213e;
    border: 1px solid #334155;
    border-radius: 8px;
    gridline-color: #334155;
}

QTableWidget::item {
    padding: 8px;
}

QHeaderView::section {
    background-color: #0f0f23;
    color: #94a3b8;
    border: none;
    padding: 8px;
    font-weight: bold;
}
"""

def get_stylesheet():
    """Получить полный стиль приложения"""
    return MAIN_STYLE
