"""BEAUTY mode (content_mode: beauty in config.yaml)  -  the default for @dhruviverse.official.

Makes one 30-40 s makeup reel:
  script (free Gemini writes a new one daily, or the bundled beauty_scripts.yaml)
  -> visuals: video    = one real stock makeup VIDEO clip per step (Pixabay / Pexels), clip first:
                         free Gemini looks at 3 frames of each clip and only keeps a clip that shows what the voice says,
                         otherwise the line is rewritten to describe what the clip shows
     visuals: pictures = one aesthetic AI beauty photo per step (FLUX, faceless-friendly)
  -> language: english  = Indian-English voice (Neerja), captions = exactly the spoken words, word-synced
     language: hinglish = Hindi voice (Swara) reading Devanagari, Roman-Hinglish karaoke captions
  -> small karaoke captions (current word in a purple box), soft music, small handle at the top.
Posts to Instagram (and YouTube once it is connected; a missing YouTube never fails the run).
"""
import json
import os
import random
import re
import time

import requests
import yaml

from .common import OUTPUT, ROOT, log, now_ist, secret
from . import story as S

IMAGE_STYLES = {
    "realistic": ("photorealistic professional beauty photography, soft natural window light, pastel aesthetic, "
                  "editorial magazine look, shallow depth of field, high detail, natural skin texture, elegant, "
                  "clean minimal composition, vertical frame, no text, no letters, no logos, no brand names, no watermark"),
    "3d_cartoon": ("cute 3D cartoon render, Pixar Disney animation style, soft pastel colors, glossy stylized makeup products, "
                   "dreamy soft lighting, clean detailed render, vertical frame, no text, no letters, no logos, no watermark"),
}
DEFAULT_PALETTE = "blush pink, nude beige and soft gold color palette"
CTA_HI = "सेव करो और फ़ॉलो करो ध्रुवीवर्स।"
CTA_EN = "Save this and follow @dhruviverse.official for more."
ENGLISH_VOICE = "en-IN-NeerjaExpressiveNeural"   # warm, natural Indian-English female voice


def speakable(text, s):
    """What the English voice reads: same words as the captions, but the handle said the way people say it."""
    handle = (s.get("channel_name") or "").strip()
    if handle and handle in text:
        text = text.replace(handle, s.get("handle_spoken") or handle.lstrip("@").replace(".", " dot "))
    text = re.sub(r"@([\w.]+)", lambda m: m.group(1).replace(".", " dot "), text)
    return text.replace("₹", "rupees ").replace("&", "and")


def bcfg(cfg):
    """Beauty settings = story engine settings + the beauty: block of config.yaml."""
    s = S.scfg({"story": {}})
    s.update({"language": "english", "visuals": "video", "channel_name": "@dhruviverse.official", "handle_always": True,
              "handle_spoken": "Dhruvi verse dot official",
              "image_style": "realistic", "music_glob": "*", "music_volume": 0.18, "show_title": True,
              "instagram": True, "youtube": True, "youtube_category": "26", "made_for_kids": False,
              "caption_font_size": 60, "handle_font_size": 32, "voice_rate": "+6%",
              "image_providers": ["hf_flux", "cloudflare", "gemini", "gradient"]})
    s.update(cfg.get("beauty") or {})
    s["language"] = str(s.get("language", "english")).strip().lower()
    s["visuals"] = str(s.get("visuals", "video")).strip().lower()
    s["voice_set_by_you"] = bool(s.get("voice"))
    if not s.get("voice"):
        s["voice"] = ENGLISH_VOICE if s["language"] == "english" else "hi-IN-SwaraNeural"
    style = str(s.get("image_style", "realistic")).strip().lower()
    s["art_style"] = s.get("art_style_" + style) or IMAGE_STYLES.get(style, IMAGE_STYLES["realistic"])
    return s


class BeautyPainter(S.Painter):
    def prompt(self, story, scene):
        return f"{scene['image']}, {story.get('palette') or DEFAULT_PALETTE}. {self.s['art_style']}"



# ============================================================================= stock VIDEO clips (visuals: video)
# Real makeup video clips from free Pixabay (and Pexels when a real Pexels key exists), one per scene.
# Each scene has 1-2 search "queries"; a clip is only used when its tags really contain the query words.
# If no good clip exists: generic beauty b-roll queries, and only then an AI picture with slow zoom.
_STOP = {"a", "an", "the", "of", "on", "in", "with", "and", "to", "close", "up", "closeup", "woman", "girl", "her",
         "applying", "putting", "using", "video", "clip", "slow", "motion", "hd"}
_BAD_TAGS = {"horror", "halloween", "zombie", "ghost", "scary", "fear", "blood", "skull", "death", "creepy", "witch",
             "animation", "animated", "cartoon", "3d", "render", "illustration", "pattern", "seamless", "abstract",
             "background", "backdrop", "particles", "loop", "intro", "logo", "text", "letters", "typography", "title",
             "neon", "sign", "goodbye", "bye", "message", "writing", "smoke", "smoking", "cigarette", "vape", "vaping",
             "hookah", "alcohol", "wine", "beer", "drunk", "man", "men", "beard", "boy", "guy", "male", "child", "kid",
             "kids", "baby", "clown", "joker", "drag", "costume", "carnival", "zombies", "sad", "crying", "tears",
             "injury", "wound", "theater", "curtain", "construction", "clock", "car", "dog", "cat", "bikini", "lingerie",
             "underwear", "sexy", "erotic", "naked", "tattoo", "piercing", "masks", "covid", "corona",
             "virus", "pandemic", "doctor", "hospital", "surgery", "botox", "injection", "syringe", "money", "fantasy",
             "fairy", "anime", "manga", "elf", "generated", "ai", "artificial", "castle", "warrior", "princess",
             "goddess", "bird", "lizard", "reptile", "insect", "happy", "greeting", "wishes", "barber", "barbershop"}
