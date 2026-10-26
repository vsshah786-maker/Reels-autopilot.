import json
import random
import re

import requests

from .common import log, secret

TYPE_EMOJI = {"tip": "💄", "fact": "💡", "quote": "🌸", "find": "🛍️"}


def _hashtags(topic, cfg, limit):
    tags = []
    for t in list(topic.get("hashtags", [])) + list(cfg["page"].get("base_hashtags", [])):
        t = "#" + re.sub(r"[^\w]", "", str(t).lstrip("#"))
        if len(t) > 1 and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    return tags[:limit]


def template_caption(topic, cfg, credits=None):
    page = cfg["page"]
    ccfg = cfg.get("captions", {})
    bullets = ccfg.get("emoji_bullets") or ["✨"]
    rnd = random.Random(str(topic["id"]))
    lines = [f"{TYPE_EMOJI.get(topic['type'], '✨')} {topic['hook']}", ""]
    if topic["type"] == "quote":
        lines += ["Read it twice. Save it for the day you need it. 🤍", ""]
    else:
        for tip in topic["tips"]:
            lines.append(f"{rnd.choice(bullets)} {tip}")
        lines.append("")
    lines.append(f"👉 {topic['cta']}")
    lines.append(page.get("follow_line", "").format(handle=page.get("handle", "")))
    tags = _hashtags(topic, cfg, int(ccfg.get("max_hashtags", 15)))
    caption = "\n".join(lines).strip() + "\n\n" + " ".join(tags)
    if credits:
        caption += "\n\n" + "Credits: " + "; ".join(credits)
    return caption[:2150], tags


def gemini_caption(topic, cfg):
    key = secret("GEMINI_API_KEY")
    if not key:
        return None
    model = (cfg.get("captions") or {}).get("gemini_model", "gemini-2.5-flash")
    prompt = (
        "Write an Instagram Reel caption for an Indian beauty page. Friendly Hinglish-friendly English, "
        "max 70 words, 2-4 emojis, end with a call to action. No hashtags. Do not invent prices or brand claims.\n"
        f"Reel type: {topic['type']}\nHook: {topic['hook']}\nPoints: {'; '.join(topic['tips'])}\nCTA: {topic['cta']}"
    )
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=40,
        )
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return txt if 20 < len(txt) < 1500 else None
    except Exception as e:  # never let AI captions break posting
        log.warning(f"Gemini caption failed, using the template caption instead ({e.__class__.__name__})")
        return None


def build_captions(topic, cfg, credits=None):
    caption, tags = template_caption(topic, cfg, credits)
    if (cfg.get("captions") or {}).get("use_gemini"):
        ai = gemini_caption(topic, cfg)
        if ai:
            caption = ai + "\n\n" + " ".join(tags) + (("\n\nCredits: " + "; ".join(credits)) if credits else "")
    title = topic["hook"].strip()
    suffix = " #Shorts"
    if len(title) + len(suffix) > 100:
        title = title[: 100 - len(suffix) - 1].rstrip() + "…"
    yt_title = title + suffix
    yt_desc = caption.replace("#Shorts", "") + "\n#Shorts"
    yt_tags = [t.lstrip("#") for t in tags][:15]
    return {"instagram_caption": caption, "youtube_title": yt_title,
            "youtube_description": yt_desc[:4900], "youtube_tags": yt_tags}
