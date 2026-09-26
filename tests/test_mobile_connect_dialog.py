from PyQt6.QtWidgets import QApplication

from ui.mobile_connect_dialog import MobileConnectDialog


def test_mobile_dialog_renders_qr_without_pillow(monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app is not None

    import qrcode

    def fail_if_image_backend_used(*_args, **_kwargs):
        raise AssertionError("QR rendering must not load Pillow")

    monkeypatch.setattr(qrcode.QRCode, "make_image", fail_if_image_backend_used)
    dialog = MobileConnectDialog(
        "http://192.168.0.24:17864/?token=example", "example"
    )
    try:
        pixmap = dialog.qr_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
        assert pixmap.width() <= 320
        assert pixmap.height() <= 320
        image = pixmap.toImage()
        colors = {
            image.pixelColor(x, y).name()
            for y in range(image.height())
            for x in range(image.width())
        }
        assert colors == {"#000000", "#ffffff"}
        assert dialog.url_edit.text().endswith("token=example")
    finally:
        dialog.close()
