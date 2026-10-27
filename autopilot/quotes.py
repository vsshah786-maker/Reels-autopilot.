"""QUOTES mode (content_mode: quotes in config.yaml)  -  the default for @dhruviverse.official.

One calm 8-14 s aesthetic reel a day:
  a line (self-love / confidence / gentle girl humor / soft motivation) - free Gemini writes a fresh one daily,
  or the next one from the bundled quotes.yaml
  -> ONE continuous pretty stock video clip that fits the mood (sky, flowers, coffee, rain, ocean ...), soft warm look
  -> the line in elegant serif text, appearing line by line with a soft fade, small @handle at the bottom
  -> soft copyright-free music (voice off by default; quotes: voice: on reads it aloud).
Posts to Instagram (and YouTube once connected; YouTube never fails the run).
"""
import json
import random
import re
import textwrap

import requests
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .common import ASSETS, OUTPUT, ROOT, log, now_ist, secret
from . import story as S
from . import beauty as B

W, H = S.W, S.H
QUERY_WORDS = ["clouds", "pink sky", "sunset", "sea sunset", "flowers", "cherry blossom", "tulips", "daisy", "sunflower",
               "dandelion", "coffee", "tea", "book", "candle", "rain window", "rain", "ocean", "beach", "moon",
               "stars night", "sky", "butterfly", "grass field", "autumn leaves", "lake", "city night", "woman walking",
               "girl walking"]
PEOPLE_QUERIES = {"woman walking", "girl walking"}
MOOD_FALLBACK = {"humor": ["coffee", "tea", "clouds", "sunset"], "confidence": ["sunset", "sea sunset", "beach", "city night"],
                 "self_love": ["pink sky", "flowers", "cherry blossom", "tulips"], "motivation": ["sunset", "sea sunset", "sky"]}
# quotes are over calm footage: "background"/"loop" tags are fine here, people's faces and text are not
QUOTE_BAD = (B._BAD_TAGS - {"background", "backdrop", "loop", "abstract", "particles"}) | {
    "face", "portrait", "selfie", "smile", "people", "crowd", "couple", "kiss", "wedding", "funeral", "storm", "fire",
    "flood", "war", "traffic", "drone", "aerial"}


def qcfg(cfg):
    s = B.bcfg(cfg)
    s.update({"channel_name": (cfg.get("beauty") or {}).get("channel_name", "@dhruviverse.official"),
              "voice": None, "voice_on": False, "music_volume": 0.55, "min_seconds": 8, "max_seconds": 14,
              "font": "PlayfairDisplay.ttf", "font_weight": "SemiBold", "font_size": 74, "line_chars": 23,
              "text_y": 0.44, "use_gemini_quote": True, "check_clips_with_gemini": True, "max_clip_checks": 4,
              "hashtags": ["#aestheticquotes", "#selflove", "#quotesdaily", "#dhruviverse"],
              "follow_line": "Follow @dhruviverse.official for daily self-love 💗"})
    q = dict(cfg.get("quotes") or {})
    if str(q.get("voice", "off")).strip().lower() in ("on", "true", "yes"):
        q["voice_on"] = True
    q.pop("voice", None)
    s.update(q)
    return s


# ----------------------------------------------------------------------------- lines
def load_quotes():
    p = ROOT / "quotes.yaml"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def bundled_quote(quotes, posted, want_id=None):
    if not quotes:
        raise RuntimeError("quotes.yaml is missing or empty")
    done = {str(p.get("topic_id")) for p in posted.get("posts", []) if p.get("success")}
    if want_id is not None:
        pick = [x for x in quotes if str(x["id"]) == str(want_id).replace("quote-", "")]
        if not pick:
            raise RuntimeError(f"No line with id {want_id} in quotes.yaml")
        q = pick[0]
    else:
        left = [x for x in quotes if f"quote-{x['id']}" not in done]
        q = left[0] if left else quotes[len(done) % len(quotes)]
    q = dict(q)
    q["id"] = f"quote-{q['id']}"
    q["source"] = "quotes.yaml"
    return q