_BEAUTY_TAGS = {"makeup", "make", "cosmetics", "cosmetic", "beauty", "lipstick", "lips", "lip", "eye", "eyes",
                "eyelashes", "lashes", "mascara", "eyeshadow", "brush", "powder", "blush", "skincare", "skin", "cream",
                "face", "woman", "girl", "model", "mirror", "glamour", "fashion"}
GENERIC_QUERIES = ["makeup", "cosmetics", "lipstick", "eye makeup", "skincare", "beauty products"]
# Pixabay clips checked by eye (they really show what the word says, no text/logos). Used first for that word.
PRODUCTS = [82076, 25850, 77005, 72007, 257927]
SKIN = [210574, 209634, 293081, 203733]
EYES = [80615, 120048, 322327, 293081, 110763, 34848, 91698, 41073, 251064]
LIPS = [189018, 270065, 351570, 46450, 109470, 306150]
BRIDAL = [365247, 354657, 365252, 44181, 354683, 43699, 354663, 354661, 354660, 47678]
VETTED = {
    "lipstick": LIPS[:5], "applying lipstick": [270065, 189018, 351570, 46450], "lips": [306150, 109470, 43631],
    "lip gloss": [306150], "smiling woman": [43631, 203733, 354657],
    "eye makeup": EYES, "eyeshadow": [322327, 80615, 77005, 251064], "eyelashes": [34848, 91698, 41073, 80615, 110763],
    "mascara": [110763, 34848], "eyebrow": [251064, 80615], "eyebrows": [251064, 80615], "dark circles": [293081, 34848],
    "makeup": [270065, 80615, 306150, 82076, 25850, 110763, 77005, 189018],
    "cosmetics": [25850, 82076, 257927, 72007, 210574], "makeup products": PRODUCTS, "beauty products": PRODUCTS,
    "makeup brush": [25850, 82076, 110763, 77005], "face powder": [25850, 72007], "blush": [72007, 25850],
    "applying foundation": [270065, 25850, 82076], "contour": [270065, 25850, 82076],
    "skincare": SKIN, "glowing skin": SKIN, "face cream": [210574, 209634], "moisturizer": [210574, 209634],
    "woman mirror": [124267, 293081, 210574, 180866], "vanity": [210574, 124267, 25850],
    "rose water": [132131, 55271, 111412], "rose petals": [55271, 111412, 132131], "flowers pink": [132131, 55271],
    "perfume": [257927], "mehendi": BRIDAL[3:], "henna": BRIDAL[3:], "indian bride": BRIDAL, "saree": [365247, 354657],
    "diwali": [105828, 93851, 144735], "festival lights": [105828, 93851, 144735],
}
# Clips seen to be wrong for a beauty page (lollipops, patterns, men, text on mirror, smoke, green screen ...)
BLOCKED = {313716, 317666, 74092, 121546, 153579, 140826, 373881, 346112, 373168, 336348, 44648, 139472, 84319,
           112724, 171493, 126333, 21147, 12720, 216973, 38962, 29916, 25028, 270706,
           39767, 39763, 9477, 212632, 34769, 134643, 186931, 365242, 9685, 23644, 95184, 298042}


def _kw(q):
    return [w for w in re.findall(r"[a-z]+", q.lower()) if w not in _STOP] or re.findall(r"[a-z]+", q.lower())


def _tags(s_):
    return set(re.findall(r"[a-z0-9]+", (s_ or "").lower()))


def _has(tags, word):
    w = word[:5] if len(word) > 5 else word
    return any(t == word or t.startswith(w) for t in tags)


