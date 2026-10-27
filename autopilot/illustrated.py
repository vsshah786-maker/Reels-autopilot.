"""ILLUSTRATED mode (content_mode: illustrated in config.yaml)  -  the default for @dhruviverse.official.

One 7-10 s reel a day in the style of the big desi quote pages:
  * ONE illustrated artwork as the background (soft digital illustration / pencil sketch + watercolor,
    Indian girl, muted pastel palette) - made fresh every day by free FLUX on Hugging Face (your HF_TOKEN),
    then Pollinations, then the bundled pictures in assets/illustrated/
  * a short viral, relatable line in the TOP third in a bold rounded font (Baloo 2 / Baloo Bhai 2),
    1-2 key words in orange or yellow (*word* in the line = accent colour)
  * language rotates every day: English -> Hinglish -> Hindi -> Gujarati (config: illustrated: languages)
  * slow Ken-Burns zoom on the art, lines fade up one by one, the accent word pops in a beat later,
    soft floating dust, small @handle at the bottom, copyright-free music from assets/music, no voice.
Free Gemini (GEMINI_API_KEY) writes a fresh line daily in the day's language (falls back to quotes_multi.yaml)
and looks at the artwork: pictures with text/letters or broken faces/hands are thrown away and re-made.
"""
import base64
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import time
import urllib.parse

import numpy as np
import requests
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .common import ASSETS, OUTPUT, ROOT, log, now_ist, secret

W, H = 1080, 1920
FONTS = ASSETS / "fonts"
LANGS = ["en", "hinglish", "hi", "gu"]
LANG_NAME = {"en": "English", "hinglish": "Hinglish (Hindi + English written in Roman/English letters)",
             "hi": "Hindi (Devanagari script)", "gu": "Gujarati (Gujarati script; common English words like "
             "attitude, smile, friends may stay in English letters or Gujarati script, like Gujarati Instagram pages)"}
CATEGORIES = ["emotional", "attitude", "funny", "emotional", "friendship", "relationship", "emotional", "self_love", "confidence"]
MOODS = ["playful", "sassy", "warm", "dreamy", "confident", "emotional"]
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d\u2B50\u2B55\u231A-\u23FF]+")

DEFAULTS = {
    "channel_name": "@dhruviverse.official",
    "languages": LANGS,            # rotation order, one per day
    "language": "auto",            # auto = rotate daily; or force one of: en, hinglish, hi, gu
    "use_gemini_line": True,
    "check_art_with_gemini": True,
    "art_providers": ["hf_router", "hf_space", "pollinations", "bundled"],
    "hf_model": "black-forest-labs/FLUX.1-schnell",
    "hf_spaces": ["black-forest-labs-flux-1-schnell"],
    "pollinations_model": "flux",
    "art_style": ("soft digital illustration, pencil sketch lines with watercolor wash, painterly, muted pastel palette, "
                  "gentle film grain, aesthetic Instagram quote reel background"),
    "art_layout": ("calm plain empty area in the upper third (soft sky or plain wall), subject in the lower two thirds, "
                   "no text, no letters, no words, no watermark, no signature"),
    "seconds": 9.0, "fps": 30, "music_volume": 0.6, "particles": True,
    "accent_orange": "#FF7A1A", "accent_yellow": "#FFD23F",
    "hashtags_common": ["#dhruviverse", "#relatable", "#desigirl", "#quotes", "#reelsindia"],
    "follow_line": "Follow @dhruviverse.official for daily vibes ✨",
    "music_by_mood": {"playful": "lofi-blush", "sassy": "lofi-blush", "warm": "soft-glow", "dreamy": "soft-glow",
                      "confident": "morning-light", "emotional": "soft-glow"},
}


def icfg(cfg):
    s = dict(DEFAULTS)
    s.update((cfg.get("illustrated") or {}))
    return s


# ----------------------------------------------------------------------------- lines
def load_lines():
    p = ROOT / "quotes_multi.yaml"
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data


def language_for(day, s):
    want = str(s.get("language", "auto")).strip().lower()
    order = [l for l in (s.get("languages") or LANGS) if l in LANGS] or LANGS
    if want in LANGS:
        return want
    return order[day.toordinal() % len(order)]


def plain(text):
    return re.sub(r"\s+", " ", text.replace("*", "").replace("\\n", " ").replace("\n", " ")).strip()


def _done(posted):
    return {str(p.get("topic_id")) for p in posted.get("posts", []) if p.get("success")}


def bundled_line(lines, lang, posted, want_id=None):
    if want_id is not None:
        pick = [x for x in lines if str(x["id"]) == str(want_id).replace("line-", "")]
        if not pick:
            raise RuntimeError(f"No line with id {want_id} in quotes_multi.yaml")
        x = dict(pick[0])
    else:
        pool = [x for x in lines if x.get("lang") == lang] or lines
        done = _done(posted)
        recent = {plain(p.get("hook") or "")[:40].lower() for p in posted.get("posts", [])}
        left = [x for x in pool if f"line-{x['id']}" not in done and plain(x["text"])[:40].lower() not in recent]
        n = sum(1 for d in done if d.startswith("line-"))
        x = dict(left[0] if left else pool[n % len(pool)])
    x["id"] = f"line-{x['id']}"
    x["source"] = "quotes_multi.yaml"
    return x