SCHEMA = {"type": "OBJECT", "properties": {
    "category": {"type": "STRING", "enum": ["self_love", "confidence", "humor", "motivation"]},
    "text": {"type": "STRING"}, "mood": {"type": "STRING"},
    "queries": {"type": "ARRAY", "items": {"type": "STRING"}},
    "caption": {"type": "STRING"}, "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["category", "text", "mood", "queries", "caption", "hashtags"]}


def gemini_quote(s, posted, quotes):
    key = secret("GEMINI_API_KEY")
    if not key or not s.get("use_gemini_quote", True):
        return None
    recent = [p.get("hook") for p in posted.get("posts", [])[-60:] if p.get("hook")]
    day = now_ist()
    cat = ["self_love", "confidence", "humor", "self_love", "motivation", "humor", "confidence"][day.weekday()]
    ex = [{k: x[k] for k in ("category", "text", "mood", "queries", "caption", "hashtags") if k in x}
          for x in quotes if x.get("category") == cat][:3]
    prompt = f"""Write ONE new ORIGINAL short line for the aesthetic Instagram page {s['channel_name']}
(Indian girls and women 16-35). Category today: {cat}
(self_love = gentle and warm; confidence = bold and uplifting; humor = relatable, kind girl humor, setup and punchline;
motivation = soft motivation). 6-25 words. Not a famous quote, no lyrics, no author. Plain text, no emojis, no hashtags.
You may put "\\n" where the line should break on screen (2-3 short lines; for humor put the punchline on its own line).
Do NOT repeat or closely copy any of these: {json.dumps(recent + [x['text'] for x in quotes][:80], ensure_ascii=False)}
queries: 2 stock video searches for ONE calm, pretty background clip matching the mood, ONLY from {json.dumps(QUERY_WORDS)}.
caption: 2 short engaging lines (question / tag a friend / save prompt) with 1-2 emojis. hashtags: 8-10, include #dhruviverse.
Examples of the exact format: {json.dumps(ex, ensure_ascii=False)}"""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json", "responseSchema": SCHEMA}}
    import os
    found = S.gemini_text_models(key) if not os.environ.get("GEMINI_PROXY_TOKEN") else \
        sorted(B.gemini_vision_models(key)[:-2], key=lambda n: "lite" in n)
    for model in dict.fromkeys([s.get("gemini_model", "gemini-3.8-flash")] + found + ["gemini-flash-latest"]):
        try:
            r = B._gemini_call(model, body, key, timeout=60)
            if r.status_code != 200:
                log.info(f"    Gemini {model}: HTTP {r.status_code}")
                continue
            d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            d["text"] = d["text"].replace("\\n", "\n").strip().strip('"')
            n = len(d["text"].split())
            if not 4 <= n <= 30:
                raise ValueError(f"{n} words")
            if any(d["text"].lower()[:40] == (t or "").lower()[:40] for t in recent):
                raise ValueError("repeat")
            d["queries"] = [q for q in d.get("queries", []) if q in QUERY_WORDS] or MOOD_FALLBACK.get(d["category"], ["sky"])
            d["id"] = "quote-ai-" + day.strftime("%Y%m%d")
            d["source"] = f"Gemini {model}"
            log.info(f"    Gemini ({model}) wrote today's line")
            return d
        except Exception as e:
            log.info(f"    Gemini {model} failed: {str(e)[:120]}")
    log.warning("    Gemini could not write a line today - using quotes.yaml")
    return None


# ----------------------------------------------------------------------------- clip
class QuoteClips(B.ClipFinder):
    def __init__(self, s, seed):
        super().__init__(s, seed)
        self.bad = QUOTE_BAD

    def score(self, c, q, need):
        tags = c["tags"]
        if tags & self.bad or (c["id"].startswith("pxb") and int(c["id"][3:]) in B.BLOCKED):
            return None
        if not all(B._has(tags, w) for w in B._kw(q)):
            return None
        best = max(c["renditions"], key=lambda v: v["width"] * v["height"])
        sc = 3.0 if best["height"] > best["width"] else 0.0
        sc += 2.0 if c["dur"] >= need else (0.0 if c["dur"] >= need / 1.4 else -4)
        sc += 1.0 if min(best["width"], best["height"]) >= 1080 else -2
        return sc + random.Random(f"{self.seed}{c['id']}").random() * 2.5   # variety day to day


def check_calm(path, mood, key_ok, checker):
    """Gemini: is this a calm pretty clip with no text/logo and no close-up face? (None = no Gemini)"""
    if not key_ok or not checker.ok():
        return None
    img = checker.frames(path)
    if not img:
        return None
    if checker.models is None:
        checker.models = B.gemini_vision_models(checker.key)
    prompt = (f"3 frames from one stock video that will sit behind a short quote on an aesthetic Instagram reel "
              f"(mood: {mood}). ok = true only if it is calm and pretty, matches the mood, has NO visible text, letters, "
              f"logos or watermarks, and NO close-up human face. shows = what it shows in max 10 words.")
    body = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": img}}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json",
                                 "responseSchema": {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"},
                                                    "shows": {"type": "STRING"}}, "required": ["ok", "shows"]}}}
    for model in list(checker.models)[:6]:
        try:
            r = B._gemini_call(model, body, checker.key, timeout=60)
            if r.status_code != 200:
                if r.status_code in (400, 403, 404, 429):
                    checker.models.remove(model)
                continue
            d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            checker.left -= 1
            return bool(d.get("ok")), str(d.get("shows", ""))[:80]
        except Exception:
            continue
    return None