class ClipFinder:
    """Searches the free stock libraries and remembers what was used, so no clip repeats in a reel."""

    def __init__(self, s, seed=0):
        self.s = s
        self.seed = seed
        self.used = set()
        self.cache = {}
        from . import stock
        self.stock = stock
        self.pixabay = stock.pixabay_key()
        self.pexels = secret("PEXELS_REAL_KEY") or secret("PEXELS_KEY2") or stock.pexels_key()
        self.bad = _BAD_TAGS | {t.lower() for t in (s.get("avoid_clip_tags") or [])}

    def _pixabay(self, q):
        r = requests.get("https://pixabay.com/api/videos/", timeout=30,
                         params={"key": self.pixabay, "q": q[:100], "per_page": 100, "safesearch": "true"})
        r.raise_for_status()
        out = []
        for h in r.json().get("hits", []):
            vids = [v for v in (h.get("videos") or {}).values() if v and v.get("url") and v.get("width")]
            if not vids:
                continue
            out.append({"id": f"pxb{h['id']}", "tags": _tags(h.get("tags")), "dur": float(h.get("duration") or 0),
                        "renditions": vids, "credit": f"Pixabay / {h.get('user', '')}", "src": "pixabay"})
        return out

    def _pexels(self, q):
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": self.pexels}, timeout=30,
                         params={"query": q, "orientation": "portrait", "per_page": 30, "size": "medium"})
        r.raise_for_status()
        out = []
        for v in r.json().get("videos", []):
            files = [{"url": f["link"], "width": f["width"], "height": f["height"], "size": 0}
                     for f in v.get("video_files", []) if f.get("width") and f.get("file_type") == "video/mp4"]
            if files:
                # Pexels has no tags: its own ranking for the query is trusted, the URL slug adds words
                out.append({"id": f"pex{v['id']}", "tags": _tags(v.get("url", "").replace("-", " ")) | set(_kw(q)),
                            "dur": float(v.get("duration") or 0), "renditions": files,
                            "credit": f"Pexels / {(v.get('user') or {}).get('name', '')}", "src": "pexels"})
        return out

    def _pixabay_id(self, vid):
        r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={"key": self.pixabay, "id": vid})
        r.raise_for_status()
        out = []
        for h in r.json().get("hits", []):
            vids = [v for v in (h.get("videos") or {}).values() if v and v.get("url") and v.get("width")]
            if vids:
                out.append({"id": f"pxb{h['id']}", "tags": _tags(h.get("tags")), "dur": float(h.get("duration") or 0),
                            "renditions": vids, "credit": f"Pixabay / {h.get('user', '')}", "src": "pixabay",
                            "vetted": True})
        return out

    def candidates(self, q):
        if q in self.cache:
            return self.cache[q]
        out = []
        pinned = re.match(r"^pixabay:(\d+)$", q.strip())
        if pinned or q.strip().lower() in VETTED:
            ids = [int(pinned.group(1))] if pinned else list(VETTED[q.strip().lower()])
            if not pinned:
                random.Random(f"{self.seed}-{q}").shuffle(ids)   # a different order each day
            if self.pixabay:
                for vid in ids:
                    try:
                        out += self._pixabay_id(vid)
                    except Exception as e:
                        log.warning(f"    pixabay clip {vid}: {e.__class__.__name__}")
            if pinned:
                self.cache[q] = out
                return out
        for src, fn in (("pexels", self._pexels if self.pexels else None),
                        ("pixabay", self._pixabay if self.pixabay else None)):
            if not fn:
                continue
            try:
                out += fn(q)
            except Exception as e:
                log.warning(f"    {src} search '{q}' failed: {e.__class__.__name__}: {str(e)[:120]}")
        self.cache[q] = out
        return out

    def score(self, c, q, need):
        tags = c["tags"]
        if c["id"].startswith("pxb") and int(c["id"][3:]) in BLOCKED:
            return None
        if c.get("vetted"):
            return 100 + (1 if c["dur"] >= need else 0)
        if tags & self.bad:
            return None
        words = _kw(q)
        if not all(_has(tags, w) for w in words):
            return None
        best = max(c["renditions"], key=lambda v: v["width"] * v["height"])
        vertical = best["height"] > best["width"]
        sc = 3.0 if vertical else 0.0
        sc += 1.5 if c["dur"] >= need else (0.5 if c["dur"] >= need / 1.5 else -3)
        sc += min(2.0, 0.5 * len(tags & _BEAUTY_TAGS))
        sc += 1.0 if c["src"] == "pexels" else 0
        if min(best["width"], best["height"]) < 720:
            sc -= 3
        return sc

    def ranked(self, queries, need, limit=6):
        """[(candidate, query)] best first, over all queries, no clip twice, nothing used in this reel."""
        out, seen = [], set(self.used)
        for q in queries:
            ranked = []
            for c in self.candidates(q):
                if c["id"] in seen:
                    continue
                sc = self.score(c, q, need) if not q.startswith("pixabay:") else 1000
                if sc is not None:
                    ranked.append((sc, c))
            ranked.sort(key=lambda x: -x[0])
            for sc, c in ranked:
                if c["id"] not in seen:
                    seen.add(c["id"])
                    out.append((c, q))
        return out[:limit]

    def pick(self, queries, need):
        for q in queries:
            ranked = []
            for c in self.candidates(q):
                if c["id"] in self.used:
                    continue
                sc = self.score(c, q, need)
                if sc is not None:
                    ranked.append((sc, c))
            if ranked:
                ranked.sort(key=lambda x: -x[0])
                for sc, c in ranked[:4]:
                    try:
                        path = self.download(c)
                    except Exception as e:
                        log.warning(f"    clip download failed: {e}")
                        continue
                    self.used.add(c["id"])
                    return c, path, q
        return None, None, None

    def download(self, c):
        vids = c["renditions"]
        vertical = max(vids, key=lambda v: v["width"] * v["height"])
        vertical = vertical["height"] > vertical["width"]
        # smallest rendition that still fills a 1080x1920 frame well (landscape clips get centre-cropped)
        need_h = 1600 if vertical else 1440

        def ok(v):
            return (v["height"] >= need_h) and (not v.get("size") or v["size"] < 90_000_000)
        good = sorted([v for v in vids if ok(v)], key=lambda v: v["width"] * v["height"])
        pick = good[0] if good else max([v for v in vids if not v.get("size") or v["size"] < 90_000_000] or vids,
                                        key=lambda v: v["width"] * v["height"])
        return self.stock._dl(pick["url"], ".mp4")


