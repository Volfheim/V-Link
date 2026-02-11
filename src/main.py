"""
V-Link entry point.
"""

import os
import sys


def _consume_arg(flag: str) -> str:
    if flag not in sys.argv:
        return ""
    idx = sys.argv.index(flag)
    value = ""
    if idx + 1 < len(sys.argv):
        value = sys.argv[idx + 1]
        del sys.argv[idx:idx + 2]
    else:
        del sys.argv[idx]
    return value


def _consume_switch(flag: str) -> bool:
    if flag in sys.argv:
        sys.argv.remove(flag)
        return True
    return False


def _write_ready_flag(path: str):
    if not path:
        return
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("ready")
    except Exception:
        pass


if "--self-test" in sys.argv:
    sys.exit(0)

_update_ready_flag = _consume_arg("--update-ready-flag")
_show_after_update = _consume_switch("--show-after-update")

import asyncio
from PyQt6.QtCore import Qt
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
    if _show_after_update:
        window.show()
    elif window.settings.start_minimized:
        window.hide()
    else:
        window.show()
    window.show_startup_state()

    async def bootstrap():
        try:
            await window.start_services()

            if _show_after_update:
                window.setWindowState(
                    (window.windowState() & ~Qt.WindowState.WindowMinimized)
                    | Qt.WindowState.WindowActive
                )
                window.showNormal()
                window.show()
                window.raise_()
                window.activateWindow()
                if window._low_power_mode:
                    await window.exit_low_power_mode()
            elif window.settings.start_minimized:
                window.hide()
                await window.enter_low_power_mode()

            _write_ready_flag(_update_ready_flag)
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
