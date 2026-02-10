"""Create GitHub Release for V-Link v1.9.1 and upload EXE."""
import json, os, sys, urllib.request, urllib.error, mimetypes

TAG = "v1.9.2"
REPO = "Volfheim/V-Link"
EXE = r"E:\Gravity\V-Link\dist\V-Link-1.9.2.exe"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    import subprocess as _sp
    try:
        r = _sp.run(['git','credential','fill'],
                     input='protocol=https\nhost=github.com\n\n',
                     capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith('password='):
                TOKEN = line.split('=',1)[1].strip()
                break
    except Exception:
        pass
if not TOKEN:
    sys.exit("No GitHub token found")

BODY = r"""## What's Changed

### 🐛 Critical auto-update fix
- Fixed auto-update failing when the EXE is on a different drive than `%LOCALAPPDATA%` (e.g. D:/E: vs C:).
- Replaced `move` with `copy /B` + `del` in the update helper script — `move` silently corrupts PyInstaller EXEs across drives.
- Windows Zone.Identifier (Alternate Data Stream) is now stripped from downloaded EXEs before launch, preventing Defender from blocking DLL extraction.
- Added file verification: if the copy fails, the old EXE is restored automatically.
- Extra delays added before/after EXE swap for reliable file handle release.

### ✨ Cosmetic
- App version is now shown in the tray icon tooltip (e.g. "V-Link v1.9.2").
- Update dialog now displays clean text instead of raw Markdown symbols.

### Implementation details
- `updater.py`: `os.remove(Zone.Identifier)` before bat launch; bat script uses `copy /Y /B` + `if not exist` guard.
- `main_window.py`: `setToolTip(f"V-Link v{__version__}")` + regex-based markdown stripping in update dialog.
"""

headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github+json",
    "Content-Type": "application/json",
}

# Create release
payload = json.dumps({"tag_name": TAG, "name": f"V-Link {TAG}", "body": BODY.strip(), "draft": False, "prerelease": False}).encode()
req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases", data=payload, headers=headers, method="POST")
try:
    resp = urllib.request.urlopen(req)
    release = json.loads(resp.read().decode())
    upload_url = release["upload_url"].split("{")[0]
    print(f"Release created: {release['html_url']}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"Error creating release: {e.code} {body}")
    sys.exit(1)

# Upload EXE
fname = os.path.basename(EXE)
with open(EXE, "rb") as f:
    data = f.read()
up_headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github+json",
    "Content-Type": "application/octet-stream",
}
up_url = f"{upload_url}?name={fname}"
req2 = urllib.request.Request(up_url, data=data, headers=up_headers, method="POST")
try:
    resp2 = urllib.request.urlopen(req2)
    asset = json.loads(resp2.read().decode())
    print(f"Asset uploaded: {asset['name']} ({asset['size']//1024} KB)")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"Error uploading asset: {e.code} {body}")
    sys.exit(1)

print("Done!")
