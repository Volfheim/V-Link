"""
V-Link entry point.
"""

import os
import sys
from pathlib import Path


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


def _set_windows_app_id():
    """
    Ensure taskbar icon uses the app icon consistently on Windows.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Volfheim.VLink")
    except Exception:
        pass


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

from crash_reporter import (
    install_asyncio_exception_handler,
    install_exception_hooks,
    install_qasync_timer_guard,
)

_crash_log_path = install_exception_hooks()
install_qasync_timer_guard(_crash_log_path)

import asyncio
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from core import Settings, i18n, t
from main_window import MainWindow


def resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def _instance_lock_path() -> str:
    lock_dir = Path.home() / ".v-link"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return str(lock_dir / "instance.lock")


def main():
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("V-Link")
    app.setOrganizationName("Volfheim")
    settings = Settings()
    i18n.load(settings.language)

    # Prefer executable icon in frozen mode (best taskbar compatibility on Windows).
    app_icon = QIcon()
    if getattr(sys, "frozen", False):
        exe_icon = QIcon(sys.executable)
        if not exe_icon.isNull():
            app_icon = exe_icon

    if app_icon.isNull():
        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
        elif os.path.exists("app_icon.ico"):
            app_icon = QIcon("app_icon.ico")

    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # Protect against duplicate launches (Run key + Startup folder, manual second launch, etc.).
    from PyQt6.QtCore import QLockFile
    instance_lock = QLockFile(_instance_lock_path())
    instance_lock.setStaleLockTime(15000)
    if not instance_lock.tryLock(250):
        QMessageBox.information(
            None,
            "V-Link",
            t("V-Link уже запущен.\nПроверьте окно приложения или иконку в системном трее."),
        )
        return 0
    app._instance_lock = instance_lock

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    install_asyncio_exception_handler(loop, _crash_log_path)

    window = MainWindow(settings=settings)
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
            else:
                # Обычный запуск
                window.setWindowState(
                    (window.windowState() & ~Qt.WindowState.WindowMinimized)
                    | Qt.WindowState.WindowActive
                )
                window.showNormal()
                window.show()
                window.raise_()
                window.activateWindow()

            _write_ready_flag(_update_ready_flag)
        except Exception as e:
            try:
                await window.stop_services()
            except Exception:
                pass
            message = (
                t(
                    "Сетевые сервисы не удалось запустить.\n\nПричина: {error}\n\n"
                    "Приложение останется открытым: проверьте настройки порта и повторите запуск сервисов "
                    "через перезапуск программы.",
                    error=e,
                )
            )
            QMessageBox.warning(None, "V-Link", message)
            window.show()
            window.raise_()
            window.activateWindow()
            window.show_startup_state(t("● Ошибка запуска сервисов (нужен перезапуск)"))
            try:
                window.status_label.setStyleSheet("color: #ef4444; font-size: 12px;")
            except Exception:
                pass

    loop.create_task(bootstrap())

    with loop:
        return loop.run_forever()


if __name__ == "__main__":
    sys.exit(main())
