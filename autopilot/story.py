"""KIDS STORY mode (content_mode: story in config.yaml).

Makes one 30-40 s vertical kids-story reel:
  story script (free Gemini, or the bundled stories.yaml)  ->  one AI cartoon picture per scene
  -> storyteller voice (free edge-tts) with word timings -> slow zoom/pan + soft transitions
  -> small karaoke captions (current word in a purple box) -> soft music under the voice.
Everything is free. If one free service is down, the next one is tried, so a reel is always made.
"""
import asyncio
import base64
import json
import math
import os
import random
import re
import shutil
import subprocess
import time
import urllib.parse
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .common import ASSETS, OUTPUT, ROOT, log, now_ist, secret

W, H = 1080, 1920
LANG_VOICES = {"hindi": "hi-IN-SwaraNeural", "hinglish": "hi-IN-SwaraNeural", "english": "en-IN-NeerjaNeural"}


# ----------------------------------------------------------------------------- settings
def scfg(cfg):
    s = dict(cfg.get("story") or {})
    s.setdefault("language", "hinglish")
    s.setdefault("channel_name", "Nanha Sitara Stories")
    s.setdefault("art_style", "bright colorful 3D cartoon, Pixar Disney animation style, cute chubby character with big expressive eyes, "
                              "cheerful sunny daylight, vibrant saturated colors, kids animated movie, clean detailed render")
    s.setdefault("image_providers", ["hf_flux", "cloudflare", "pollinations", "gemini", "gradient"])
    s.setdefault("pollinations_model", "flux")
    s.setdefault("cloudflare_model", "@cf/black-forest-labs/flux-1-schnell")
    s.setdefault("gemini_model", "gemini-3.8-flash")
    s.setdefault("gemini_image_model", "gemini-2.5-flash-image")
    s.setdefault("use_gemini_story", True)
    s.setdefault("voice_rate", "+0%")
    s.setdefault("voice_pitch", "+0Hz")
    s.setdefault("caption_font_size", 64)
    s.setdefault("caption_max_words", 3)
    s.setdefault("caption_y", 0.68)
    s.setdefault("highlight_color", "#7B2FF7")
    s.setdefault("show_title", True)
    s.setdefault("music_volume", 0.22)
    s.setdefault("glitch", False)
    s.setdefault("transition", "fade")
    s.setdefault("transition_seconds", 0.5)
    s.setdefault("fps", 30)
    s.setdefault("max_mb", 15)
    return s


def voice_for(s):
    return s.get("voice") or LANG_VOICES.get(s["language"], "hi-IN-SwaraNeural")


# ----------------------------------------------------------------------------- stories
def load_stories():
    p = ROOT / "stories.yaml"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _scene_text(sc, lang):
    """(spoken text, caption text). Hinglish = Hindi voice reads Devanagari, captions show Roman Hindi."""
    if lang == "english":
        t = sc.get("en") or sc.get("hi")
        return t, t
    spoken = sc.get("hi") or sc.get("en")
    if lang == "hinglish":
        return spoken, sc.get("hinglish") or spoken
    return spoken, spoken


def bundled_story(stories, posted, lang, want_id=None):
    if not stories:
        raise RuntimeError("stories.yaml is missing or empty")
    done = {str(p.get("topic_id")) for p in posted.get("posts", []) if p.get("success")}
    if want_id is not None:
        pick = [s for s in stories if str(s["id"]) == str(want_id)]
        if not pick:
            raise RuntimeError(f"No story with id {want_id} in stories.yaml")
        st = pick[0]
    else:
        left = [s for s in stories if f"story-{s['id']}" not in done]
        st = left[0] if left else stories[(len(done)) % len(stories)]
    key = {"english": "en", "hinglish": "hinglish"}.get(lang, "hi")
    title = st.get(f"title_{key}") or st.get("title_hi") or st.get("title_en")
    moral = st.get(f"moral_{key}") or st.get("moral_hi") or st.get("moral_en")
    scenes = []
    for sc in st["scenes"]:
        spoken, caption = _scene_text(sc, lang)
        scenes.append({"narration": spoken, "caption": caption, "image": sc["image"]})
    return {"id": f"story-{st['id']}", "title": title, "title_en": st.get("title_en", title), "moral": moral,
            "moral_en": st.get("moral_en", moral), "character": st.get("character", ""), "scenes": scenes,
            "tags": st.get("tags", []), "source": "stories.yaml", "seed": 1000 + int(st["id"]) * 7}


STORY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"}, "title_en": {"type": "STRING"},
        "character": {"type": "STRING"}, "moral": {"type": "STRING"}, "moral_en": {"type": "STRING"},
        "scenes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "narration": {"type": "STRING"}, "caption": {"type": "STRING"}, "image_prompt": {"type": "STRING"}},
            "required": ["narration", "caption", "image_prompt"]}},
        "youtube_title": {"type": "STRING"}, "youtube_description": {"type": "STRING"},
        "youtube_tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "instagram_caption": {"type": "STRING"},
    },
    "required": ["title", "title_en", "character", "moral", "moral_en", "scenes", "youtube_title",
                 "youtube_description", "youtube_tags", "instagram_caption"],
}


