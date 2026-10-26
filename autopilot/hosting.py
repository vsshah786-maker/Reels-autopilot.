"""Instagram needs to DOWNLOAD the video from a public link. These give the video a temporary free link."""
import os
import time

import requests

from .common import log, secret


def litterbox(path, hours="24h"):
    """Free anonymous temporary file host (catbox.moe). The file auto-deletes after 24 h."""
    with open(path, "rb") as f:
        r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                          data={"reqtype": "fileupload", "time": hours},
                          files={"fileToUpload": (os.path.basename(path), f, "video/mp4")}, timeout=300)
    r.raise_for_status()
    url = r.text.strip()
    if not url.startswith("https://"):
        raise RuntimeError(f"litterbox answered: {url[:200]}")
    return url, None


def github_release(path, tag):
    """Uploads the video to a GitHub Release of your repo (works only if the repo is PUBLIC)."""
    token, repo = secret("GITHUB_TOKEN"), secret("GITHUB_REPOSITORY")
    if not token or not repo:
        raise RuntimeError("GITHUB_TOKEN/GITHUB_REPOSITORY not available (only inside GitHub Actions)")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.post(f"https://api.github.com/repos/{repo}/releases", headers=h, timeout=30,
                      json={"tag_name": tag, "name": tag, "body": "Temporary reel upload", "prerelease": True})
    r.raise_for_status()
    rel = r.json()
    with open(path, "rb") as f:
        up = requests.post(rel["upload_url"].split("{")[0], params={"name": os.path.basename(path)},
                           headers={**h, "Content-Type": "video/mp4"}, data=f, timeout=300)
    up.raise_for_status()
    dl = up.json()["browser_download_url"]
    # Instagram does not like redirects - resolve to the final file link
    final = requests.get(dl, stream=True, timeout=30, allow_redirects=True)
    final.close()
    if final.status_code != 200:
        raise RuntimeError(f"release asset not public (HTTP {final.status_code}) - is the repo private?")

    def cleanup():
        requests.delete(f"https://api.github.com/repos/{repo}/releases/{rel['id']}", headers=h, timeout=30)
        requests.delete(f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}", headers=h, timeout=30)
    return final.url, cleanup


def public_url(path, method, tag):
    order = {"litterbox": [litterbox], "github": [github_release]}.get(method, [github_release, litterbox])
    last = None
    for fn in order:
        try:
            url, cleanup = fn(path, tag) if fn is github_release else fn(path)
            log.info(f"    Video link ready via {fn.__name__}")
            return url, cleanup
        except Exception as e:
            last = e
            log.warning(f"    {fn.__name__} failed: {e}")
            time.sleep(2)
    raise RuntimeError(f"Could not get a public link for the video: {last}")
