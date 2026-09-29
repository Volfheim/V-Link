import sys

from core.i18n import i18n
from network.server import TransferServer


def test_mobile_html_loads_from_frozen_bundle_layout(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "ui").mkdir(parents=True)
    (bundle / "resources" / "locales").mkdir(parents=True)
    (bundle / "resources" / "logo.png").write_bytes(b"logo")
    (bundle / "resources" / "locales" / "ru.json").write_text("{}", encoding="utf-8")
    (bundle / "resources" / "locales" / "en.json").write_text("{}", encoding="utf-8")
    (bundle / "ui" / "web_interface.html").write_text(
        "<html>{{HTML_LANG}}{{LOGO_BASE64}}{{I18N_JSON}}</html>", encoding="utf-8"
    )

    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    i18n.load("ru")
    html = TransferServer()._load_mobile_html()

    assert "Web interface file not found" not in html
    assert "<html>ru" in html
    assert "bG9nbw==" in html
