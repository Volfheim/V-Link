"""Publish V-Link v2.4.2 release on GitHub."""
import json, os, sys, urllib.request, urllib.error

TAG = "v2.4.2"
REPO = "Volfheim/V-Link"
EXE_PATH = r"dist/V-Link.exe"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
if not TOKEN:
    if len(sys.argv) > 1:
        TOKEN = sys.argv[1].strip()
    else:
        print("Error: GITHUB_TOKEN environment variable or command-line argument is required.")
        sys.exit(1)

RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases"
UPLOAD_URL_TEMPLATE = "https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={name}"

def make_request(url, data=None, method=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("User-Agent", "V-Link-Release-Bot")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return req

def main():
    if not os.path.exists(EXE_PATH):
        print(f"Error: {EXE_PATH} not found")
        sys.exit(1)

    print(f"Checking existing release {TAG}...")
    req = make_request(f"{RELEASE_URL}/tags/{TAG}", headers={"Accept": "application/vnd.github.v3+json"})
    
    release_id = None
    try:
        with urllib.request.urlopen(req) as f:
            data = json.load(f)
            release_id = data['id']
            print(f"Found existing release ID: {release_id}")
            
            # Удаляем старый ассет, если он есть
            assets = data.get('assets', [])
            for asset in assets:
                if asset['name'] == os.path.basename(EXE_PATH):
                    asset_id = asset['id']
                    print(f"Deleting existing asset {asset['name']} (ID: {asset_id})...")
                    del_req = make_request(
                        f"https://api.github.com/repos/{REPO}/releases/assets/{asset_id}",
                        method="DELETE"
                    )
                    try:
                        with urllib.request.urlopen(del_req) as df:
                            print("Old asset deleted.")
                    except Exception as de:
                        print(f"Failed to delete old asset: {de}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"Error checking release (HTTP {e.code}): {e}")
            sys.exit(1)

    if not release_id:
        print(f"Creating release {TAG}...")
        body_text = (
            "### Features & Improvements in v2.4.2\n"
            "* **WebDAV Support:** Added read-only WebDAV server to easily transfer large folders (500+ GB) from PC to phone. Directly accessible from native File apps on iOS/Android.\n"
            "* **UI Fixes:** Fixed overlapping elements (ZIP download and Date sort selector) on mobile screens.\n"
            "* **Overscroll Fix:** Fixed the white background block shown when scrolling down past page limits on mobile browsers.\n"
            "* **Performance Optimizations:** Removed redundant SHA-256 calculation for file-info queries, significantly reducing CPU usage during mobile sync. Also moved blocking directory scan operations to background threads (`run_in_executor`)."
        )
        payload = json.dumps({
            "tag_name": TAG,
            "target_commitish": "main",
            "name": TAG,
            "body": body_text,
            "draft": False,
            "prerelease": False
        }).encode('utf-8')

        req = make_request(RELEASE_URL, data=payload, method="POST", headers={"Content-Type": "application/json"})
        
        try:
            with urllib.request.urlopen(req) as f:
                data = json.load(f)
                release_id = data['id']
                print(f"Release created: {data['html_url']}")
        except urllib.error.HTTPError as e:
            print(f"Failed to create release: {e}")
            print(e.read().decode())
            sys.exit(1)

    print(f"Uploading {EXE_PATH}...")
    with open(EXE_PATH, "rb") as f:
        content = f.read()
    
    filename = os.path.basename(EXE_PATH)
    upload_url = UPLOAD_URL_TEMPLATE.format(REPO=REPO, release_id=release_id, name=filename)
    
    req = make_request(
        upload_url, 
        data=content, 
        method="POST", 
        headers={"Content-Type": "application/vnd.microsoft.portable-executable"}
    )
    
    try:
        with urllib.request.urlopen(req) as f:
            print("Asset uploaded successfully!")
    except urllib.error.HTTPError as e:
        print(f"Upload failed: {e}")
        print(e.read().decode())
        sys.exit(1)

    print("Done!")

if __name__ == "__main__":
    main()