def find_clip(q, s, need, seed):
    finder = QuoteClips(s, seed)
    checker = B.ClipChecker(s)
    queries = list(q.get("queries") or []) + MOOD_FALLBACK.get(q.get("category"), []) + ["clouds", "sunset", "flowers"]
    if not checker.ok():   # clips with people need Gemini's eye; without it stay with nature/objects
        queries = [x for x in queries if x not in PEOPLE_QUERIES]
    cands = finder.ranked(list(dict.fromkeys(queries)), need, limit=8)
    first = None
    for c, query in cands:
        try:
            path = finder.download(c)
        except Exception as e:
            log.warning(f"    clip download failed: {e}")
            continue
        res = check_calm(path, q.get("mood", ""), True, checker)
        if res is None or res[0]:
            log.info(f"    clip {c['id']} for '{query}'" + (f" (Gemini ok: {res[1]})" if res else " (tags)"))
            return path, c
        log.info(f"    clip {c['id']} skipped by Gemini: {res[1]}")
        first = first or (path, c)
    return first or (None, None)


# ----------------------------------------------------------------------------- text
def _font(s, size):
    f = ImageFont.truetype(str(ASSETS / "fonts" / s["font"]), size)
    try:
        f.set_variation_by_name(s.get("font_weight", "Medium"))
    except Exception:
        pass
    return f


def wrap_lines(text, n, font=None, max_w=W * 0.84):
    """Keep the line breaks written in the line; wrap the rest by real pixel width (or n characters)."""
    out = []
    for part in text.replace("\\n", "\n").split("\n"):
        words, cur = part.split(), ""
        for w in words:
            t = (cur + " " + w).strip()
            fits = font.getlength(t) <= max_w if font else len(t) <= n
            if cur and not fits:
                out.append(cur)
                cur = w
            else:
                cur = t
        if cur:
            out.append(cur)
    # no lonely last word: pull one word down from the line above
    for i in range(1, len(out)):
        if len(out[i].split()) == 1 and len(out[i - 1].split()) >= 3 and "\n" not in text:
            a = out[i - 1].split()
            out[i - 1], out[i] = " ".join(a[:-1]), a[-1] + " " + out[i]
    return out


def line_pngs(text, s, workdir):
    size = int(s["font_size"])
    f = _font(s, size)
    parts = [p for p in text.replace("\\n", "\n").split("\n") if p.strip()]
    if len(parts) > 1:   # line breaks written by hand: a slightly smaller font beats breaking "12 / steps"
        for sz in range(size, int(size * 0.8) - 1, -2):
            fz = _font(s, sz)
            if all(fz.getlength(p.strip()) <= W * 0.84 for p in parts):
                size, f = sz, fz
                break
    lines = wrap_lines(text, int(s["line_chars"]), f)
    while len(lines) > 6 and size > 50:
        size -= 6
        f = _font(s, size)
        lines = wrap_lines(text, int(s["line_chars"]), f)
    lh = int(size * 1.34)
    block = lh * len(lines)
    top = int(H * float(s["text_y"]) - block / 2)
    pngs = []
    for i, ln in enumerate(lines):
        f2 = f if f.getlength(ln) <= W * 0.88 else _font(s, int(size * W * 0.88 / f.getlength(ln)))
        img = Image.new("RGBA", (W, lh + 40), (0, 0, 0, 0))
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        x = (W - f2.getlength(ln)) / 2
        ImageDraw.Draw(sh).text((x + 2, 24), ln, font=f2, fill=(0, 0, 0, 210))
        sh = sh.filter(ImageFilter.GaussianBlur(7))
        img = Image.alpha_composite(img, sh)
        ImageDraw.Draw(img).text((x, 20), ln, font=f2, fill=(255, 251, 246, 255))
        p = workdir / f"line_{i}.png"
        img.save(p)
        pngs.append((p, top + i * lh - 20))
    return pngs


