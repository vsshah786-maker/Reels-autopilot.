"""Draws the text screens (transparent PNGs) that go on top of the background.
Each content type has its own look:
  tip   -> numbered tips on a dark frosted card
  fact  -> "FACT 1" label + text
  quote -> big serif quote, centred, no card
  find  -> "BUDGET FIND" tag + white card with dark text
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .common import ASSETS

W, H = 1080, 1920
SAFE_X = 90           # keep text away from edges
SAFE_RIGHT = 150      # Instagram's like/comment buttons sit on the right
FONTS = ASSETS / "fonts"


def font(name, size, variation=None):
    f = ImageFont.truetype(str(FONTS / name), size)
    if variation:
        try:
            f.set_variation_by_name(variation)
        except Exception:
            pass
    return f


def serif(size, bold=True, italic=False):
    return font("PlayfairDisplay-Italic.ttf" if italic else "PlayfairDisplay.ttf", size, "Bold" if bold else "Regular")


def sans(size, weight="Medium"):
    return font(f"Poppins-{weight}.ttf", size)


def hex_rgba(h, a=255):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def balanced(draw, text, fnt, max_w):
    """Wrap text so lines are similar length (no lonely last word)."""
    best = wrap(draw, text, fnt, max_w)
    n = len(best)
    if n < 2:
        return best
    w = max_w
    while w > max_w * 0.55:
        w -= 20
        trial = wrap(draw, text, fnt, w)
        if len(trial) != n:
            break
        best = trial
    return best


def fit(draw, text, maker, start, max_w, max_lines, min_size=34):
    size = start
    while size > min_size:
        f = maker(size)
        lines = balanced(draw, text, f, max_w)
        if len(lines) <= max_lines and all(draw.textlength(l, font=f) <= max_w for l in lines):
            return f, lines
        size -= 4
    f = maker(min_size)
    return f, wrap(draw, text, f, max_w)


def text_block(img, lines, fnt, cx, top, fill, line_gap=1.18, shadow=True, align="center"):
    d = ImageDraw.Draw(img)
    asc, desc = fnt.getmetrics()
    lh = int((asc + desc) * line_gap)
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        for i, l in enumerate(lines):
            w = sd.textlength(l, font=fnt)
            x = cx - w / 2 if align == "center" else cx
            sd.text((x + 3, top + i * lh + 4), l, font=fnt, fill=(0, 0, 0, 150))
        sh = sh.filter(ImageFilter.GaussianBlur(7))
        img.alpha_composite(sh)
    for i, l in enumerate(lines):
        w = d.textlength(l, font=fnt)
        x = cx - w / 2 if align == "center" else cx
        d.text((x, top + i * lh), l, font=fnt, fill=fill)
    return lh * len(lines)


def pill(img, text, cx, cy, bg, fg, size=34, pad=(30, 14)):
    d = ImageDraw.Draw(img)
    f = sans(size, "SemiBold")
    tw = d.textlength(text, font=f)
    asc, desc = f.getmetrics()
    w, h = tw + pad[0] * 2, asc + desc + pad[1] * 2
    box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
    d.rounded_rectangle(box, radius=h / 2, fill=bg)
    d.text((cx - tw / 2, box[1] + pad[1] - 2), text, font=f, fill=fg)
    return h


def card(img, box, color, radius=44):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=color)
    img.alpha_composite(layer)


def handle_tag(img, handle):
    if not handle:
        return
    d = ImageDraw.Draw(img)
    f = sans(32, "Medium")
    w = d.textlength(handle, font=f)
    # top of the screen: the bottom is covered by Instagram's caption and buttons
    d.text((W / 2 - w / 2, 250), handle, font=f, fill=(255, 255, 255, 210))


def shade(path, darken=0.28):
    """Static darkening layer (stronger at top and bottom) so white text is always readable."""
    import numpy as np
    y = np.arange(H, dtype=float)
    edge = np.clip(1 - y / 520, 0, None) * 90 + np.clip((y - 1350) / 570, 0, None) * 70
    a = np.clip(255 * darken + edge, 0, 235).astype(np.uint8)
    arr = np.zeros((H, W, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = 12, 6, 10
    arr[..., 3] = a[:, None]
    Image.fromarray(arr, "RGBA").save(path)
    return path


LABELS = {"tip": "BEAUTY TIP", "fact": "DID YOU KNOW?", "quote": "", "find": "BUDGET FIND"}


def render_screens(topic, cfg, outdir: Path):
    """Returns list of dicts: {png, text(for voice), base_seconds, role}"""
    outdir.mkdir(parents=True, exist_ok=True)
    th = cfg["video"].get("theme", {})
    accent = hex_rgba(th.get("accent", "#F7C6D0"))
    white = hex_rgba(th.get("text", "#FFFFFF"))
    card_c = hex_rgba(th.get("card", "#1A1018"), int(255 * float(th.get("card_opacity", 0.55))))
    handle = cfg["page"].get("handle", "")
    v = cfg["video"]
    typ = topic.get("type", "tip")
    maxw = W - SAFE_X - SAFE_RIGHT
    cx = SAFE_X + maxw / 2
    screens = []

    def new():
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # ---------- hook / quote screen ----------
    img = new()
    d = ImageDraw.Draw(img)
    if typ == "quote":
        qf = serif(260, True, True)
        d.text((cx - 70, 430), "\u201c", font=qf, fill=accent)
        f, lines = fit(d, topic["hook"], lambda s: serif(s, False, True), 92, maxw, 6)
        asc, desc = f.getmetrics()
        hgt = int((asc + desc) * 1.25) * len(lines)
        text_block(img, lines, f, cx, 960 - hgt / 2 + 40, white, line_gap=1.25)
        d.line([cx - 60, 960 + hgt / 2 + 90, cx + 60, 960 + hgt / 2 + 90], fill=accent, width=4)
        secs = max(6.0, 2.2 + len(topic["hook"].split()) * 0.42)
    else:
        label = LABELS.get(typ, "")
        f, lines = fit(d, topic["hook"], lambda s: serif(s, True), 112, maxw, 5)
        asc, desc = f.getmetrics()
        hgt = int((asc + desc) * 1.15) * len(lines)
        top = 900 - hgt / 2
        if label:
            pill(img, label, cx, top - 90, accent, (40, 20, 30, 255))
        text_block(img, lines, f, cx, top, white, line_gap=1.15)
        d.line([cx - 50, top + hgt + 50, cx + 50, top + hgt + 50], fill=accent, width=5)
        secs = float(v.get("hook_seconds", 3.2))
    handle_tag(img, handle)
    p = outdir / "screen_00.png"
    img.save(p)
    screens.append({"png": p, "text": topic["hook"], "base_seconds": secs, "role": "hook"})

    # ---------- point screens ----------
    tips = topic["tips"][: int(v.get("max_tips", 4))]
    for i, tip in enumerate(tips, 1):
        img = new()
        d = ImageDraw.Draw(img)
        is_note = typ == "find" and tip.lower().startswith("tip:")
        if typ == "find":
            body = tip[4:].strip() if is_note else tip
            f, lines = fit(d, body, lambda s: sans(s, "SemiBold"), 64, maxw - 100, 5)
            asc, desc = f.getmetrics()
            hgt = int((asc + desc) * 1.2) * len(lines)
            top = 1000 - hgt / 2
            card(img, [SAFE_X, top - 150, SAFE_X + maxw, top + hgt + 70], (255, 250, 252, 238))
            tag = "SHOPPING TIP" if is_note else f"FIND #{i}"
            pill(img, tag, cx, top - 150, accent, (60, 25, 40, 255))
            text_block(img, lines, f, cx, top - 20, (45, 25, 35, 255), line_gap=1.2, shadow=False)
        else:
            f, lines = fit(d, tip, lambda s: sans(s, "SemiBold"), 66, maxw - 90, 5)
            asc, desc = f.getmetrics()
            hgt = int((asc + desc) * 1.2) * len(lines)
            top = 1010 - hgt / 2
            card(img, [SAFE_X, top - 210, SAFE_X + maxw, top + hgt + 75], card_c)
            if typ == "fact":
                pill(img, f"FACT {i}", cx, top - 115, accent, (40, 20, 30, 255))
            else:
                nf = serif(110, True, True)
                num = f"{i:02d}"
                nw = d.textlength(num, font=nf)
                d.text((cx - nw / 2, top - 205), num, font=nf, fill=accent)
            text_block(img, lines, f, cx, top + 5, white, line_gap=1.2)
        handle_tag(img, handle)
        p = outdir / f"screen_{i:02d}.png"
        img.save(p)
        secs = max(float(v.get("tip_seconds", 3.6)), 1.6 + len(tip.split()) * 0.28)
        screens.append({"png": p, "text": tip.replace("Tip:", "Tip."), "base_seconds": secs, "role": "point"})

    # ---------- CTA ----------
    img = new()
    d = ImageDraw.Draw(img)
    f, lines = fit(d, topic["cta"], lambda s: serif(s, True), 96, maxw, 4)
    asc, desc = f.getmetrics()
    hgt = int((asc + desc) * 1.15) * len(lines)
    top = 880 - hgt / 2
    text_block(img, lines, f, cx, top, white, line_gap=1.15)
    pill(img, f"Follow {handle}" if handle else "Follow for more", cx, top + hgt + 110, accent, (40, 20, 30, 255), size=36)
    p = outdir / f"screen_{len(screens):02d}.png"
    img.save(p)
    screens.append({"png": p, "text": topic["cta"], "base_seconds": float(v.get("cta_seconds", 3.0)), "role": "cta"})
    return screens