def gemini_text_models(key):
    """Google retires model names often, so ask which 'flash' models this key can use (newest first)."""
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key, "pageSize": 300},
                         timeout=30)
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception:
        return []
    ok = [n for n in names if re.fullmatch(r"gemini-\d+(\.\d+)?-flash(-lite)?", n)]

    def ver(n):
        v = re.findall(r"\d+(?:\.\d+)?", n)[0]
        return (float(v), "lite" not in n)
    return sorted(ok, key=ver, reverse=True)


def gemini_story(s, posted):
    key = secret("GEMINI_API_KEY")
    if not key or not s.get("use_gemini_story", True):
        return None
    lang = s["language"]
    recent = [p.get("hook") for p in posted.get("posts", [])[-40:] if p.get("hook")]
    lang_rule = {
        "hindi": "narration and caption: simple spoken Hindi in Devanagari (caption = same text as narration).",
        "english": "narration and caption: simple English (caption = same text as narration).",
        "hinglish": ("narration: simple spoken Hindi in Devanagari script (a few common English words are OK); "
                     "caption: the SAME sentence written in Roman letters the way Indians type Hindi on WhatsApp, "
                     "word-for-word with EXACTLY the same number of words as narration."),
    }[lang]
    prompt = f"""You write 30-40 second stories for the YouTube kids channel "{s['channel_name']}" (Indian children aged 3-8):
fun, colourful, simple stories with a moral lesson, fun facts and playful learning.
Write ONE new, original, child-safe story with exactly 6 scenes.
- Total narration 65-85 words. Very short, simple sentences. Scene 1 is a hook, the last scene says the moral.
- {lang_rule}
- character: one fixed visual description of the main character (species/child, colours, eyes, one accessory), in English.
- image_prompt (English): only what is visible in that scene (action, place, mood, time of day). Call the main character
  "the <animal/child>"; describe any other character with the same words every time. No text in images. Cheerful, safe.
- title / moral in the narration language (title_en, moral_en in English).
- youtube_title: under 70 characters, catchy, include #shorts. youtube_description: 2-3 lines with the moral + 5 hashtags.
- youtube_tags: 10 tags. instagram_caption: 2 lines + 8 hashtags.
Do NOT reuse these recent titles: {json.dumps(recent, ensure_ascii=False)}"""
    models = [s["gemini_model"]] + gemini_text_models(key) + ["gemini-flash-latest", "gemini-flash-lite-latest"]
    for model in dict.fromkeys(models):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key}, timeout=90,
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json",
                                           "responseSchema": STORY_SCHEMA}})
            if r.status_code != 200:
                log.warning(f"Gemini story ({model}) HTTP {r.status_code}: {r.text[:200]}")
                continue
            data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            scenes = [{"narration": x["narration"].strip(), "caption": (x.get("caption") or x["narration"]).strip(),
                       "image": x["image_prompt"].strip()} for x in data["scenes"] if x.get("narration")]
            if len(scenes) < 4:
                raise ValueError("too few scenes")
            log.info(f"Story written by Gemini ({model}): {data['title']}")
            return {"id": "story-ai-" + now_ist().strftime("%Y%m%d"), "title": data["title"],
                    "title_en": data.get("title_en", data["title"]), "moral": data["moral"],
                    "moral_en": data.get("moral_en", data["moral"]), "character": data["character"],
                    "scenes": scenes[:8], "tags": data.get("youtube_tags", []), "source": f"gemini:{model}",
                    "seed": random.randint(1, 10 ** 6), "ai_meta": data}
        except Exception as e:
            log.warning(f"Gemini story ({model}) failed: {e.__class__.__name__}: {e}")
    return None