def video_scene_clip(src, secs, fps, out, s):
    """Trim one stock clip to the scene length, fill 9:16 (centre crop), gentle grade. Slow-mo if it is short."""
    dur = S.probe_dur(src) or secs
    speed = 1.0
    if dur < secs + 0.3:
        speed = min(1.6, (secs + 0.3) / max(0.5, dur))
    usable = dur * speed
    start = 0.0 if usable <= secs + 0.6 else min(0.3, (dur - secs / speed) * 0.25)
    loop = ["-stream_loop", "-1"] if usable < secs else []
    vf = (f"setpts={speed:.3f}*PTS,scale={S.W}:{S.H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={S.W}:{S.H},fps={fps},eq=saturation={float(s.get('clip_saturation', 1.06))}:contrast=1.03,"
          f"unsharp=5:5:0.4,format=yuv420p")
    S.ff(loop + ["-ss", f"{start:.2f}", "-i", src, "-t", f"{secs:.3f}", "-an", "-vf", vf,
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", out])
    return out



# ----------------------------------------------------------------------------- clip check with free Gemini (vision)
def _gemini_call(model, body, key, timeout=60):
    base = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
    tok = os.environ.get("GEMINI_PROXY_TOKEN")
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    params = {} if tok else {"key": key}
    return requests.post(f"{base}/v1beta/models/{model}:generateContent", params=params, headers=headers,
                         json=body, timeout=timeout)


def gemini_vision_models(key):
    base = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
    tok = os.environ.get("GEMINI_PROXY_TOKEN")
    try:
        r = requests.get(f"{base}/v1beta/models", params={"pageSize": 300} if tok else {"key": key, "pageSize": 300},
                         headers={"Authorization": f"Bearer {tok}"} if tok else {}, timeout=30)
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception:
        names = []
    ok = [n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-flash(-lite)?", n)]
    # lite models first: they have the biggest free daily quota, and "is this lipstick?" is an easy question
    ok.sort(key=lambda n: (("lite" not in n), -float(re.findall(r"\d+(?:\.\d+)?", n)[0])))
    return ok + ["gemini-flash-lite-latest", "gemini-flash-latest"]


CHECK_SCHEMA = {"type": "OBJECT", "properties": {
    "matches": {"type": "BOOLEAN"}, "shows": {"type": "STRING"}, "rewrite": {"type": "STRING"}},
    "required": ["matches", "shows", "rewrite"]}


class ClipChecker:
    """Asks free Gemini: do these 3 frames of the clip really SHOW what the voice says?"""

    def __init__(self, s):
        self.key = secret("GEMINI_API_KEY") if s.get("check_clips_with_gemini", True) else None
        self.left = int(s.get("max_clip_checks", 14))
        self.models = None
        self.last = 0.0

    def ok(self):
        return bool(self.key) and self.left > 0

    def frames(self, path):
        import base64
        import subprocess
        import tempfile
        dur = S.probe_dur(path) or 6
        with tempfile.TemporaryDirectory() as td:
            outs = []
            for j, f in enumerate((0.2, 0.5, 0.8)):
                o = f"{td}/f{j}.jpg"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * f:.2f}", "-i", str(path), "-frames:v", "1",
                                "-vf", "scale=-2:420", o], timeout=60)
                outs.append(o)
            from PIL import Image
            ims = [Image.open(o).convert("RGB") for o in outs if os.path.exists(o)]
            if not ims:
                return None
            sheet = Image.new("RGB", (sum(i.width for i in ims) + 8 * (len(ims) - 1), 420), "white")
            x = 0
            for im in ims:
                sheet.paste(im, (x, 0))
                x += im.width + 8
            buf = f"{td}/sheet.jpg"
            sheet.save(buf, quality=80)
            return base64.b64encode(open(buf, "rb").read()).decode()

    def check(self, path, line, is_last):
        """-> (matches, shows, rewrite) or None when Gemini is not available."""
        if not self.ok():
            return None
        img = self.frames(path)
        if not img:
            return None
        if self.models is None:
            self.models = gemini_vision_models(self.key)
        keep = (f' The line must still end exactly with "{CTA_EN}".' if is_last else "")
        prompt = (f'These are 3 frames (start, middle, end) from ONE short stock video clip for a makeup reel. '
                  f'The voiceover during this clip says: "{line}"\n'
                  f'matches = true ONLY if the frames clearly show the same product AND action the line talks about '
                  f'(for example the line says applying lipstick and the frames show lipstick being applied). '
                  f'A different product, a different body part, or just a pretty face = false.\n'
                  f'shows = what the clip actually shows, in max 12 words.\n'
                  f'rewrite = the voiceover line rewritten so it describes exactly what the frames show, while still being '
                  f'a correct, safe, useful makeup tip on the same topic. Keep the same step word at the start '
                  f'(First, Second, Third, Fourth, Step one ...) if the line has one. Simple spoken English for Indian girls, '
                  f'9 to 17 words, no digits, no hyphens, no emojis, no brand names.{keep}')
        body = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": img}}]}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                     "responseSchema": CHECK_SCHEMA}}
        for model in list(self.models):
            wait = 4.5 - (time.time() - self.last)   # stay under the free per-minute limit
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                r = _gemini_call(model, body, self.key)
                if r.status_code != 200:
                    log.info(f"      Gemini {model}: HTTP {r.status_code}")
                    if r.status_code in (400, 403, 404, 429):
                        self.models.remove(model)   # not for this key / used up today -> next model
                    continue
                d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                self.left -= 1
                return bool(d.get("matches")), str(d.get("shows", ""))[:120], str(d.get("rewrite", "")).strip()
            except Exception as e:
                log.info(f"      Gemini {model} check failed: {str(e)[:100]}")
        self.key = None   # nothing works today -> stop asking
        return None


