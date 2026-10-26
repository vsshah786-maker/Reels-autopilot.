"""Finds free background clips/photos for each screen of the reel.
Order of preference depends on config video.background_source:
  pexels   -> Pexels videos -> Pexels photos -> Openverse photos (no key) -> plain gradient
  my_clips -> your own files in assets/my_clips -> gradient
  mixed    -> your own files first, then the pexels chain
"""
import hashlib
import os
import random
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

from .common import ASSETS, CACHE, log, secret

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
UA = {"User-Agent": "FacelessReelsAutopilot/1.0"}


class Background:
    def __init__(self, path, kind, credit=None):
        self.path = Path(path)
        self.kind = kind  # "video" | "image"
        self.credit = credit

    def __repr__(self):
        return f"<{self.kind} {self.path.name}>"


def _dl(url, suffix):
    CACHE.mkdir(exist_ok=True)
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + suffix
    p = CACHE / name
    if p.exists() and p.stat().st_size > 10_000:
        return p
    with requests.get(url, headers=UA, timeout=60, stream=True) as r:
        r.raise_for_status()
        with open(p, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    if p.stat().st_size < 10_000:
        p.unlink()
        raise IOError("download too small")
    return p


# ---------------- Pexels (free key from pexels.com/api) ----------------
def pexels_videos(query, n, used):
    key = secret("PEXELS_API_KEY")
    if not key:
        return []
    r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                     params={"query": query, "orientation": "portrait", "per_page": 15}, timeout=30)
    r.raise_for_status()
    out = []
    vids = r.json().get("videos", [])
    random.shuffle(vids)
    for v in vids:
        if v["id"] in used or v.get("duration", 0) < 4:
            continue
        files = [f for f in v.get("video_files", []) if f.get("height") and f.get("width")
                 and f["height"] > f["width"] and f["height"] >= 1280 and f.get("file_type") == "video/mp4"]
        if not files:
            continue
        files.sort(key=lambda f: abs(f["height"] - 1920))
        try:
            p = _dl(files[0]["link"], ".mp4")
        except Exception as e:
            log.warning(f"Pexels download failed: {e}")
            continue
        used.add(v["id"])
        who = (v.get("user") or {}).get("name", "Pexels")
        out.append(Background(p, "video", f"Video by {who} on Pexels"))
        if len(out) >= n:
            break
    return out


def pexels_photos(query, n, used):
    key = secret("PEXELS_API_KEY")
    if not key:
        return []
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                     params={"query": query, "orientation": "portrait", "per_page": 15}, timeout=30)
    r.raise_for_status()
    out = []
    for ph in r.json().get("photos", []):
        if ph["id"] in used:
            continue
        try:
            p = _dl(ph["src"].get("large2x") or ph["src"]["original"], ".jpg")
        except Exception:
            continue
        used.add(ph["id"])
        out.append(Background(p, "image", f"Photo by {ph.get('photographer', 'Pexels')} on Pexels"))
        if len(out) >= n:
            break
    return out


# ---------------- Openverse (no key needed; Creative Commons photos) ----------------
def openverse_photos(query, n, used):
    r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=30, params={
        "q": query, "license": "cc0,pdm,by", "aspect_ratio": "tall", "size": "large",
        "page_size": 20, "mature": "false"})
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        if it["id"] in used:
            continue
        if it.get("height") and it.get("width") and (it["height"] < 900 or it["width"] > it["height"]):
            continue
        try:
            p = _dl(it["url"], ".jpg")
            with Image.open(p) as im:
                w, h = im.size
            if h < 900 or w >= h:
                continue
        except Exception:
            continue
        used.add(it["id"])
        lic = (it.get("license") or "").upper()
        credit = None
        if lic not in ("CC0", "PDM"):
            credit = f"\"{(it.get('title') or 'photo')[:40]}\" by {it.get('creator') or 'unknown'} (CC {lic} {it.get('license_version', '')})"
        out.append(Background(p, "image", credit))
        if len(out) >= n:
            break
    return out


# ---------------- your own clips ----------------
def my_clips(n, used, repeat=False):
    folder = Path(os.environ.get("AUTOPILOT_CLIPS_DIR") or (ASSETS / "my_clips"))
    files = [p for p in sorted(folder.glob("**/*")) if p.suffix.lower() in VIDEO_EXT | IMAGE_EXT]
    random.shuffle(files)
    out = []
    for p in files:
        if str(p) in used:
            continue
        used.add(str(p))
        out.append(Background(p, "video" if p.suffix.lower() in VIDEO_EXT else "image"))
        if len(out) >= n:
            break
    while repeat and out and len(out) < n:   # not enough clips: reuse them
        out.append(out[len(out) % max(1, len(files))])
    return out


def gradient(i, theme):
    CACHE.mkdir(exist_ok=True)
    p = CACHE / f"gradient_{i}.jpg"
    palettes = [("#F7C6D0", "#7B4B6A"), ("#FDE2D4", "#B56576"), ("#E8D5F2", "#5E4B8B"), ("#FFE5B4", "#C06C84")]
    a, b = palettes[i % len(palettes)]
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), a)
    top = Image.new("RGB", (W, H), b)
    mask = Image.linear_gradient("L").resize((W, H))
    img = Image.composite(top, img, mask)
    d = ImageDraw.Draw(img)
    rnd = random.Random(i)
    for _ in range(14):
        x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(60, 260)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
    img = Image.blend(Image.composite(top, Image.new("RGB", (W, H), a), mask), img, 0.18).filter(ImageFilter.GaussianBlur(40))
    img.save(p, quality=92)
    return Background(p, "image")


def get_backgrounds(topic, n, cfg):
    source = cfg["video"].get("background_source", "pexels")
    queries = list(topic.get("search") or []) or [cfg["page"].get("niche", "aesthetic")]
    used, out = set(), []

    def fill(fn, label):
        nonlocal out
        for q in queries * 2:
            if len(out) >= n:
                return
            try:
                got = fn(q, n - len(out), used)
                if got:
                    log.info(f"  {label}: {len(got)} for '{q}'")
                out += got
            except Exception as e:
                log.warning(f"  {label} search '{q}' failed: {e.__class__.__name__}: {e}")

    if source in ("my_clips", "mixed"):
        out += my_clips(n, used, repeat=(source == "my_clips"))
    if source in ("pexels", "mixed"):
        if secret("PEXELS_API_KEY"):
            fill(pexels_videos, "Pexels videos")
            fill(pexels_photos, "Pexels photos")
        else:
            log.warning("No PEXELS_API_KEY - using free Creative Commons photos from Openverse instead")
        fill(openverse_photos, "Openverse photos")
    i = 0
    while len(out) < n:
        out.append(gradient(i, cfg["video"].get("theme", {})))
        i += 1
    # spread the clips: if we got fewer unique ones, repeat them
    return out[:n]
