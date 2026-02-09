"""
V-Link entry point.
"""

import asyncio
import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from main_window import MainWindow


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("V-Link")
    app.setOrganizationName("Volfheim")

    icon_path = resource_path("app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    elif os.path.exists("app_icon.ico"):
        app.setWindowIcon(QIcon("app_icon.ico"))

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    if window.settings.start_minimized:
        window.hide()
    else:
        window.show()
    window.show_startup_state()

    async def bootstrap():
        try:
            await window.start_services()
            if window.settings.start_minimized:
                window.hide()
                await window.enter_low_power_mode()
        except Exception as e:
            try:
                await window.stop_services()
            except Exception:
                pass
            QMessageBox.critical(
                None,
                "V-Link",
                f"Не удалось запустить приложение.\n\nПричина: {e}",
            )
            app.quit()

    loop.create_task(bootstrap())

    with loop:
        sys.exit(loop.run_forever())


if __name__ == "__main__":
    main()