def handle_png(s, workdir):
    f = ImageFont.truetype(str(ASSETS / "fonts" / "Poppins-Medium.ttf"), 34)
    t = s["channel_name"]
    img = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x = (W - f.getlength(t)) / 2
    ImageDraw.Draw(sh).text((x + 1, 22), t, font=f, fill=(0, 0, 0, 170))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(4)))
    ImageDraw.Draw(img).text((x, 20), t, font=f, fill=(255, 255, 255, 225))
    p = workdir / "handle.png"
    img.save(p)
    return p


def shade_png(workdir):
    """soft dark band behind the text so it is always readable (strongest in the middle)"""
    import numpy as np
    y = np.linspace(0, 1, H)[:, None]
    a = 0.38 * np.exp(-((y - 0.45) / 0.22) ** 2) + 0.12
    arr = np.zeros((H, W, 4), dtype=np.uint8)
    arr[..., 3] = (a * 255).astype(np.uint8).repeat(W, axis=1)
    p = workdir / "shade.png"
    Image.fromarray(arr, "RGBA").save(p)
    return p


# ----------------------------------------------------------------------------- build
def build_quote_reel(q, s, workdir, out):
    import shutil
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    text = q["text"].replace("\\n", "\n")
    words = len(text.split())
    voice = None
    if s.get("voice_on"):
        mp3 = workdir / "voice.mp3"
        S.speak(re.sub(r"\s+", " ", text), mp3, s.get("quote_voice", B.ENGLISH_VOICE), "+0%", "+0Hz")
        voice = mp3
    lines = wrap_lines(text, int(s["line_chars"]), _font(s, int(s["font_size"])))
    reveal = 0.6 + 0.7 * (len(lines) - 1)
    secs = reveal + 1.2 + words / 1.9          # time to read it twice
    if voice:
        secs = max(secs, S.probe_dur(voice) + 2.5)
    secs = max(float(s["min_seconds"]), min(float(s["max_seconds"]), secs))
    log.info(f"    {len(lines)} lines, {words} words -> {secs:.1f}s")
    clip, c = find_clip(q, s, secs, q.get("seed", 0))
    bg = workdir / "bg.mp4"
    if clip:
        B.video_scene_clip(clip, secs, int(s["fps"]), bg, dict(s, clip_saturation=1.0))
    else:
        g = S.Painter(s, workdir)._gradient("", 0, 0)
        S.scene_clip(g, secs, int(s["fps"]), "in", bg)
    pngs = line_pngs(text, s, workdir)
    inputs = ["-i", bg, "-loop", "1", "-i", shade_png(workdir), "-loop", "1", "-i", handle_png(s, workdir)]
    fc = ["[0:v]colorbalance=rs=0.04:gs=0.01:bs=-0.04:rm=0.03:bm=-0.03,eq=saturation=0.92:contrast=0.97:brightness=0.01,"
          "gblur=sigma=1.2,vignette=PI/5[bgv]",
          "[bgv][1:v]overlay=0:0:shortest=1[v0]",
          f"[v0][2:v]overlay=0:{int(H * 0.86)}:shortest=1[v1]"]
    last = "[v1]"
    for i, (p, y) in enumerate(pngs):
        t0 = 0.6 + 0.7 * i
        inputs += ["-loop", "1", "-t", f"{secs:.2f}", "-i", p]
        fc.append(f"[{3 + i}:v]format=rgba,fade=in:st={t0:.2f}:d=0.8:alpha=1[l{i}]")
        fc.append(f"{last}[l{i}]overlay=0:{y}:shortest=1[v{i + 2}]")
        last = f"[v{i + 2}]"
    fc.append(f"{last}fade=in:st=0:d=0.5,fade=out:st={secs - 0.7:.2f}:d=0.7,format=yuv420p[v]")
    ai = 3 + len(pngs)
    music = S.pick_music(dict(s, music_glob=s.get("music_glob", "*")), workdir, secs, q.get("seed", 0))
    inputs += ["-stream_loop", "-1", "-i", music]
    mv = float(s["music_volume"])
    if voice:
        inputs += ["-i", voice]
        fc.append(f"[{ai}:a]volume={mv * 0.5},aformat=channel_layouts=stereo[m]")
        fc.append(f"[{ai + 1}:a]adelay=700:all=1,volume=1.5,aformat=channel_layouts=stereo[vo]")
        fc.append(f"[m][vo]amix=inputs=2:duration=first:normalize=0,afade=t=in:d=0.8,"
                  f"afade=t=out:st={secs - 1.2:.2f}:d=1.2,alimiter=limit=0.95[a]")
    else:
        fc.append(f"[{ai}:a]volume={mv},aformat=channel_layouts=stereo,afade=t=in:d=1.0,"
                  f"afade=t=out:st={secs - 1.5:.2f}:d=1.5[a]")
    S.ff(inputs + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{secs:.2f}",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "6000k", "-bufsize", "12000k",
                   "-pix_fmt", "yuv420p", "-r", int(s["fps"]), "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
                   "-movflags", "+faststart", out])
    log.info(f"Reel ready: {out} ({secs:.1f}s, {out.stat().st_size / 1e6:.1f} MB)")
    return {"clip": c["id"] if c else None, "credit": c["credit"] if c else None, "seconds": secs}