# ----------------------------------------------------------------------------- pictures
class Painter:
    """Tries free picture makers in order; remembers which ones are down for this run."""

    def __init__(self, s, workdir):
        self.s, self.dir = s, workdir
        self.dead = set()
        self.last_poll = 0.0
        self.stats = []

    def prompt(self, story, scene):
        return (f"{story['character']}. Scene: {scene['image']}. {self.s['art_style']}, "
                f"full body visible, vertical composition, no text, no letters, no watermark")

    def paint(self, story, i, scene):
        out = self.dir / f"scene_{i:02d}.png"
        p = self.prompt(story, scene)
        for prov in self.s["image_providers"]:
            if prov in self.dead:
                continue
            t0 = time.time()
            try:
                img = getattr(self, "_" + prov)(p, story["seed"], i)
            except Exception as e:
                log.warning(f"    picture {i + 1}: {prov} failed ({e.__class__.__name__}: {str(e)[:160]})")
                img = None
            if img is not None:
                img = cover(img.convert("RGB"), W, H)
                img.save(out)
                self.stats.append((i, prov, round(time.time() - t0, 1)))
                log.info(f"    picture {i + 1}: {prov} in {time.time() - t0:.0f}s")
                return out
        raise RuntimeError("no picture maker worked")


    # 1. FLUX on Hugging Face's free public demo (no account, no card). Best free pictures (Pixar-like).
    #    Optional free HF_TOKEN secret (huggingface.co -> Settings -> Access Tokens) gives a bigger daily quota.
    def _hf_flux(self, prompt, seed, i):
        spaces = self.s.get("hf_spaces") or ["black-forest-labs-flux-1-schnell"]
        tok = secret("HF_TOKEN")
        headers = {"Authorization": f"Bearer {tok}"} if tok else {}
        last = ""
        for attempt in range(4):
            space = spaces[attempt % len(spaces)]
            base = f"https://{space}.hf.space/gradio_api"
            try:
                r = requests.post(f"{base}/call/infer", headers=headers, timeout=60,
                                  json={"data": [prompt[:1500], seed, False, 864, 1536, 4]})
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
                eid = r.json()["event_id"]
                ev = None
                with requests.get(f"{base}/call/infer/{eid}", headers=headers, stream=True, timeout=240) as resp:
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if line.startswith("event:"):
                            ev = line[6:].strip()
                        elif line.startswith("data:") and ev == "complete":
                            out = json.loads(line[5:])[0]
                            url = out.get("url") if isinstance(out, dict) else None
                            if not url and isinstance(out, dict) and out.get("path"):
                                url = f"{base}/file={out['path']}"
                            img = requests.get(url, headers=headers, timeout=60)
                            return Image.open(_bytes(img.content))
                        elif line.startswith("data:") and ev == "error":
                            raise RuntimeError("space error " + line[5:120])
                raise RuntimeError("no picture came back")
            except Exception as e:
                last = str(e)[:160]
                # "error null" / quota = the free daily GPU time is used up -> stop asking for this run
                if any(k in last.lower() for k in ("quota", "exceeded", "null")) and attempt >= 1:
                    self.dead.add("hf_flux")
                    break
                time.sleep(4)
        raise RuntimeError(last + ("" if tok else "  (tip: add a free HF_TOKEN secret for a bigger daily quota)"))

    # 2. Cloudflare Workers AI (free plan, no card): FLUX too. Needs CF_ACCOUNT_ID + CF_API_TOKEN secrets.
    def _cloudflare(self, prompt, seed, i):
        acct, tok = secret("CF_ACCOUNT_ID"), secret("CF_API_TOKEN")
        if not (acct and tok):
            self.dead.add("cloudflare")
            return None
        model = self.s["cloudflare_model"]
        body = {"prompt": prompt[:2000], "seed": seed + i, "steps": 8}
        if "flux-1-schnell" not in model:
            body.update({"width": 768, "height": 1344})
        for attempt in range(3):
            r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}",
                              headers={"Authorization": f"Bearer {tok}"}, json=body, timeout=120)
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and ctype.startswith("image"):
                return Image.open(_bytes(r.content))
            if r.status_code == 200:
                b64 = (r.json().get("result") or {}).get("image")
                if b64:
                    return Image.open(_bytes(base64.b64decode(b64)))
            if r.status_code in (401, 403):
                self.dead.add("cloudflare")
                raise RuntimeError(f"HTTP {r.status_code} (check CF_API_TOKEN / CF_ACCOUNT_ID): {r.text[:150]}")
            if r.status_code == 429 and "daily" in r.text.lower():
                self.dead.add("cloudflare")
                raise RuntimeError("free daily limit used up")
            time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")

    # 3. Pollinations: free, no account. Anonymous limit = 1 picture per ~45 s, lower resolution.
    def _pollinations(self, prompt, seed, i):
        tok = secret("POLLINATIONS_TOKEN")
        q = urllib.parse.quote(prompt[:1500])
        if tok:
            url = f"https://gen.pollinations.ai/image/{q}"
            params = {"width": 1080, "height": 1920, "seed": seed, "model": self.s.get("pollinations_key_model", "zimage"),
                      "nologo": "true"}
            headers = {"Authorization": f"Bearer {tok}"}
        else:
            url = f"https://image.pollinations.ai/prompt/{q}"
            params = {"width": 1080, "height": 1920, "seed": seed, "model": self.s["pollinations_model"],
                      "nologo": "true", "private": "true"}
            headers = {}
        deadline = time.time() + 200
        last = ""
        while time.time() < deadline:
            wait = 47 - (time.time() - self.last_poll)
            if not tok and wait > 0:
                time.sleep(wait)
            self.last_poll = time.time()
            try:
                r = requests.get(url, params=params, headers=headers, timeout=150)
            except requests.RequestException as e:
                last = str(e)
                time.sleep(10)
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                img = Image.open(_bytes(r.content))
                if not tok:  # the free picture carries a small logo in the bottom corner: trim it off
                    w0, h0 = img.size
                    img = img.crop((0, 0, w0, int(h0 * 0.93)))
                return img
            last = f"HTTP {r.status_code}: {r.text[:120]}"
            m = re.search(r"[Rr]etry after (\d+)", r.text or "")
            time.sleep(min(int(m.group(1)) + 2, 60) if m else 15)
        raise RuntimeError("gave up after ~3 min: " + last)

    # 4. Gemini picture model (only if your free key allows pictures).
    def _gemini(self, prompt, seed, i):
        key = secret("GEMINI_API_KEY")
        if not key:
            self.dead.add("gemini")
            return None
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.s['gemini_image_model']}:generateContent",
            params={"key": key}, timeout=120,
            json={"contents": [{"parts": [{"text": prompt + ". Tall 9:16 portrait picture."}]}],
                  "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}})
        if r.status_code != 200:
            if r.status_code in (400, 403, 404, 429):
                self.dead.add("gemini")
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
        for part in r.json()["candidates"][0]["content"]["parts"]:
            d = part.get("inlineData") or part.get("inline_data")
            if d:
                return Image.open(_bytes(base64.b64decode(d["data"])))
        raise RuntimeError("no picture in answer")

    # 5. Always works: a soft colourful gradient with little stars.
    def _gradient(self, prompt, seed, i):
        rnd = random.Random(seed + i)
        pal = [((255, 179, 186), (186, 225, 255)), ((255, 223, 186), (186, 255, 201)),
               ((214, 186, 255), (255, 186, 233)), ((186, 255, 255), (255, 255, 186))]
        a, b = pal[(seed + i) % len(pal)]
        y = np.linspace(0, 1, H)[:, None, None]
        arr = (np.array(a) * (1 - y) + np.array(b) * y) * np.ones((H, W, 3))
        img = Image.fromarray(arr.astype("uint8"))
        d = ImageDraw.Draw(img)
        for _ in range(40):
            x0, y0, r0 = rnd.randint(0, W), rnd.randint(0, H), rnd.randint(4, 14)
            d.ellipse((x0 - r0, y0 - r0, x0 + r0, y0 + r0), fill=(255, 255, 255))
        return img.filter(ImageFilter.GaussianBlur(2))


def _bytes(b):
    import io
    return io.BytesIO(b)


def cover(img, w, h):
    return ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.45))