SCHEMA = {"type": "OBJECT", "properties": {
    "text": {"type": "STRING"},
    "category": {"type": "STRING", "enum": sorted(set(CATEGORIES))},
    "meaning_en": {"type": "STRING"},
    "scene": {"type": "STRING"},
    "mood": {"type": "STRING", "enum": MOODS},
    "hook": {"type": "STRING"},
    "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["text", "category", "meaning_en", "scene", "mood", "hook", "hashtags"]}


def gemini_models(key):
    from . import beauty as B
    try:
        from . import story as S
        found = S.gemini_text_models(key)
    except Exception:
        found = []
    return list(dict.fromkeys(found + B.gemini_vision_models(key)))


def gemini_line(s, lang, posted, lines):
    key = secret("GEMINI_API_KEY")
    if not key or not s.get("use_gemini_line", True):
        return None
    from . import beauty as B
    day = now_ist()
    cat = CATEGORIES[day.toordinal() // 4 % len(CATEGORIES)]
    recent = [plain(p.get("hook") or "") for p in posted.get("posts", [])[-90:] if p.get("hook")]
    ex = [{k: x[k] for k in ("text", "category", "meaning_en", "scene", "mood", "hook", "hashtags") if k in x}
          for x in lines if x.get("lang") == lang]
    random.Random(day.toordinal()).shuffle(ex)
    prompt = f"""You write lines for {s['channel_name']}, a viral Indian Instagram quote page (girls and women 16-35),
like the big Gujarati/Hindi/Hinglish attitude-quote pages. Write ONE new ORIGINAL line in {LANG_NAME[lang]}.
Category today: {cat} (emotional = heart-touching lines people deeply feel: mom, papa, home, growing up, hostel life,
loneliness, true friends, self-worth - the kind people save and share; attitude = sassy confident; funny = relatable
desi humor; friendship = makes people tag their best friend; relationship = cute/savage love lines;
self_love / confidence = bold and warm).
Rules: 5-18 words, 1-3 short lines (use "\\n" for line breaks). Must feel real and conversational, the way people
actually talk and write on Instagram - natural spelling, nothing bookish, nothing translated word-for-word.
It must make people comment, tag a friend, save or share. Not a famous quote, not song lyrics, no author, no emojis,
no hashtags in text. Mark the 1 or 2 most important words with *asterisks* (they get an orange colour), e.g. *attitude*.
meaning_en = English meaning. scene = the illustration behind it, one sentence: usually a young Indian girl/woman
(back view, side view or face partly turned away; outfit, place, light, colours) or friends together, matching the
line's feeling; soft muted colours. hook = one short engaging caption line with 1 emoji (tag a friend / comment).
hashtags = 8 relevant ones, mix English + regional (e.g. #gujaratiquotes #hindiquotes #desigirl #attitude).
Do NOT repeat or closely copy any of these: {json.dumps(recent + [plain(x['text']) for x in lines][:120], ensure_ascii=False)}
Examples of the tone and format: {json.dumps(ex[:5], ensure_ascii=False)}"""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json", "responseSchema": SCHEMA}}
    models = list(dict.fromkeys(([s["gemini_model"]] if s.get("gemini_model") else []) + gemini_models(key)))[:8]
    for model in models + models[:2]:         # a second try on the first two after a short pause (rate limits)
        try:
            r = B._gemini_call(model, body, key, timeout=60)
            if r.status_code == 429 and model in models[:2]:
                time.sleep(12)
            if r.status_code != 200:
                log.info(f"    Gemini {model}: HTTP {r.status_code}")
                continue
            d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            d["text"] = EMOJI.sub("", d["text"].replace("\\n", "\n")).strip().strip('"')
            n = len(plain(d["text"]).split())
            if not 3 <= n <= 24:
                raise ValueError(f"{n} words")
            script_ok = {"hi": r"[\u0900-\u097F]", "gu": r"[\u0A80-\u0AFF]"}.get(lang)
            if script_ok and not re.search(script_ok, d["text"]):
                raise ValueError("wrong script")
            if lang in ("en", "hinglish") and re.search(r"[\u0900-\u0AFF]", d["text"]):
                raise ValueError("wrong script")
            if any(plain(d["text"]).lower()[:35] == t.lower()[:35] for t in recent):
                raise ValueError("repeat")
            if d["text"].count("*") < 2 or d["text"].count("*") % 2:
                d["text"] = d["text"].replace("*", "")
                words = plain(d["text"]).split()
                longest = max(words, key=len)
                d["text"] = d["text"].replace(longest, f"*{longest}*", 1)
            d.update({"lang": lang, "id": "line-ai-" + day.strftime("%Y%m%d"), "source": f"Gemini {model}"})
            log.info(f"    Gemini ({model}) wrote today's line")
            return d
        except Exception as e:
            log.info(f"    Gemini {model} failed: {str(e)[:120]}")
    log.warning("    Gemini could not write a line today - using quotes_multi.yaml")
    return None


# ----------------------------------------------------------------------------- art
def _img(b):
    return Image.open(io.BytesIO(b)).convert("RGB")


class Artist:
    """Makes the background illustration: free FLUX on Hugging Face -> Pollinations -> bundled pictures."""

    def __init__(self, s, seed):
        self.s, self.seed = s, seed
        self.dead = set()
        self.used = None

    def prompt(self, line):
        return f"{line.get('scene') or 'young Indian girl, back view, cozy aesthetic scene'}, {self.s['art_style']}, {self.s['art_layout']}"

    def make(self, line, attempt=0):
        p = self.prompt(line)
        seed = self.seed + attempt * 7919
        for prov in self.s["art_providers"]:
            if prov in self.dead:
                continue
            t0 = time.time()
            try:
                img = getattr(self, "_" + prov)(p, seed, line)
            except Exception as e:
                log.warning(f"    art: {prov} failed ({e.__class__.__name__}: {str(e)[:160]})")
                img = None
            if img is not None:
                log.info(f"    art: {prov} in {time.time() - t0:.0f}s ({img.size[0]}x{img.size[1]})")
                self.used = prov
                return img, prov
        raise RuntimeError("no artwork could be made")

    # 1. Hugging Face Inference (router) with the free HF_TOKEN
    def _hf_router(self, prompt, seed, line):
        tok = secret("HF_TOKEN")
        if not tok:
            self.dead.add("hf_router")
            return None
        url = f"https://router.huggingface.co/hf-inference/models/{self.s['hf_model']}"
        body = {"inputs": prompt, "parameters": {"width": 768, "height": 1344, "num_inference_steps": 4, "seed": seed}}
        for attempt in range(3):
            r = requests.post(url, headers={"Authorization": f"Bearer {tok}", "Accept": "image/png"}, json=body, timeout=120)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                return _img(r.content)
            if r.status_code in (401, 402, 403, 404):
                self.dead.add("hf_router")
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
            time.sleep(8 * (attempt + 1))   # 503 = model loading
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")

    # 2. the free public FLUX demo Space on Hugging Face (HF_TOKEN gives a bigger daily quota)
    def _hf_space(self, prompt, seed, line):
        tok = secret("HF_TOKEN")
        headers = {"Authorization": f"Bearer {tok}"} if tok else {}
        last = ""
        for attempt in range(3):
            space = self.s["hf_spaces"][attempt % len(self.s["hf_spaces"])]
            base = f"https://{space}.hf.space/gradio_api"
            try:
                r = requests.post(f"{base}/call/infer", headers=headers, timeout=60,
                                  json={"data": [prompt[:1500], seed, False, 768, 1344, 4]})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
                eid = r.json()["event_id"]
                ev = None
                with requests.get(f"{base}/call/infer/{eid}", headers=headers, stream=True, timeout=240) as resp:
                    for ln in resp.iter_lines(decode_unicode=True):
                        if not ln:
                            continue
                        if ln.startswith("event:"):
                            ev = ln[6:].strip()
                        elif ln.startswith("data:") and ev == "complete":
                            out = json.loads(ln[5:])[0]
                            url = out.get("url") if isinstance(out, dict) else None
                            if not url and isinstance(out, dict) and out.get("path"):
                                url = f"{base}/file={out['path']}"
                            return _img(requests.get(url, headers=headers, timeout=60).content)
                        elif ln.startswith("data:") and ev == "error":
                            raise RuntimeError("space error " + ln[5:120])
                raise RuntimeError("no picture came back")
            except Exception as e:
                last = str(e)[:160]
                if any(k in last.lower() for k in ("quota", "exceeded", "null")) and attempt >= 1:
                    self.dead.add("hf_space")
                    break
                time.sleep(5)
        raise RuntimeError(last)

    # 3. Pollinations (free, no key; lower quality, small logo is cropped off)
    def _pollinations(self, prompt, seed, line):
        tok = secret("POLLINATIONS_TOKEN")
        q = urllib.parse.quote(prompt[:1400])
        if tok:
            url, headers = f"https://gen.pollinations.ai/image/{q}", {"Authorization": f"Bearer {tok}"}
        else:
            url, headers = f"https://image.pollinations.ai/prompt/{q}", {}
        params = {"width": 768, "height": 1344, "seed": seed, "model": self.s["pollinations_model"], "nologo": "true",
                  "private": "true", "enhance": "false"}
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=150)
            except requests.RequestException as e:
                time.sleep(10)
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                img = _img(r.content)
                if not tok:
                    w0, h0 = img.size
                    img = img.crop((0, 0, w0, int(h0 * 0.92)))
                return img
            time.sleep(20)
        raise RuntimeError("Pollinations did not answer")

    # 4. always works: one of the bundled illustrations (assets/illustrated/*.jpg)
    def _bundled(self, prompt, seed, line):
        pics = sorted((ASSETS / "illustrated").glob("*.jpg")) + sorted((ASSETS / "illustrated").glob("*.png"))
        if not pics:
            return None
        mood = str(line.get("mood", ""))
        fit = [p for p in pics if mood and mood in p.stem] or pics
        return Image.open(random.Random(seed).choice(fit)).convert("RGB")


ART_SCHEMA = {"type": "OBJECT", "properties": {
    "has_text": {"type": "BOOLEAN"}, "deformed": {"type": "BOOLEAN"}, "pretty": {"type": "BOOLEAN"},
    "top_calm": {"type": "BOOLEAN"}, "shows": {"type": "STRING"}},
    "required": ["has_text", "deformed", "pretty", "top_calm", "shows"]}


def check_art(img, s):
    """Gemini looks at the picture. Returns (ok, why) or None when Gemini isn't available."""
    key = secret("GEMINI_API_KEY")
    if not key or not s.get("check_art_with_gemini", True):
        return None
    from . import beauty as B
    sm = img.copy()
    sm.thumbnail((576, 1024))
    buf = io.BytesIO()
    sm.save(buf, "JPEG", quality=85)
    prompt = ("This illustration will be the background of an Instagram quote reel. Look closely. "
              "has_text = true if there is ANY visible text, letters, numbers, signature, logo or watermark (even small or garbled). "
              "deformed = true if any face, eyes, hands, fingers or body look broken, melted, extra or wrong. "
              "pretty = true if it is a sharp, aesthetic, pleasant ILLUSTRATION or painting (false for a blurry or photo-like picture). "
              "top_calm = true if the upper third is calm/plain enough to put white or dark text on. "
              "shows = what it shows in max 12 words.")
    body = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg",
                                                                       "data": base64.b64encode(buf.getvalue()).decode()}}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "responseSchema": ART_SCHEMA}}
    for model in B.gemini_vision_models(key)[:6]:
        try:
            r = B._gemini_call(model, body, key, timeout=60)
            if r.status_code != 200:
                continue
            d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            bad = [k for k in ("has_text", "deformed") if d.get(k)] + ([] if d.get("pretty", True) else ["not pretty"])
            return (not bad), (", ".join(bad) or "ok") + f" - {d.get('shows', '')[:80]}"
        except Exception:
            continue
    return None