def clean_line(text, is_last):
    t = re.sub(r"\s+", " ", (text or "").replace("-", " ").replace("&", "and").replace("/", " or ")).strip()
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t).strip()
    if is_last and not t.endswith(CTA_EN):
        t = t.rstrip(" .") + ". " + CTA_EN
    return t


class ClipPainter(BeautyPainter):
    """visuals: video -> one real stock clip per scene that SHOWS what the voice says.
    Clip-first: candidates are found per scene, free Gemini looks at 3 frames of each and says yes/no;
    if no clip matches, the line is rewritten to describe what the best clip really shows (voice + captions follow)."""

    picks = None

    def prepare(self, story):
        finder = ClipFinder(self.s, story.get("seed", 0))
        checker = ClipChecker(self.s)
        self.finder, self.picks, self.clip_log = finder, [], []
        if not (finder.pixabay or finder.pexels):
            log.warning("    No PEXELS_API_KEY / PIXABAY_API_KEY secret - using AI pictures instead of video clips")
            self.picks = [None] * len(story["scenes"])
            return story
        generic = list(self.s.get("generic_queries") or GENERIC_QUERIES)
        per_scene = int(self.s.get("clips_checked_per_scene", 3))
        n = len(story["scenes"])
        for i, sc in enumerate(story["scenes"]):
            is_last = i == n - 1
            need = len(sc["narration"].split()) / 2.6 + 0.9
            own = [q for q in (sc.get("queries") or []) if q]
            pinned = all(q.startswith("pixabay:") for q in own[:1]) and own
            cands = finder.ranked(own, need) or finder.ranked(generic, need)
            chosen, best, tried = None, None, 0
            for c, q in cands:
                try:
                    path = finder.download(c)
                except Exception as e:
                    log.warning(f"    clip download failed: {e}")
                    continue
                if pinned and q.startswith("pixabay:") or c.get("vetted") and not checker.ok():
                    chosen = (c, path, q, "picked by hand" if q.startswith("pixabay:") else "vetted")
                    break
                res = checker.check(path, sc["caption"], is_last) if english_story(story) else None
                if res is None:   # no Gemini today: trust the tags
                    chosen = (c, path, q, "tags")
                    break
                tried += 1
                ok, shows, rewrite = res
                log.info(f"      {c['id']} '{q}': {'YES' if ok else 'no'} - shows {shows}")
                if ok:
                    chosen = (c, path, q, f"Gemini yes: {shows}")
                    break
                if i == 0:   # the hook is a question/claim, not an action: never rewrite it, keep the best clip
                    chosen = (c, path, q, f"hook, best clip: {shows}")
                    break
                if best is None:
                    best = (c, path, q, shows, rewrite)
                if tried >= per_scene:
                    break
            if not chosen and best:
                c, path, q, shows, rewrite = best
                new = clean_line(rewrite, is_last)
                if 6 <= len(new.split()) <= 30:
                    log.info(f"    scene {i + 1}: no clip shows it -> line rewritten to match the clip ({shows})")
                    log.info(f"      old: {sc['caption']}")
                    log.info(f"      new: {new}")
                    sc["caption"], sc["narration"] = new, speakable(new, self.s)
                    sc["rewritten"] = True
                chosen = (c, path, q, f"rewritten to match: {shows}")
            if chosen:
                c, path, q, why = chosen
                finder.used.add(c["id"])
                log.info(f"    scene {i + 1}: clip {c['id']} for '{q}' ({why}; {c['credit']})")
                self.picks.append(path)
                self.clip_log.append({"scene": i + 1, "clip": c["id"], "query": q, "why": why, "credit": c["credit"]})
            else:
                log.info(f"    scene {i + 1}: no fitting clip - AI picture")
                self.picks.append(None)
                self.clip_log.append({"scene": i + 1, "clip": None})
        return story

    def scene_clips(self, story, secs_list, fps, workdir):
        if self.picks is None:
            self.prepare(story)
        jobs = []
        for i, sc in enumerate(story["scenes"]):
            src = self.picks[i]
            jobs.append(("video", src) if src else ("image", self.paint(story, i, sc)))
        with S.ThreadPoolExecutor(max_workers=3) as ex:
            futs = []
            for i, (kind, src) in enumerate(jobs):
                out = workdir / f"clip_{i:02d}.mp4"
                if kind == "video":
                    futs.append(ex.submit(video_scene_clip, src, secs_list[i], fps, out, self.s))
                else:
                    futs.append(ex.submit(S.scene_clip, src, secs_list[i], fps, S.MOVES[i % len(S.MOVES)], out))
            return [f.result() for f in futs]