# ----------------------------------------------------------------------------- voice
def speak(text, path, voice, rate, pitch):
    """edge-tts with word timings -> list of (start_s, end_s, word)."""
    import edge_tts

    async def go():
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        words = []
        with open(path, "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    st = ch["offset"] / 1e7
                    words.append((st, st + ch["duration"] / 1e7, ch["text"]))
        return words

    last = None
    for attempt in range(3):
        try:
            return asyncio.run(asyncio.wait_for(go(), timeout=90))
        except TypeError:  # very old edge-tts without the boundary option
            raise
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"voice failed: {last}")


def probe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip() or 0)


def _align_latin(spoken_words, cap):
    """English captions vs English voice with different word counts: match the words by spelling,
    so each caption word lights up exactly when it is said."""
    import difflib
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    sp = [norm(w[2]) for w in spoken_words]
    toks, owner = [], []
    for ci, c in enumerate(cap):
        for part in re.split(r"[^A-Za-z0-9]+", c):
            if part:
                toks.append(part.lower())
                owner.append(ci)
    sm = difflib.SequenceMatcher(a=toks, b=sp, autojunk=False)
    hit = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            hit.setdefault(owner[blk.a + k], []).append(blk.b + k)
    if len(hit) < max(1, len(cap) // 2):
        return None
    full = {ci: len(v) == owner.count(ci) for ci, v in hit.items()}
    span = {ci: [min(v), max(v)] for ci, v in hit.items()}
    keys = sorted(span)
    for x, y in zip(keys, keys[1:]):  # spoken words nobody matched (e.g. "Dhruvi verse dot") ...
        if y == x + 1 and span[y][0] > span[x][1] + 1:
            if not full[y]:
                span[y][0] = span[x][1] + 1   # ... belong to the next caption word if it is only partly matched
            elif not full[x]:
                span[x][1] = span[y][0] - 1
    out = []
    for ci, c in enumerate(cap):
        if ci in span:
            out.append([spoken_words[span[ci][0]][0], spoken_words[span[ci][1]][1], c])
        else:
            out.append([None, None, c])
    for i, o in enumerate(out):  # caption words with no spoken match: share the gap between neighbours
        if o[0] is None:
            prev = out[i - 1][1] if i else spoken_words[0][0]
            j = i
            while j < len(out) and out[j][0] is None:
                j += 1
            nxt = out[j][0] if j < len(out) else spoken_words[-1][1]
            k = j - i
            for m in range(k):
                out[i + m][0] = prev + (nxt - prev) * m / k
                out[i + m][1] = prev + (nxt - prev) * (m + 1) / k
    return [tuple(o) for o in out]


def align_caption_words(spoken_words, caption_text):
    """Map the caption words (with punctuation) onto the spoken word timings.
    Same count -> 1:1. Different count (e.g. Roman Hindi) -> spread by length over the same time."""
    cap = caption_text.split()
    if not spoken_words:
        return []
    if len(cap) == len(spoken_words):
        return [(a, b, c) for (a, b, _), c in zip(spoken_words, cap)]
    if all(re.search(r"[A-Za-z]", w[2]) for w in spoken_words) and all(re.search(r"[A-Za-z0-9]", c) for c in cap):
        out = _align_latin(spoken_words, cap)
        if out:
            return out
    t0, t1 = spoken_words[0][0], spoken_words[-1][1]
    weights = [max(2, len(c)) for c in cap]
    tot, acc, out = sum(weights), 0, []
    for c, wgt in zip(cap, weights):
        a = t0 + (t1 - t0) * acc / tot
        acc += wgt
        out.append((a, t0 + (t1 - t0) * acc / tot, c))
    return out


# ----------------------------------------------------------------------------- captions
def _font(size):
    for name in ("Poppins-ExtraBold.ttf", "Poppins-Bold.ttf", "Poppins-SemiBold.ttf"):
        p = ASSETS / "fonts" / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _hex(c, alpha=255):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def group_words(words, max_words, max_chars=18):
    groups, cur = [], []
    for w in words:
        txt = w[2]
        if cur and (len(cur) >= max_words or sum(len(x[2]) + 1 for x in cur) + len(txt) > max_chars):
            groups.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?,।;:]$", txt):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


