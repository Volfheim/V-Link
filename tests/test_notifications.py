from PyQt6.QtWidgets import QApplication

import main_window


class MemorySettings:
    def __init__(self):
        self.values = {
            "clipboard_sync_enabled": False,
            "clipboard_sync_images": False,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    @property
    def autostart(self):
        return False

    @property
    def port(self):
        return 8765

    @property
    def clipboard_node_id(self):
        return "notification-test"

    @property
    def language(self):
        return "system"


def test_clicking_transfer_notification_reveals_target(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    opened = []
    target = tmp_path / "received.txt"
    target.write_text("ok", encoding="utf-8")

    monkeypatch.setattr(main_window, "set_autostart", lambda _enabled: None)
    monkeypatch.setattr(main_window, "reveal_in_explorer", lambda path: opened.append(path) or True)

    window = main_window.MainWindow(settings=MemorySettings())
    try:
        window._notification_target_path = str(target)
        window.tray_icon.messageClicked.emit()
        app.processEvents()
        assert opened == [str(target)]
    finally:
        window._quitting = True
        window.tray_icon.hide()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_long_transfer_name_keeps_notification_action_visible(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    target = tmp_path / "Recreate Studio - Brainrot Song (feat. PartyTunesOfficial).mp3"
    shown = []

    monkeypatch.setattr(main_window, "set_autostart", lambda _enabled: None)

    window = main_window.MainWindow(settings=MemorySettings())
    try:
        monkeypatch.setattr(window.tray_icon, "isVisible", lambda: True)
        monkeypatch.setattr(
            window.tray_icon,
            "showMessage",
            lambda title, message, icon, timeout: shown.append(
                (title, message, icon, timeout)
            ),
        )
        window._transfer_directions["transfer-1"] = ("in", 2_000_000)

        window._on_transfer_complete("transfer-1", str(target))

        title, message, _icon, timeout = shown[0]
        assert title == "Получен файл · Открыть"
        assert message == f"1.9 МБ · {target.name}"
        assert "Нажмите" not in message
        assert timeout == 6000
    finally:
        window._quitting = True
        window.tray_icon.hide()
        window.close()
        window.deleteLater()
        app.processEvents()