def english_story(story):
    return story.get("language") == "english"

# ----------------------------------------------------------------------------- scripts
def load_scripts():
    p = ROOT / "beauty_scripts.yaml"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _to_story(sc, lang, source, seed, s=None):
    s = s or {}
    scenes = []
    english = lang == "english" and all(x.get("en") for x in sc["scenes"])
    if lang == "english" and not english:
        lang = "hinglish"   # this script has no English words yet -> Hinglish voice
    for x in sc["scenes"]:
        hi, rom = x.get("hi") or x.get("hinglish"), x.get("hinglish") or x.get("hi")
        if english:
            spoken, caption = speakable(x["en"], s), x["en"]
        else:
            spoken, caption = {"hinglish": (hi, rom), "hindi": (hi, hi)}.get(lang, (rom, rom))
        scenes.append({"narration": spoken, "caption": caption, "image": x.get("image") or x.get("en") or "",
                       "queries": list(x.get("queries") or [])})
    hook = (sc.get("hook_en") if english else None) or sc.get("hook") or sc["title"]
    caption_text = (sc.get("caption_en") if english else None) or sc.get("caption", "")
    return {"id": f"beauty-{sc['id']}", "title": hook, "title_en": sc["title"], "language": "english" if english else lang,
            "palette": sc.get("palette") or DEFAULT_PALETTE, "scenes": scenes, "character": "",
            "caption": caption_text, "hashtags": sc.get("hashtags", []), "source": source, "seed": seed}


def bundled_script(scripts, posted, lang, want_id=None, s=None):
    if not scripts:
        raise RuntimeError("beauty_scripts.yaml is missing or empty")
    done = {str(p.get("topic_id")) for p in posted.get("posts", []) if p.get("success")}
    if want_id is not None:
        pick = [x for x in scripts if str(x["id"]) == str(want_id).replace("beauty-", "")]
        if not pick:
            raise RuntimeError(f"No script with id {want_id} in beauty_scripts.yaml")
        sc = pick[0]
    else:
        left = [x for x in scripts if f"beauty-{x['id']}" not in done]
        sc = left[0] if left else scripts[len(done) % len(scripts)]
    return _to_story(sc, lang, "beauty_scripts.yaml", 5000 + int(sc["id"]) * 11, s)


SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"}, "hook": {"type": "STRING"}, "palette": {"type": "STRING"},
        "scenes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "image": {"type": "STRING"}, "hi": {"type": "STRING"}, "hinglish": {"type": "STRING"}},
            "required": ["image", "hi", "hinglish"]}},
        "caption": {"type": "STRING"}, "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "hook", "palette", "scenes", "caption", "hashtags"],
}


SCHEMA_EN = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"}, "hook_en": {"type": "STRING"}, "palette": {"type": "STRING"},
        "scenes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "en": {"type": "STRING"}, "queries": {"type": "ARRAY", "items": {"type": "STRING"}},
            "image": {"type": "STRING"}},
            "required": ["en", "queries", "image"]}},
        "caption_en": {"type": "STRING"}, "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["title", "hook_en", "palette", "scenes", "caption_en", "hashtags"],
}
QUERY_WORDS = ["lipstick", "applying lipstick", "lips", "lip gloss", "eye makeup", "eyelashes", "eyeshadow", "mascara",
               "blush", "makeup", "cosmetics", "makeup brush", "face powder", "applying foundation", "skincare",
               "moisturizer", "face cream", "glowing skin", "woman mirror", "smiling woman", "rose water", "hairstyle",
               "perfume", "henna", "mehendi", "diwali", "indian bride", "vanity", "selfie", "beauty products"]


def gemini_prompt_en(s, recent, scripts):
    ex = next((x for x in scripts if all(sc.get("en") for sc in x.get("scenes", []))), None)
    example = json.dumps({"title": ex["title"], "hook_en": ex.get("hook_en"), "palette": ex.get("palette"),
                          "scenes": [{"en": sc["en"], "queries": [q for q in sc.get("queries", []) if ":" not in q],
                                      "image": sc.get("image", "")} for sc in ex["scenes"]],
                          "caption_en": ex.get("caption_en"), "hashtags": ex.get("hashtags")},
                         ensure_ascii=False) if ex else ""
    return f"""You write daily 30-40 second ENGLISH makeup reels for the faceless Indian beauty Instagram page {s['channel_name']}
(audience: Indian girls and women 16-35, budget-conscious). Pick ONE fresh topic from: affordable makeup tips, makeup hacks,
kajal/eyeliner, lipstick, blush, base/foundation/concealer, skincare before makeup, budget dupes (no brand names), 5-minute GRWM
looks, festive or wedding-guest looks, common makeup mistakes. Do NOT repeat these recent topics: {json.dumps(recent, ensure_ascii=False)}.
Rules:
- exactly 6 scenes: scene 1 = hook (question or bold claim), scenes 2-5 = four practical, correct, safe tips/steps
  (First, / Second, / Third, / Fourth, ...), scene 6 = short payoff and then exactly: "{CTA_EN}"
- en: simple, warm spoken English for Indian girls, short sentences. It is read aloud by a voice AND shown word by word as
  captions, so: no digits (write numbers as words), no emojis, no hyphens, no "&", no "/", no brackets, no brand names.
  Whole script 70-90 words in total, each scene 9-17 words.
- queries: 2 short search words per scene for a free stock VIDEO library, the clip must visibly show what the sentence says.
  Use ONLY words from this list: {json.dumps(QUERY_WORDS)}
- image: one line describing a faceless-friendly real photo (backup only): product close-up, one hand applying, mirror,
  side profile. No text, no logos.
- palette: e.g. "blush pink, nude beige and soft gold color palette".
- hook_en: max 6 words (shown on screen). title: short English title.
- caption_en: 3-6 short English lines with emojis listing the tips, ending with a save/follow line. hashtags: 6-10, include #dhruviverse.
Example of the exact format: {example}"""


