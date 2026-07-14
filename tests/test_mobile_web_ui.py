from pathlib import Path


WEB_UI_PATH = Path(__file__).resolve().parents[1] / "src" / "ui" / "web_interface.html"


def load_web_ui() -> str:
    return WEB_UI_PATH.read_text(encoding="utf-8")


def test_mobile_page_uses_dark_root_background_without_fixed_attachment():
    html = load_web_ui()

    assert "background-attachment: fixed" not in html
    assert "background-color: #0B1020;" in html
    assert "min-height: 100dvh;" in html
    assert html.count("overscroll-behavior-y: none;") == 2


def test_upload_progress_is_hidden_and_reset_after_completion():
    html = load_web_ui()
    completion = html.split("if (fileIndex >= files.length) {", 1)[1].split(
        "const file = files[fileIndex];", 1
    )[0]

    assert 'id="progressBarWrap"' in html
    assert ".progress-bar-wrap.active { opacity: 1; }" in html
    assert "startUploadProgress();" in html
    assert "scheduleUploadProgressReset();" in completion
    assert "dom.progressBarWrap.classList.remove('active');" in html
    assert "dom.progressBar.style.width = '0%';" in html
