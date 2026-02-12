"""Create GitHub Release for V-Link v2.0.1 and upload EXE."""
import json, os, sys, urllib.request, urllib.error, mimetypes

TAG = "v2.1.0"
REPO = "Volfheim/V-Link"
EXE = r"E:\Gravity\V-Link\dist\V-Link.exe"
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

BODY = r"""## 📱 Mobile Web Revolution (v2.1.0)

Полностью новый мобильный интерфейс для передачи файлов!

### ✨ Что нового?
- **Dark Mode**: Стильный темный дизайн.
- **Интерактивность**:
    - Прогресс-бар загрузки (реальное отображение %).
    - Всплывающие уведомления (Toast).
    - Автообновление списка файлов.
- **Удобство**: Крупные кнопки для тач-экранов, анимации.
- **Язык**: Интерфейс полностью на русском.

**Full Changelog**: https://github.com/Volfheim/V-Link/compare/v2.0.2...v2.1.0
"""

headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github+json",
    "Content-Type": "application/json",
}

# 1. Check if release exists and delete it (re-release support)
try:
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as f:
        existing = json.load(f)
    print(f"Release {TAG} exists. Deleting...")
    
    del_url = existing['url']
    req_del = urllib.request.Request(del_url, method="DELETE", headers=headers)
    with urllib.request.urlopen(req_del):
        print("Old release deleted.")
except urllib.error.HTTPError as e:
    if e.code != 404:
        print(f"Error checking release: {e.code}")
        sys.exit(1)

# 2. Create Release
print(f"Creating release {TAG}...")
payload = json.dumps({
    "tag_name": TAG, 
    "name": f"V-Link {TAG}", 
    "body": BODY.strip(), 
    "draft": False, 
    "prerelease": False
}).encode()

req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases", data=payload, headers=headers, method="POST")
try:
    with urllib.request.urlopen(req) as f:
        release = json.loads(f.read().decode())
    print(f"Release created: {release['html_url']}")
    upload_url = release["upload_url"].split("{")[0]
except urllib.error.HTTPError as e:
    print(f"Error creating release: {e.code} {e.read().decode()}")
    sys.exit(1)

# 3. Upload EXE
fname = os.path.basename(EXE)
print(f"Uploading {fname}...")
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
    with urllib.request.urlopen(req2) as f:
        asset = json.loads(f.read().decode())
    print(f"Asset uploaded: {asset['name']} ({asset['size']//1024} KB)")
except urllib.error.HTTPError as e:
    print(f"Error uploading asset: {e.code} {e.read().decode()}")
    sys.exit(1)

print("Done!")