def gemini_script(s, posted, scripts):
    key = secret("GEMINI_API_KEY")
    if not key or not s.get("use_gemini_script", True):
        return None
    recent = [p.get("hook") for p in posted.get("posts", [])[-40:] if p.get("hook")]
    examples = json.dumps(scripts[:1], ensure_ascii=False) if scripts else ""
    prompt = f"""You write daily 30-40 second Hinglish makeup reels for the faceless Indian beauty Instagram page @dhruviverse.official
(audience: Indian girls and women 16-35, budget-conscious). Pick ONE fresh topic from: affordable makeup tips, makeup hacks,
kajal/eyeliner, lipstick, blush, base/foundation/concealer, skincare before makeup, budget dupes (no brand names), 5-minute GRWM
looks, festive or wedding-guest looks, common makeup mistakes. Do NOT repeat these recent topics: {json.dumps(recent, ensure_ascii=False)}.
Rules:
- exactly 6 scenes: scene 1 = hook (question or bold claim), scenes 2-5 = four practical, correct, safe tips/steps,
  scene 6 = short payoff and the CTA, ending exactly with "{CTA_HI}" (hi) and "Save karo aur follow karo @dhruviverse.official" (hinglish).
- whole script 65-80 Hindi words in total, each scene 9-15 words.
- hi: natural spoken Hindi in Devanagari, English beauty words written in Devanagari (लिपस्टिक, कॉम्पैक्ट), numbers as words,
  no digits, no emojis. It is read aloud by a Hindi voice.
- hinglish: the SAME sentence in Roman Hindi with EXACTLY the same number of words as hi (word-for-word, used as karaoke captions).
- image: one line describing a real photograph for an AI image model, faceless-friendly: product close-ups, flat-lays, ONE hand
  holding or applying a product, vanity/mirror shots, side profile or eye/lip extreme close-up with the face partly out of frame.
  Never a full frontal face. No text, labels, brand names or logos (say "plain unlabeled").
- palette: e.g. "blush pink, nude beige and soft gold color palette" (one palette for the whole reel).
- hook: max 6 words, Roman Hinglish (shown on screen). title: short English title.
- caption: 3-6 short Hinglish lines with emojis listing the tips, ending with a save/follow line. hashtags: 6-10, include #dhruviverse.
No brand names anywhere. Example of the exact format: {examples}"""
    english = s["language"] == "english"
    if english:
        prompt = gemini_prompt_en(s, recent, scripts)
    found = S.gemini_text_models(key) if not os.environ.get("GEMINI_PROXY_TOKEN") else \
        sorted(gemini_vision_models(key)[:-2], key=lambda n: "lite" in n)
    models = [s.get("gemini_model", "gemini-3.8-flash")] + found + ["gemini-flash-latest"]
    for model in dict.fromkeys(models):
        try:
            body = {"contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json",
                                         "responseSchema": SCHEMA_EN if english else SCHEMA}}
            r = _gemini_call(model, body, key, timeout=90)
            if r.status_code != 200:
                log.warning(f"    Gemini {model}: HTTP {r.status_code} {r.text[:120]}")
                continue
            data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            sc = data["scenes"]
            need = ("en", "queries") if english else ("hi", "hinglish", "image")
            if not 4 <= len(sc) <= 8 or any(not all(x.get(f) for f in need) for x in sc):
                raise ValueError("script came back incomplete")
            if english:
                for x in sc:  # keep captions clean: the voice and the captions use these exact words
                    x["en"] = re.sub(r"\s+", " ", x["en"].replace("-", " ").replace("&", "and")).strip()
                    x["queries"] = [q for q in x["queries"] if isinstance(q, str) and q.strip()][:3]
                if not sc[-1]["en"].rstrip().endswith(CTA_EN):
                    sc[-1]["en"] = sc[-1]["en"].rstrip() + " " + CTA_EN
            n_words = sum(len((x["en"] if english else x["hi"]).split()) for x in sc)
            if not 45 <= n_words <= 120:
                raise ValueError(f"script length {n_words} words is off")
            data["id"] = "ai-" + now_ist().strftime("%Y%m%d")
            st = _to_story(data, s["language"], f"Gemini {model}", int(now_ist().strftime("%j")) * 13 + 77, s)
            log.info(f"    Gemini ({model}) wrote today's script: {data.get('title')}")
            return st
        except Exception as e:
            log.warning(f"    Gemini {model} failed: {str(e)[:150]}")
    log.warning("    Gemini could not write a script today - using the bundled beauty_scripts.yaml")
    return None


