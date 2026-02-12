"""Create GitHub Release for V-Link v2.1.3 and upload EXE."""
import json, os, sys, urllib.request, urllib.error, mimetypes

TAG = "v2.1.3"
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

BODY = r"""## 💎 Visual Polish (v2.1.3)

Refined branding and UI aesthetics.

### ✨ Changes
- **Logo**: Replaced generic icon with custom V-Link branding (PNG) embedded directly.
- **Theme**: Updated background gradient to a deeper, more premium purple (`#170F30` -> `#0B1020`).
- **Access Denied**: Updated error pages to match the new branding.

**Full Changelog**: https://github.com/Volfheim/V-Link/compare/v2.1.2...v2.1.3
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
        print("Deleted existing release.")
except urllib.error.HTTPError as e:
    if e.code != 404:
        raise

# 2. CRUD Release
print(f"Creating release {TAG}...")
data = {
    "tag_name": TAG,
    "target_commitish": "main",
    "name": TAG,
    "body": BODY,
    "draft": False,
    "prerelease": False
}

req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases",
                             data=json.dumps(data).encode('utf-8'),
                             headers=headers, method="POST")
with urllib.request.urlopen(req) as f:
    release = json.load(f)
    upload_url_template = release['upload_url']

print(f"Release created: {release['html_url']}")

# 3. Upload Asset
upload_url = upload_url_template.replace("{?name,label}", f"?name={os.path.basename(EXE)}")
print(f"Uploading {EXE}...")

with open(EXE, 'rb') as f:
    file_data = f.read()

req_up = urllib.request.Request(upload_url, data=file_data, headers={
    **headers,
    "Content-Type": "application/vnd.microsoft.portable-executable"
}, method="POST")

with urllib.request.urlopen(req_up) as f:
    print("Asset uploaded successfully.")

print("Done!")