class CaptionPainter:
    def __init__(self, s):
        self.size = int(s["caption_font_size"])
        self.font = _font(self.size)
        self.hl = _hex(s["highlight_color"])
        self.h = int(self.size * 2.6)

    def draw(self, words, active, path):
        """One caption picture: words in white with a dark outline, word number `active` in a purple box."""
        f, pad_x, gap = self.font, int(self.size * 0.28), int(self.size * 0.30)
        stroke = max(3, self.size // 13)
        widths = [f.getbbox(w, stroke_width=stroke)[2] - f.getbbox(w, stroke_width=stroke)[0] for w in words]
        total = sum(widths) + gap * (len(words) - 1)
        scale = 1.0
        if total > W * 0.80:  # never wider than 80% of the screen
            scale = W * 0.80 / total
        if scale < 1.0:
            f = _font(int(self.size * scale))
            widths = [f.getbbox(w, stroke_width=stroke)[2] - f.getbbox(w, stroke_width=stroke)[0] for w in words]
            total = sum(widths) + gap * (len(words) - 1)
        img = Image.new("RGBA", (W, self.h), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (W, self.h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        d = ImageDraw.Draw(img)
        asc, desc = f.getmetrics()
        cy = self.h // 2
        x = (W - total) // 2
        ty = cy - (asc + desc) // 2 + int(self.size * 0.06)
        boxes = []
        for i, (w, wd) in enumerate(zip(words, widths)):
            if i == active:
                boxes.append((x - pad_x, cy - int(self.size * 0.70), x + wd + pad_x, cy + int(self.size * 0.70)))
            sd.text((x + 3, ty + 5), w, font=f, fill=(0, 0, 0, 170), stroke_width=stroke + 2, stroke_fill=(0, 0, 0, 170))
            x += wd + gap
        shadow = shadow.filter(ImageFilter.GaussianBlur(5))
        img = Image.alpha_composite(img, shadow)
        d = ImageDraw.Draw(img)
        for b in boxes:
            d.rounded_rectangle(b, radius=int(self.size * 0.32), fill=self.hl)
        x = (W - total) // 2
        for i, (w, wd) in enumerate(zip(words, widths)):
            d.text((x, ty), w, font=f, fill=(255, 255, 255, 255), stroke_width=stroke,
                   stroke_fill=(20, 10, 40, 255) if i != active else (60, 10, 120, 255))
            x += wd + gap
        img.save(path)


def title_png(title, channel, path, s):
    f1, f2 = _font(int(s["caption_font_size"] * 1.15)), _font(int(s["caption_font_size"] * 0.55))
    img = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if not channel:  # beauty mode: the handle is drawn separately for the whole reel
        _title_lines(d, title, f1, 60, s)
        img.save(path)
        return
    # channel pill
    cw = f2.getbbox(channel)[2] + 50
    d.rounded_rectangle(((W - cw) // 2, 20, (W + cw) // 2, 20 + int(s["caption_font_size"] * 0.5) + 30), radius=30,
                        fill=_hex(s["highlight_color"], 235))
    d.text((W // 2, 20 + (int(s["caption_font_size"] * 0.5) + 30) // 2), channel, font=f2, fill="white", anchor="mm")
    _title_lines(d, title, f1, 130, s)
    img.save(path)


def handle_png(handle, path, s):
    """Small handle pill shown at the top for the whole reel (beauty mode)."""
    f = _font(int(s.get("handle_font_size", 34)))
    img = Image.new("RGBA", (W, 110), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tw = f.getbbox(handle)[2]
    h = int(s.get("handle_font_size", 34)) + 26
    d.rounded_rectangle(((W - tw) // 2 - 26, 20, (W + tw) // 2 + 26, 20 + h), radius=h // 2,
                        fill=(0, 0, 0, int(255 * 0.32)))
    d.text((W // 2, 20 + h // 2), handle, font=f, fill=(255, 255, 255, 240), anchor="mm")
    img.save(path)


def _title_lines(d, title, f1, y, s):
    words, lines, cur = title.split(), [], ""
    for w in words:
        if f1.getbbox((cur + " " + w).strip())[2] > W * 0.82 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    for ln in lines[:2]:
        d.text((W // 2, y), ln, font=f1, fill="white", anchor="mm", stroke_width=6, stroke_fill=(30, 10, 60))
        y += int(s["caption_font_size"] * 1.35)


# ----------------------------------------------------------------------------- music (made by maths, copyright free)
def make_kids_music(path, seconds, seed=0):
    sr = 44100
    rnd = random.Random(seed)
    bpm = 104
    beat = 60 / bpm
    n = int(seconds * sr)
    out = np.zeros(n)
    t_all = np.arange(n) / sr

    def hz(m):
        return 440 * 2 ** ((m - 69) / 12)

    def tone(m, dur, kind="mallet", vol=0.3):
        k = int(dur * sr)
        t = np.arange(k) / sr
        f = hz(m)
        if kind == "mallet":
            s = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t * 18)
            s *= np.exp(-t * 5.5)
        elif kind == "pluck":
            s = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t)) * np.exp(-t * 7)
        else:  # bass
            s = np.sin(2 * np.pi * f * t) * np.exp(-t * 3)
        s *= np.minimum(1, t / 0.004)
        return s * vol

    def add(sig, at):
        i = int(at * sr)
        if i >= n:
            return
        j = min(n, i + len(sig))
        out[i:j] += sig[: j - i]

    prog = [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]]  # C G Am F
    scale = [72, 74, 76, 79, 81, 84]
    t, bar = 0.0, 0
    while t < seconds:
        ch = prog[bar % 4]
        add(tone(ch[0] - 24, beat * 2, "bass", 0.32), t)
        add(tone(ch[0] - 24, beat * 2, "bass", 0.25), t + beat * 2)
        for k in range(8):  # ukulele-ish arpeggio
            add(tone(ch[k % 3] + (12 if k % 4 == 3 else 0), beat, "pluck", 0.10), t + k * beat / 2)
        for k in range(4):  # little xylophone tune
            if rnd.random() < 0.8:
                m = rnd.choice([x for x in scale if (x % 12) in [c % 12 for c in ch]] or scale)
                add(tone(m, beat * 1.5, "mallet", 0.13), t + k * beat)
        t += beat * 4
        bar += 1
    # soft shaker
    hat = np.random.default_rng(seed).normal(0, 1, int(0.03 * sr)) * np.exp(-np.arange(int(0.03 * sr)) / sr * 120) * 0.025
    k = 0
    while k * beat / 2 < seconds:
        add(hat, k * beat / 2)
        k += 1
    out *= np.minimum(1, t_all / 1.0) * np.minimum(1, (seconds - t_all) / 1.5).clip(0, 1)
    out /= max(1e-6, np.abs(out).max()) / 0.8
    data = (out * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wv:
        wv.setnchannels(1)
        wv.setsampwidth(2)
        wv.setframerate(sr)
        wv.writeframes(data.tobytes())
    return path


def pick_music(s, workdir, seconds, seed):
    pat = s.get("music_glob", "kids*")
    tracks = [p for p in (ASSETS / "music").glob(pat) if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}
              and (pat.startswith("kids") or not p.name.startswith("kids"))]
    if tracks:
        return random.choice(tracks)
    return make_kids_music(workdir / "music.wav", seconds + 1, seed)


# ----------------------------------------------------------------------------- ffmpeg
def ff(args, timeout=900):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-1500:])


MOVES = ["in", "pan_right", "out", "pan_up", "pan_left", "in"]


def scene_clip(img, secs, fps, move, out):
    """Slow Ken-Burns zoom/pan on one picture."""
    frames = int(math.ceil(secs * fps))
    big = out.with_suffix(".big.png")
    with Image.open(img) as im:
        im = im.convert("RGB").resize((W * 2, H * 2), Image.LANCZOS)
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
        im.save(big)
    p = f"(on/{frames})"
    z, x, y = {
        "in": (f"1.0+0.13*{p}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "out": (f"1.13-0.13*{p}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "pan_right": ("1.12", f"(iw-iw/zoom)*{p}", "ih/2-(ih/zoom/2)"),
        "pan_left": ("1.12", f"(iw-iw/zoom)*(1-{p})", "ih/2-(ih/zoom/2)"),
        "pan_up": ("1.12", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-{p})"),
    }[move]
    ff(["-loop", "1", "-framerate", fps, "-i", big,
        "-vf", f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={fps},eq=saturation=1.08:contrast=1.03,format=yuv420p",
        "-frames:v", frames, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out])
    big.unlink(missing_ok=True)
    return out


# ----------------------------------------------------------------------------- main build
def build_story_reel(story, cfg, workdir: Path, out_path: Path, s=None, painter=None):
    s = s or scfg(cfg)
    fps, T = int(s["fps"]), float(s["transition_seconds"])
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    voice = voice_for(s)
    n = len(story["scenes"])

    log.info(f"1/5 Voice ({voice}) for {n} scenes")
    lead, tail_gap = 0.2, 0.45
    voices = []
    for i, sc in enumerate(story["scenes"]):
        mp3 = workdir / f"voice_{i:02d}.mp3"
        words = speak(sc["narration"], mp3, voice, s["voice_rate"], s["voice_pitch"])
        voices.append((mp3, probe_dur(mp3), words))
    # each picture lasts as long as its sentence (trailing silence in the voice file is ignored)
    durs = [lead + (w[-1][1] if w else d) + tail_gap for _, d, w in voices]
    durs[-1] += 0.9  # let the last picture breathe
    total = sum(durs)
    log.info(f"    story length {total:.1f}s")

    painter = painter or Painter(s, workdir)
    starts = [sum(durs[:i]) for i in range(n)]
    clips = []
    if hasattr(painter, "scene_clips"):  # beauty mode with real stock video clips
        log.info("2/5 Video clips")
        clips = painter.scene_clips(story, [durs[i] + (T if i < n - 1 else 0) for i in range(n)], fps, workdir)
    else:
        log.info("2/5 Pictures")
        imgs = [painter.paint(story, i, sc) for i, sc in enumerate(story["scenes"])]
        log.info("3/5 Moving pictures")
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = []
        for i in (range(0) if clips else range(n)):
            secs = durs[i] + (T if i < n - 1 else 0)
            futs.append(ex.submit(scene_clip, imgs[i], secs, fps, MOVES[i % len(MOVES)], workdir / f"clip_{i:02d}.mp4"))
        clips = clips or [f.result() for f in futs]

    # voice track: each scene's speech placed exactly where its picture starts
    vparts = []
    for i, (mp3, d, _) in enumerate(voices):
        seg = workdir / f"vseg_{i:02d}.wav"
        ff(["-i", mp3, "-af", f"adelay={int(lead * 1000)}:all=1,apad,atrim=0:{durs[i]:.3f},afade=t=out:st={durs[i] - 0.06:.3f}:d=0.06", "-ar", "44100", "-ac", "1", seg])
        vparts.append(seg)
    (workdir / "vlist.txt").write_text("".join(f"file '{p.name}'\n" for p in vparts))
    voice_wav = workdir / "voice.wav"
    ff(["-f", "concat", "-safe", "0", "-i", workdir / "vlist.txt", "-c", "copy", voice_wav])

    log.info("4/5 Karaoke captions")
    cp = CaptionPainter(s)
    timeline = []  # (start, end, words, active)
    for i, (mp3, d, words) in enumerate(voices):
        cap_words = align_caption_words(words, story["scenes"][i]["caption"])
        cap_words = [(starts[i] + lead + a, starts[i] + lead + b, c) for a, b, c in cap_words]
        groups = group_words(cap_words, int(s["caption_max_words"]))
        for gi, g in enumerate(groups):
            g_end = groups[gi + 1][0][0] if gi + 1 < len(groups) else min(g[-1][1] + 0.35, starts[i] + durs[i] - 0.05)
            for wi, (a, b, _) in enumerate(g):
                end = g[wi + 1][0] if wi + 1 < len(g) else g_end
                timeline.append((a, end, [x[2] for x in g], wi))
    blank = workdir / "cap_blank.png"
    Image.new("RGBA", (W, cp.h), (0, 0, 0, 0)).save(blank)
    lines, t, k = [], 0.0, 0
    for (a, b, words, act) in timeline:
        if a > t + 0.01:
            lines += [f"file '{blank.name}'", f"duration {a - t:.3f}"]
        png = workdir / f"cap_{k:04d}.png"
        cp.draw(words, act, png)
        lines += [f"file '{png.name}'", f"duration {max(0.04, b - a):.3f}"]
        t, k = b, k + 1
    lines += [f"file '{blank.name}'", f"duration {max(0.1, total - t + 0.5):.3f}", f"file '{blank.name}'"]
    (workdir / "caps.txt").write_text("\n".join(lines) + "\n")

    log.info("5/5 Putting it all together")
    music = pick_music(s, workdir, total, story["seed"])
    inputs, fc = [], []
    for c in clips:
        inputs += ["-i", c]
    last = "[0:v]"
    for i in range(1, n):
        lbl = f"[x{i}]"
        fc.append(f"{last}[{i}:v]xfade=transition={s['transition']}:duration={T}:offset={starts[i]:.3f}{lbl}")
        last = lbl
    base = last
    if s.get("glitch"):
        en = "+".join(f"between(t,{starts[i] - 0.06:.2f},{starts[i] + 0.12:.2f})" for i in range(1, n))
        fc.append(f"{base}rgbashift=rh=-14:bh=14:enable='{en}',noise=alls=18:allf=t:enable='{en}'[gl]")
        base = "[gl]"
    ci = n
    inputs += ["-f", "concat", "-safe", "0", "-i", workdir / "caps.txt"]
    cap_y = int(H * float(s["caption_y"]) - cp.h / 2)
    fc.append(f"[{ci}:v]fps={fps},format=rgba[cap]")
    fc.append(f"{base}[cap]overlay=0:{cap_y}:format=auto:shortest=0:eof_action=pass[vc]")
    vout = "[vc]"
    nxt = ci + 1
    if s.get("show_title", True):
        tp = workdir / "title.png"
        title_png(story["title"], "" if s.get("handle_always") else s["channel_name"], tp, s)
        inputs += ["-loop", "1", "-t", f"{min(3.4, durs[0]):.2f}", "-i", tp]
        fc.append(f"[{nxt}:v]format=rgba,fade=in:st=0:d=0.4:alpha=1,fade=out:st={min(3.4, durs[0]) - 0.5:.2f}:d=0.5:alpha=1[tt]")
        fc.append(f"{vout}[tt]overlay=0:{int(H * 0.08)}:eof_action=pass[vt]")
        vout = "[vt]"
        nxt += 1
    if s.get("handle_always"):
        hp = workdir / "handle.png"
        handle_png(s["channel_name"], hp, s)
        inputs += ["-loop", "1", "-t", f"{total + 0.5:.2f}", "-i", hp]
        fc.append(f"{vout}[{nxt}:v]overlay=0:{int(H * 0.035)}:eof_action=pass[vh]")
        vout = "[vh]"
        nxt += 1
    inputs += ["-i", voice_wav]
    va = nxt
    nxt += 1
    inputs += ["-stream_loop", "-1", "-i", music]
    ma = nxt
    mv = float(s["music_volume"])
    fc.append(f"[{va}:a]aformat=channel_layouts=stereo,volume=1.6,asplit=2[v1][v2]")
    fc.append(f"[{ma}:a]aformat=channel_layouts=stereo,volume={mv}[mu]")
    fc.append("[mu][v1]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=350[duck]")
    fc.append(f"[v2][duck]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={total - 0.8:.2f}:d=0.8,"
              f"alimiter=limit=0.95[a]")
    vf_final = f"{vout}format=yuv420p,setsar=1[v]"
    fc.append(vf_final)
    crf = 21
    for attempt in range(3):
        ff(inputs + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
                     "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-maxrate", "3500k", "-bufsize", "7000k",
                     "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", fps,
                     "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", out_path])
        mb = out_path.stat().st_size / 1e6
        if mb <= float(s["max_mb"]):
            break
        crf += 3
    log.info(f"Reel ready: {out_path} ({total:.1f}s, {out_path.stat().st_size / 1e6:.1f} MB)")
    return {"path": out_path, "seconds": total, "pictures": painter.stats}


# ----------------------------------------------------------------------------- captions for posting
def story_captions(story, cfg):
    s = scfg(cfg)
    meta = story.get("ai_meta") or {}
    lang_word = {"hindi": "Hindi", "hinglish": "Hindi", "english": "English"}[s["language"]]
    base_tags = s.get("hashtags") or ["#kidsstory", "#moralstory", "#storytime", "#kidsvideo", "#bedtimestory",
                                      "#hindikahaniya", "#cartoon", "#shorts"]
    title = meta.get("youtube_title") or f"{story['title']} | {lang_word} Kids Story #shorts"
    if len(title) > 95:
        title = title[:92] + "..."
    desc = meta.get("youtube_description") or (
        f"{story['title']} ({story['title_en']})\n\nMoral: {story['moral']}\n\n"
        f"Fun, colourful short stories for little kids every day on {s['channel_name']}.\n"
        + " ".join(base_tags))
    tags = (meta.get("youtube_tags") or []) + list(story.get("tags", [])) + [
        "kids story", "moral story", f"{lang_word.lower()} kids story", "story for kids", "cartoon story", s["channel_name"]]
    tags = [t.lstrip("#")[:60] for t in dict.fromkeys(tags)][:20]
    ig = meta.get("instagram_caption") or f"{story['title']} ✨\nMoral: {story['moral']}\n\n" + " ".join(base_tags)
    return {"youtube_title": title, "youtube_description": desc, "youtube_tags": tags, "instagram_caption": ig}


# ----------------------------------------------------------------------------- the daily run
def run_story(args, cfg, posted, save_posted):
    s = scfg(cfg)
    story = None
    if args.topic is None:
        story = gemini_story(s, posted)
    if story is None:
        story = bundled_story(load_stories(), posted, s["language"], args.topic)
    log.info(f"Today's story: {story['title']} ({story['source']}, {len(story['scenes'])} scenes, {s['language']})")
    stamp = now_ist().strftime("%Y-%m-%d")
    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / f"story-{stamp}-{story['id']}.mp4"
    reel = build_story_reel(story, cfg, OUTPUT / "work", out)
    caps = story_captions(story, cfg)
    (OUTPUT / "caption.txt").write_text(caps["instagram_caption"], encoding="utf-8")
    (OUTPUT / "youtube.json").write_text(json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT / "story.json").write_text(json.dumps({k: v for k, v in story.items() if k != "ai_meta"}, indent=2,
                                                  ensure_ascii=False), encoding="utf-8")
    if args.no_post:
        log.info(f"--no-post: video is at {out}")
        return 0
    p = cfg.get("posting", {})
    ig_on = s.get("instagram", p.get("instagram", True))
    yt_on = s.get("youtube", p.get("youtube", True))
    record = {"topic_id": story["id"], "type": "story", "hook": story["title"],
              "date": now_ist().isoformat(timespec="minutes"), "instagram": None, "youtube": None, "errors": []}
    if yt_on:
        try:
            from .youtube import upload_short
            record["youtube"] = upload_short(out, caps["youtube_title"], caps["youtube_description"], caps["youtube_tags"],
                                             p.get("youtube_privacy", "public"), s.get("youtube_category", "1"),
                                             made_for_kids=bool(s.get("made_for_kids", True)))
        except Exception as e:
            log.error(f"YouTube FAILED: {e}")
            record["errors"].append(f"youtube: {e}")
    if ig_on:
        try:
            from .instagram import Instagram
            record["instagram"] = Instagram().publish_reel(out, caps["instagram_caption"], p.get("share_to_feed", True),
                                                           p.get("video_host", "auto"), f"story-{stamp}")
        except Exception as e:
            log.error(f"Instagram FAILED: {e}")
            record["errors"].append(f"instagram: {e}")
    wanted = [k for k, on in (("youtube", yt_on), ("instagram", ig_on)) if on]
    record["success"] = any(record[k] for k in wanted) if wanted else False
    posted["posts"].append(record)
    save_posted(posted)
    if not record["success"]:
        log.error("Nothing was posted today. The video is saved in the run's 'reel' download (Artifacts).")
        return 1
    log.info("Done! " + ", ".join(k for k in wanted if record[k]) + " posted.")
    return 2 if record["errors"] else 0