def quote_captions(q, s):
    tags = list(dict.fromkeys(list(q.get("hashtags") or []) + list(s.get("hashtags") or [])))[:12]
    tags = [t if t.startswith("#") else "#" + t.replace(" ", "") for t in tags]
    line = re.sub(r"\s*\n\s*", " ", q["text"].replace("\\n", "\n")).strip()
    ig = f"{line}\n\n{(q.get('caption') or '').strip()}\n\n{s['follow_line']}\n\n" + " ".join(tags)
    title = (line[:80] + "…" if len(line) > 80 else line) + " #shorts"
    return {"youtube_title": title, "youtube_description": ig, "youtube_tags": [t.lstrip("#") for t in tags],
            "instagram_caption": ig.replace("\n\n\n", "\n\n")}


def run_quotes(args, cfg, posted, save_posted):
    s = qcfg(cfg)
    quotes = load_quotes()
    q = gemini_quote(s, posted, quotes) if args.topic is None else None
    if q is None:
        q = bundled_quote(quotes, posted, args.topic)
    q["seed"] = int(now_ist().strftime("%j")) * 31 + len(q["text"])
    log.info(f"Today's line ({q.get('category')}, {q['source']}): {q['text']!r}")
    stamp = now_ist().strftime("%Y-%m-%d")
    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / f"quote-{stamp}-{q['id']}.mp4"
    info = build_quote_reel(q, s, OUTPUT / "work", out)
    q.update(info)
    caps = quote_captions(q, s)
    (OUTPUT / "caption.txt").write_text(caps["instagram_caption"], encoding="utf-8")
    (OUTPUT / "youtube.json").write_text(json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT / "script.json").write_text(json.dumps(q, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.no_post:
        log.info(f"--no-post: video is at {out}")
        return 0
    record = {"topic_id": q["id"], "type": "quote", "hook": q["text"],
              "date": now_ist().isoformat(timespec="minutes"), "instagram": None, "youtube": None, "errors": []}
    B.post_everywhere(out, caps, s, cfg, record, stamp)
    posted["posts"].append(record)
    save_posted(posted)
    if not record["success"]:
        log.error("Instagram did not post today. The video is saved in the run's 'reel' download (Artifacts).")
        return 1
    log.info("Done! Posted to Instagram" + (" and YouTube." if record["youtube"] not in (None, "skipped") else "."))
    return 0
