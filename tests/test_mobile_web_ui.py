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


def test_large_downloads_use_one_shot_native_links():
    html = load_web_ui()
    download_function = html.split("async function downloadFile", 1)[1].split(
        "async function downloadCurrentFolder", 1
    )[0]

    assert "const activeDownloads = new Set();" in html
    assert "data-direct=\"${isDirect ? '1' : '0'}\"" in html
    assert "if (activeDownloads.has(filePath))" in html
    assert "el.dataset.direct === '1'" in html
    assert "scheduleNativeDownloadUnlock(filePath, el);" in html
    assert "setTimeout(() => browseTo(currentPath), 1000);" not in html
    assert "size > 50 * 1024 * 1024" not in download_function


def test_android_large_archives_use_http_compatible_download_names():
    html = load_web_ui()

    assert "const IS_ANDROID = /Android/i.test(navigator.userAgent);" in html
    assert "'zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2', 'xz', 'iso'" in html
    assert "needsAndroidArchiveCompatibility(item.name, item.size)" in html
    assert "useArchiveCompat ? '&compat=1' : ''" in html
    assert "useArchiveCompat ? `${safeName}.txt` : safeName" in html
    assert "Remove the final .txt after downloading." in html


def test_large_folder_download_does_not_open_two_streams():
    html = load_web_ui()
    folder_function = html.split("async function downloadCurrentFolder", 1)[1].split(
        "// --- Upload queue", 1
    )[0]

    assert "/api/mobile/file-info/" in folder_function
    assert folder_function.count("const res = await fetch(url);") == 1
    assert folder_function.index("const infoRes = await fetch(infoUrl);") < folder_function.index(
        "const res = await fetch(url);"
    )
    assert "folderName + (useArchiveCompat ? '.zip.txt' : '.zip')" in folder_function