def beauty_captions(st, s):
    tags = list(dict.fromkeys((st.get("hashtags") or []) + ["#makeuptips", "#beautytips", "#affordablemakeup",
                                                              "#indianmakeup", "#makeupreels", "#dhruviverse"]))[:14]
    tags = [t if t.startswith("#") else "#" + t.replace(" ", "") for t in tags]
    save_line = "Save this for later" if st.get("language") == "english" else "Save karo for later"
    ig = (st.get("caption") or f"{st['title']} ✨\n{save_line} 💾 Follow {s['channel_name']} 💕").strip()
    ig += "\n\n" + " ".join(tags)
    lang_word = {"english": "Makeup Tips", "hindi": "Hindi Makeup Tips"}.get(st.get("language"), "Hinglish Makeup Tips")
    yt_title = f"{st['title_en']} | {lang_word} #shorts"
    if len(yt_title) > 95:
        yt_title = yt_title[:92] + "..."
    yt_desc = (st.get("caption") or st["title"]) + f"\n\nDaily affordable beauty tips: {s['channel_name']}\n" + " ".join(tags)
    yt_tags = [t.lstrip("#") for t in tags] + ["makeup tips", "makeup hacks", "affordable makeup", "indian makeup"]
    return {"youtube_title": yt_title, "youtube_description": yt_desc, "youtube_tags": yt_tags[:20], "instagram_caption": ig}


# ----------------------------------------------------------------------------- posting
def post_everywhere(out, caps, s, cfg, record, stamp):
    """Instagram first. YouTube is a bonus: if its secrets are missing it is skipped, and a YouTube error
    never fails the run when Instagram worked."""
    p = cfg.get("posting", {})
    ig_on, yt_on = bool(s.get("instagram", True)), bool(s.get("youtube", True))
    if ig_on:
        try:
            from .instagram import Instagram
            record["instagram"] = Instagram().publish_reel(out, caps["instagram_caption"], p.get("share_to_feed", True),
                                                           p.get("video_host", "auto"), f"beauty-{stamp}")
        except Exception as e:
            log.error(f"Instagram FAILED: {e}")
            record["errors"].append(f"instagram: {e}")
    if yt_on:
        if not all(secret(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
            log.info("YouTube: skipped (not connected yet - add YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN secrets)")
            record["youtube"] = "skipped"
        else:
            try:
                from .youtube import upload_short
                record["youtube"] = upload_short(out, caps["youtube_title"], caps["youtube_description"],
                                                 caps["youtube_tags"], p.get("youtube_privacy", "public"),
                                                 s.get("youtube_category", "26"))
            except Exception as e:
                log.warning(f"YouTube failed (Instagram is not affected): {e}")
                record["errors"].append(f"youtube: {e}")
    if ig_on:
        record["success"] = bool(record["instagram"])
    else:
        record["success"] = bool(record["youtube"]) and record["youtube"] != "skipped"
    return record


# ----------------------------------------------------------------------------- the daily run
def run_beauty(args, cfg, posted, save_posted):
    s = bcfg(cfg)
    scripts = load_scripts()
    st = gemini_script(s, posted, scripts) if args.topic is None else None
    if st is None:
        st = bundled_script(scripts, posted, s["language"], args.topic, s)
    if not s.get("voice_set_by_you"):
        s["voice"] = ENGLISH_VOICE if st["language"] == "english" else "hi-IN-SwaraNeural"
    log.info(f"Today's beauty reel: {st['title']} ({st['source']}, {len(st['scenes'])} scenes, "
             f"{st['language']}, {'video clips' if s['visuals'] == 'video' else s['image_style'] + ' pictures'})")
    stamp = now_ist().strftime("%Y-%m-%d")
    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / f"beauty-{stamp}-{st['id']}.mp4"
    painter = (ClipPainter if s["visuals"] == "video" else BeautyPainter)(s, OUTPUT / "work")
    if isinstance(painter, ClipPainter):
        log.info("Finding a real video clip for every step (clip first)")
        painter.prepare(st)
    S.build_story_reel(st, cfg, OUTPUT / "work", out, s=s, painter=painter)
    st["clips"] = getattr(painter, "clip_log", None)
    caps = beauty_captions(st, s)
    (OUTPUT / "caption.txt").write_text(caps["instagram_caption"], encoding="utf-8")
    (OUTPUT / "youtube.json").write_text(json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT / "script.json").write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.no_post:
        log.info(f"--no-post: video is at {out}")
        return 0
    record = {"topic_id": st["id"], "type": "beauty", "hook": st["title"],
              "date": now_ist().isoformat(timespec="minutes"), "instagram": None, "youtube": None, "errors": []}
    post_everywhere(out, caps, s, cfg, record, stamp)
    posted["posts"].append(record)
    save_posted(posted)
    if not record["success"]:
        log.error("Instagram did not post today. The video is saved in the run's 'reel' download (Artifacts).")
        return 1
    log.info("Done! Posted to Instagram" + (" and YouTube." if record["youtube"] not in (None, "skipped") else "."))
    return 0