def get_art(line, s, seed):
    artist = Artist(s, seed)
    best = None
    for attempt in range(3):
        img, prov = artist.make(line, attempt)
        if prov == "bundled":
            return img, prov, "bundled picture"
        verdict = check_art(img, s)
        if verdict is None:
            if prov == "pollinations":      # lower quality: only used when Gemini has looked at it
                bundled = artist._bundled("", seed, line)
                if bundled is not None:
                    return bundled, "bundled", "Pollinations picture not checked - used a bundled one"
            return img, prov, "not checked (no Gemini)"
        ok, why = verdict
        log.info(f"    art check: {'OK' if ok else 'REJECTED'} ({why})")
        if ok:
            return img, prov, why
        best = best or (img, prov, why)
    log.warning("    art: no picture passed the check - using the bundled pictures")
    img = artist._bundled("", seed, line)
    if img is not None:
        return img, "bundled", "fallback after failed checks"
    return best


def cover(img, w, h):
    sw, sh = img.size
    sc = max(w / sw, h / sh)
    img = img.resize((max(w, round(sw * sc)), max(h, round(sh * sc))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


# ----------------------------------------------------------------------------- text
def font_file(lang):
    return FONTS / ("BalooBhai2.ttf" if lang == "gu" else "Baloo2.ttf")


def get_font(lang, size, weight="ExtraBold"):
    try:
        f = ImageFont.truetype(str(font_file(lang)), size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        f = ImageFont.truetype(str(font_file(lang)), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def check_shaping():
    """Hindi/Gujarati letters need the 'raqm' text shaper, otherwise matras/conjuncts come out broken."""
    from PIL import features
    if not features.check("raqm"):
        raise RuntimeError("Pillow has no raqm text shaper - Hindi/Gujarati would render wrong. "
                           "Install it: sudo apt-get install -y libraqm0 (the workflow does this).")


def parse_words(text):
    """'I am *not rude*,\nreally' -> lines of words; a word is a list of (piece, accent) so punctuation
    right after an accent word stays glued to it ("*chai*," -> [("chai", True), (",", False)])."""
    text = EMOJI.sub("", text.replace("\\n", "\n")).strip()
    out = []
    for raw in text.split("\n"):
        words, acc, cur = [], False, []
        for tok in re.split(r"([ \t]+|\*)", raw):
            if not tok:
                continue
            if tok == "*":
                acc = not acc
                continue
            if tok.isspace():
                if acc and cur and cur[-1][1]:
                    cur[-1] = (cur[-1][0] + " ", True)   # an accent phrase stays on one line ("pani puri")
                    continue
                if cur:
                    words.append(cur)
                cur = []
                continue
            if acc and cur and cur[-1][1] and cur[-1][0].endswith(" "):
                cur[-1] = (cur[-1][0] + tok, True)
            else:
                cur.append((tok, acc))
        if cur:
            words.append(cur)
        if words:
            out.append(words)
    return out


def _wrap(para, f, space, max_w):
    lines, cur, cw = [], [], 0.0
    for word in para:
        ww = sum(f.getlength(p) for p, _ in word)
        if cur and cw + space + ww > max_w:
            lines.append(cur)
            cur, cw = [], 0.0
        cur.append((word, ww))
        cw += (space if len(cur) > 1 else 0) + ww
    if cur:
        lines.append(cur)
    return lines


def _wrap_balanced(para, f, space, max_w):
    """Same number of lines as a greedy wrap, but evenly filled (no lonely last word)."""
    lines = _wrap(para, f, space, max_w)
    if len(lines) < 2:
        return lines
    total = sum(sum(f.getlength(p) for p, _ in w) for w in para) + space * (len(para) - 1)
    target = total / len(lines)
    while target < max_w:
        trial = _wrap(para, f, space, target)
        if len(trial) == len(lines):
            return trial
        target += 12
    return lines


def layout(text, lang, max_w, max_h, start=84, minimum=44):
    """Biggest font that fits. Keeps your own line breaks unless that makes the text much smaller."""
    paras = parse_words(text)

    def fit(exact):
        for size in range(start, (54 if exact else minimum) - 1, -2):
            f = get_font(lang, size)
            space = f.getlength(" ")
            lines = []
            for para in paras:
                lines += _wrap_balanced(para, f, space, max_w)
            lh = int(size * 1.3)
            if exact and len(lines) != len(paras):
                continue
            if len(lines) <= 4 and lh * len(lines) <= max_h and all(
                    sum(x[1] for x in ln) + space * (len(ln) - 1) <= max_w for ln in lines):
                return f, size, lines, lh, space
        return None

    a, b = fit(True), fit(False)
    if a and (not b or a[1] >= 0.8 * b[1]):
        return a
    if b:
        return b
    f = get_font(lang, minimum)
    space = f.getlength(" ")
    lines = [ln for para in paras for ln in _wrap_balanced(para, f, space, max_w)][:5]
    return f, minimum, lines, int(minimum * 1.3), space


def calm_y(bg, lo, hi, block_h, block_w=W * 0.84, prefer_top=0.25):
    """Top of the text block: the calmest band (least detail = no face/body/objects) between lo and hi.
    Detail = edge strength + local contrast measured over the width the text will cover; a small bonus for
    higher positions so the text sits in the upper area when it is equally calm."""
    if hi <= lo:
        return lo
    x0, x1 = int((W - block_w) / 2 / 4), int((W + block_w) / 2 / 4)
    e = None
    for im in (bg if isinstance(bg, (list, tuple)) else [bg]):   # first + last frame of the slow zoom
        small = im.convert("RGB").resize((W // 4, H // 4))
        g = np.asarray(small.convert("L"), dtype=np.float32)[:, x0:x1]
        sat = np.asarray(small.convert("HSV"), dtype=np.float32)[:, x0:x1, 1]
        ey = np.abs(np.diff(g, axis=0, prepend=g[:1]))
        ex = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
        # people/objects = edges + contrast + strong colour (a kurti, hair, skin); sky/walls are pale and smooth
        ycc = np.asarray(small.convert("YCbCr"), dtype=np.float32)[:, x0:x1]
        skin = ((ycc[..., 2] > 135) & (ycc[..., 2] < 175) & (ycc[..., 1] > 85) & (ycc[..., 1] < 130)
                & (ycc[..., 0] > 60) & (ycc[..., 0] < 235))
        dark = ycc[..., 0] < 55                                   # hair
        ei = ((ey + ex).mean(axis=1) + 0.35 * g.std(axis=1) + 0.12 * sat.mean(axis=1) + 0.15 * sat.std(axis=1)
              + 60 * skin.mean(axis=1) + 25 * dark.mean(axis=1))
        e = ei if e is None else np.maximum(e, ei)
    best, by = None, lo
    for y in range(lo, hi + 1, 8):
        a, b = y // 4, max(y // 4 + 1, (y + block_h) // 4)
        band = e[max(0, a - 6):b + 6]          # include a little margin around the text
        score = float(band.mean()) + 0.6 * float(band.max()) / 4 + prefer_top * 24 * (y - lo) / H
        if best is None or score < best:
            best, by = score, y
    return by


def luminance(img, box):
    a = np.asarray(img.crop(box).convert("L"), dtype=np.float32)
    return float(a.mean()), float(np.percentile(a, 90)), float(a.std())


def text_layers(text, lang, bg, s, bg_end=None):
    """Returns the text as separate RGBA pieces (a soft halo, each line's normal words, each accent word)."""
    max_w, top, max_h = W * 0.80, int(H * float(s.get("text_top", 0.07))), int(H * float(s.get("text_height", 0.2)))
    f, size, lines, lh, space = layout(text, lang, max_w, max_h, int(s.get("font_max", 84)))
    block_h = lh * len(lines)
    lowest = int(H * float(s.get("text_lowest", 0.56)))     # the block may sit anywhere from the top to the centre
    wmax = max(sum(x[1] for x in ln) + space * (len(ln) - 1) for ln in lines)
    y0 = calm_y([bg, bg_end] if bg_end is not None else bg, top, max(top, lowest - block_h), block_h, wmax + size * 0.6, float(s.get("prefer_top", 0.25)))
    mean, p90, std = luminance(bg, (int(W * 0.08), y0, int(W * 0.92), y0 + block_h))
    dark_text = mean > 135
    main = (52, 28, 22) if dark_text else (255, 255, 255)
    accent = s["accent_orange"] if dark_text else (s["accent_yellow"] if mean < 95 else s["accent_orange"])
    acc_rgb = tuple(int(accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    shadow = (255, 248, 240) if dark_text else (20, 10, 8)
    pieces = []
    pad = int(size * 0.45)
    union = Image.new("L", (W, H), 0)
    for li, ln in enumerate(lines):
        lw = sum(x[1] for x in ln) + space * (len(ln) - 1)
        x = (W - lw) / 2
        y = y0 + li * lh
        normal = Image.new("RGBA", (W, lh + 2 * pad), (0, 0, 0, 0))
        for word, ww in ln:
            for piece, a in word:
                pw = f.getlength(piece)
                if a:
                    img = Image.new("RGBA", (int(pw) + 2 * pad, lh + 2 * pad), (0, 0, 0, 0))
                    _draw_word(img, (pad, pad), piece, f, acc_rgb, shadow, size, dark_text)
                    pieces.append({"kind": "accent", "line": li, "img": img, "x": int(x) - pad, "y": y - pad})
                    union.paste(255, (int(x), y, int(x + pw), y + lh))
                else:
                    _draw_word(normal, (x, pad), piece, f, main, shadow, size, dark_text)
                x += pw
            x += space
        bb = normal.getchannel("A").getbbox()
        if bb:
            union.paste(255, (bb[0], y + 4, bb[2], y + lh - 4))
        pieces.append({"kind": "line", "line": li, "img": normal, "x": 0, "y": y - pad})
    # soft halo behind the words (no box): a feathered glow of light (dark text) or shadow (white text)
    busy = min(1.0, std / 45.0)
    strength = float(s.get("halo", 0.8)) * (0.5 + 0.5 * busy)
    if strength > 0.02:
        m = union.filter(ImageFilter.GaussianBlur(size * 0.55)).point(lambda v: min(255, v * 3))
        m = m.filter(ImageFilter.GaussianBlur(size * 0.6)).point(lambda v: int(v * strength))
        halo = Image.new("RGBA", (W, H), ((255, 246, 236) if dark_text else (15, 8, 6)) + (0,))
        halo.putalpha(m)
        pieces.insert(0, {"kind": "halo", "line": 0, "img": halo, "x": 0, "y": 0})
    info = {"size": size, "lines": len(lines), "dark_text": dark_text, "bg_mean": round(mean), "bg_std": round(std),
            "accent": accent}
    return pieces, info


def _draw_word(canvas, xy, word, f, color, shadow, size, dark_text):
    x, y = xy
    off = max(2, size // 26)
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    alpha = 150 if dark_text else 170
    d.text((x + (0 if dark_text else off), y + (0 if dark_text else off)), word, font=f, fill=shadow + (alpha,),
           stroke_width=max(2, size // 22) if dark_text else 1, stroke_fill=shadow + (alpha,))
    sh = sh.filter(ImageFilter.GaussianBlur(max(3, size // 14)))
    canvas.alpha_composite(sh)
    ImageDraw.Draw(canvas).text((x, y), word, font=f, fill=color + (255,))


def handle_layer(s, light_bg=False):
    f = ImageFont.truetype(str(FONTS / "Poppins-Medium.ttf"), 34)
    t = s["channel_name"]
    w = int(f.getlength(t)) + 40
    img = Image.new("RGBA", (w, 70), (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((20, 14), t, font=f, fill=((255, 250, 244, 170) if light_bg else (0, 0, 0, 150)))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)))
    ImageDraw.Draw(img).text((20, 14), t, font=f, fill=((60, 38, 32, 225) if light_bg else (255, 255, 255, 215)))
    return img


# ----------------------------------------------------------------------------- video
def _ease(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def _fade(layer, a):
    if a >= 0.999:
        return layer
    al = layer.getchannel("A").point(lambda v: int(v * a))
    out = layer.copy()
    out.putalpha(al)
    return out


def pick_music(s, mood, seed):
    tracks = [p for p in (ASSETS / "music").glob("*") if p.suffix.lower() in {".mp3", ".m4a", ".wav", ".ogg"}
              and not p.name.startswith("kids")]
    if not tracks:
        return None
    want = (s.get("music_by_mood") or {}).get(str(mood), "")
    fit = [p for p in tracks if want and p.stem.startswith(want)]
    return (fit or tracks)[seed % len(fit or tracks)]


def build_illustrated_reel(line, s, workdir, out, art=None):
    check_shaping()
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    seed = int(line.get("seed", 1))
    rnd = random.Random(seed)
    if art is None:
        img, prov, why = get_art(line, s, seed)
    else:
        img, prov, why = art
    secs = float(s["seconds"])
    fps = int(s["fps"])
    n = int(round(secs * fps))
    # big, slightly sharpened copy for the slow zoom
    zoom_max = 1.10
    big = cover(img, int(W * 1.16), int(H * 1.16)).filter(ImageFilter.UnsharpMask(radius=2, percent=50, threshold=3))
    big.save(workdir / "art.jpg", quality=92)
    still = cover(img, W, H)
    move = rnd.choice(["in", "in_up", "in_left", "in_right"])
    bw, bh = big.size

    def view(u):
        z = 1.0 + (zoom_max - 1.0) * (0.5 - 0.5 * math.cos(math.pi * u))   # smooth ease in/out
        cw, ch = bw / (1.16 * z), bh / (1.16 * z)
        cx, cy = bw / 2, bh / 2
        drift = 0.035 * u
        if move == "in_up":
            cy -= bh * drift
        elif move == "in_left":
            cx -= bw * drift
        elif move == "in_right":
            cx += bw * drift
        return (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)

    end = big.transform((W, H), Image.EXTENT, view(1.0), Image.BICUBIC)
    pieces, tinfo = text_layers(line["text"], line.get("lang", "en"), still, s, end)
    hy = int(H * 0.905)
    handle = handle_layer(s, luminance(still, (W // 3, hy, 2 * W // 3, hy + 70))[0] > 150)
    hx = (W - handle.width) // 2
    # dust motes
    motes = []
    if s.get("particles", True):
        for _ in range(26):
            motes.append([rnd.uniform(0, W), rnd.uniform(H * 0.25, H), rnd.uniform(1.5, 4.5), rnd.uniform(0.15, 0.55),
                          rnd.uniform(8, 28), rnd.uniform(0, 6.28)])
    sprite = {}

    def mote(r):
        k = int(r * 2)
        if k not in sprite:
            sz = int(r * 6) + 4
            m = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(m).ellipse((sz / 2 - r, sz / 2 - r, sz / 2 + r, sz / 2 + r), fill=255)
            sprite[k] = m.filter(ImageFilter.GaussianBlur(r * 0.8))
        return sprite[k]

    line_t = {i: 0.25 + 0.45 * i for i in range(tinfo["lines"])}
    last_line = max(line_t.values()) if line_t else 0.25
    pop = bool(s.get("accent_pop", False))   # False = the orange word appears together with its line
    acc_n = 0
    for p in pieces:
        if p["kind"] == "halo":
            p["t0"] = 0.05
        elif p["kind"] == "accent" and pop:
            p["t0"] = last_line + 0.55 + 0.18 * acc_n
            acc_n += 1
        else:
            p["t0"] = line_t[p["line"]]
            if p["kind"] == "accent":
                p["kind"] = "line"     # same fade + slide as the rest of its line

    music = pick_music(s, line.get("mood"), seed)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        mv = float(s["music_volume"])
        cmd += ["-filter_complex", f"[1:a]atrim=0:{secs:.2f},volume={mv},aformat=channel_layouts=stereo,"
                                   f"afade=t=in:d=0.6,afade=t=out:st={secs - 1.2:.2f}:d=1.2[a]",
                "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "44100"]
    cmd += ["-t", f"{secs:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-maxrate", "5500k",
            "-bufsize", "11000k", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=open(workdir / "ffmpeg.log", "wb"))
    try:
        for i in range(n):
            t = i / fps
            box = view(t / secs)
            frame = big.transform((W, H), Image.EXTENT, box, Image.BICUBIC).convert("RGBA")
            if motes:
                layer = Image.new("RGBA", (W, H), (255, 244, 225, 0))
                for m in motes:
                    x = (m[0] + math.sin(t * 0.6 + m[5]) * 14) % W
                    y = (m[1] - m[4] * t) % H
                    a = m[3] * (0.6 + 0.4 * math.sin(t * 1.3 + m[5]))
                    spr = mote(m[2])
                    col = Image.new("RGBA", spr.size, (255, 244, 225, 0))
                    col.putalpha(spr.point(lambda v, a=a: int(v * a)))
                    layer.alpha_composite(col, (int(x), int(y)))
                frame.alpha_composite(layer)
            for p in pieces:
                k = (t - p["t0"]) / {"line": 0.5, "halo": 0.9}.get(p["kind"], 0.38)
                if k <= 0:
                    continue
                e = _ease(k)
                if p["kind"] == "halo":
                    frame.alpha_composite(_fade(p["img"], e), (0, 0))
                elif p["kind"] == "line":
                    frame.alpha_composite(_fade(p["img"], e), (p["x"], int(p["y"] + (1 - e) * 22)))
                else:
                    sc = 1.0 + 0.28 * (1 - e) - 0.05 * math.sin(min(1.0, k) * math.pi)
                    im = p["img"]
                    if abs(sc - 1.0) > 0.003:
                        im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BICUBIC)
                    x = p["x"] + (p["img"].width - im.width) // 2
                    y = p["y"] + (p["img"].height - im.height) // 2
                    frame.alpha_composite(_fade(im, min(1.0, k * 1.6)), (x, y))
            ha = _ease((t - 0.6) / 0.8)
            if ha > 0:
                frame.alpha_composite(_fade(handle, ha), (hx, hy))
            proc.stdin.write(frame.convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        proc.wait(timeout=600)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (workdir / "ffmpeg.log").read_text()[-1500:])
    log.info(f"Reel ready: {out} ({secs:.1f}s, {out.stat().st_size / 1e6:.1f} MB) art={prov} text={tinfo}")
    return {"art": prov, "art_check": why, "text_info": tinfo, "music": music.name if music else None, "seconds": secs}


# ----------------------------------------------------------------------------- caption
HOOKS = {"attitude": ["Tag the friend who has this attitude 😎", "Comment 🔥 if this is you"],
         "funny": ["Tag that friend 😂👀", "Comment 😂 if it's you"],
         "friendship": ["Tag your partner in crime 👯‍♀️", "Send this to your bestie 💗"],
         "relationship": ["Send this to your person 💌", "Comment 💗 if you agree"],
         "self_love": ["Save this for the days you forget 💗", "Comment 💗 if you agree"],
         "emotional": ["Send this to someone who needs it 🥺", "Comment ❤️ if you felt this", "Tag the one this reminds you of 🫶"],
         "confidence": ["Comment 👑 if this is your energy", "Save this, queen ✨"]}
LANG_TAGS = {"en": ["#englishquotes", "#attitudequotes"], "hinglish": ["#hinglishquotes", "#desiquotes"],
             "hi": ["#hindiquotes", "#hindishayari"], "gu": ["#gujaratiquotes", "#gujarati"]}
CAT_TAGS = {"attitude": ["#attitude", "#sassy"], "funny": ["#funnyquotes", "#desihumor"],
            "friendship": ["#bestfriends", "#friendshipquotes"], "relationship": ["#lovequotes", "#couplegoals"],
            "self_love": ["#selflove", "#selflovequotes"], "confidence": ["#confidence", "#queenvibes"],
            "emotional": ["#hearttouching", "#feelings"]}


def captions(line, s):
    cat = line.get("category", "attitude")
    pool = HOOKS.get(cat, HOOKS["attitude"])
    hook = (line.get("hook") or "").strip() or pool[int(line.get("seed", 0)) % len(pool)]
    tags = list(line.get("hashtags") or []) + LANG_TAGS.get(line.get("lang"), []) + CAT_TAGS.get(cat, []) + \
        list(s.get("hashtags_common") or [])
    tags = [t if t.startswith("#") else "#" + t for t in (x.replace(" ", "") for x in tags)]
    tags = list(dict.fromkeys(t.lower() for t in tags))[:10]
    text = re.sub(r"[ \t]+", " ", EMOJI.sub("", line["text"].replace("\\n", "\n").replace("*", ""))).strip()
    ig = f"{text}\n\n{hook}\n\n{s['follow_line']}\n\n" + " ".join(tags)
    one = plain(line["text"])
    title = (one[:80] + "…" if len(one) > 80 else one) + " #shorts"
    return {"youtube_title": title, "youtube_description": ig, "youtube_tags": [t.lstrip("#") for t in tags],
            "instagram_caption": ig}


# ----------------------------------------------------------------------------- run
def run_illustrated(args, cfg, posted, save_posted):
    s = icfg(cfg)
    day = now_ist()
    lang = language_for(day, s)
    lines = load_lines()
    line = None
    if args.topic is not None:
        line = bundled_line(lines, lang, posted, args.topic)
        lang = line.get("lang", lang)
    if line is None:
        line = gemini_line(s, lang, posted, lines)
    if line is None:
        line = bundled_line(lines, lang, posted)
    line["seed"] = day.toordinal() * 37 + len(line["text"])
    log.info(f"Today's line [{line.get('lang')}, {line.get('category')}, {line['source']}]: {plain(line['text'])!r}")
    stamp = day.strftime("%Y-%m-%d")
    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / f"illustrated-{stamp}-{line['id']}.mp4"
    info = build_illustrated_reel(line, s, OUTPUT / "work", out)
    line.update(info)
    caps = captions(line, s)
    (OUTPUT / "caption.txt").write_text(caps["instagram_caption"] + "\n\n(Posting by hand? You can add a trending "
                                        "sound in the Instagram app.)\n", encoding="utf-8")
    (OUTPUT / "youtube.json").write_text(json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT / "script.json").write_text(json.dumps(line, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if args.no_post:
        log.info(f"--no-post: video is at {out}")
        return 0
    from . import beauty as B
    os.environ.setdefault("IG_THUMB_OFFSET_MS", str(int(s.get("cover_ms", 3500))))   # cover = frame with the text
    record = {"topic_id": line["id"], "type": "illustrated", "lang": line.get("lang"), "hook": plain(line["text"]),
              "date": day.isoformat(timespec="minutes"), "instagram": None, "youtube": None, "errors": []}
    B.post_everywhere(out, caps, B.bcfg(cfg), cfg, record, stamp)
    posted["posts"].append(record)
    save_posted(posted)
    if not record["success"]:
        log.error("Instagram did not post today. The video is saved in the run's 'reel' download (Artifacts).")
        return 1
    log.info("Done! Posted to Instagram" + (" and YouTube." if record["youtube"] not in (None, "skipped") else "."))
    return 0
