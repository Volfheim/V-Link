from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from main_window import MainWindow


class MobileServerStub:
    port = 17864

    def __init__(self):
        self.disabled = False

    def is_running(self):
        return True

    def enable_mobile_share(self, ttl_sec):
        assert ttl_sec == 0
        return "example"

    def get_mobile_url(self, host_ip):
        return f"http://{host_ip}:{self.port}/?token=example"

    def disable_mobile_share(self):
        self.disabled = True


def test_window_resizes_and_mobile_button_opens_dialog(monkeypatch):
    monkeypatch.setenv("VLINK_SKIP_AUTOSTART_SYNC", "1")
    app = QApplication.instance() or QApplication([])
    assert app is not None

    window = MainWindow()
    server = MobileServerStub()
    window.server = server
    monkeypatch.setattr(window, "_best_mobile_ip", lambda: "192.168.0.24")
    monkeypatch.setattr(window, "_probe_local_lan_endpoint", lambda *_args: None)
    try:
        window.show()
        for width in (650, 807, 650):
            window.resize(width, 971)
            app.processEvents()
            central = window.centralWidget()
            assert central.width() == width
            assert central.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            for widget in (window.device_list, window.drop_zone, window.transfer_list):
                assert widget.geometry().right() <= central.geometry().right()
            background = window.grab().toImage().pixelColor(width - 10, 80)
            assert background.name() == "#1a1a2e"

        window.mobile_btn.click()
        app.processEvents()
        assert window.mobile_dialog is not None
        assert window.mobile_dialog.isVisible()
        assert window.mobile_dialog.url_edit.text().endswith("token=example")
    finally:
        if window.mobile_dialog:
            window.mobile_dialog.close()
        window.close()
    assert server.disabled
