"""Create GitHub Release for V-Link v1.9.3 and upload EXE."""
import json, os, sys, urllib.request, urllib.error, mimetypes

TAG = "v1.9.4"
REPO = "Volfheim/V-Link"
EXE = r"E:\Gravity\V-Link\dist\V-Link-1.9.4.exe"
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

### 🔄 Completely Reworked Update System
The auto-update mechanism has been rebuilt from the ground up for maximum reliability:
- **Atomic Updates**: Downloads to a temporary file, unblocks it, and performs a safe atomic replacement.
- **No More "DLL Load Failed"**: Solves issues with file locking and corrupted updates.
- **Fail-Safe Logic**: Uses robust process waiting (`tasklist` loop) to ensure the old version is truly closed before replacing.
- **Automatic Cleanup**: Old versions and temporary files are automatically removed after a successful update.
- **Loop Prevention**: Smart flags prevent infinite update loops.

### Notes
- **UI**: "Powered by Volfheim" footer is present.
- **Stable Release**: This version focuses on fixing the update flow once and for all.
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
