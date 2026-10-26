"""Builds the 1080x1920 reel with ffmpeg: background per screen + text + transitions + music/voice."""
import random
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from .common import ASSETS, log
from .overlay import render_screens, shade
from .stock import get_backgrounds
from .tts import speak_all, duration

W, H = 1080, 1920


def ff(args, timeout=600):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-1500:])


def prep_image(src, dst):
    """Crop a photo to 9:16 and make it big (smooth slow zoom needs extra pixels)."""
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im = ImageOps.fit(im, (1620, 2880), Image.LANCZOS)
        im.save(dst, quality=93)
    return dst


def render_segment(bg, overlay_png, shade_png, secs, fps, out, idx):
    frames = int(round(secs * fps))
    text_in = ("[2:v]format=rgba,fade=in:st=0.12:d=0.5:alpha=1[tx];"
               "[b2][tx]overlay=x=0:y='if(lt(t,0.6),36*(1-t/0.6),0)':format=auto[o];"
               "[o]format=yuv420p,setsar=1[v]")
    if bg.kind == "video":
        clip_len = duration(bg.path)
        start = 0.0
        if clip_len > secs + 1:
            start = random.uniform(0, max(0.0, min(clip_len - secs - 0.5, 8)))
        inputs = ["-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", bg.path]
        bgf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},"
               f"eq=saturation=1.06:contrast=1.03,setsar=1[bg];")
    else:
        big = out.with_suffix(".bg.jpg")
        prep_image(bg.path, big)
        zin = idx % 2 == 0
        z = f"1.0+0.10*on/{frames}" if zin else f"1.10-0.10*on/{frames}"
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", big]
        bgf = (f"[0:v]scale=2160:3840,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
               f"d=1:s={W}x{H}:fps={fps},eq=saturation=1.06:contrast=1.03,setsar=1[bg];")
    fc = bgf + "[bg][1:v]overlay=0:0[b2];" + text_in
    ff(inputs + ["-loop", "1", "-i", shade_png, "-loop", "1", "-i", overlay_png,
                 "-filter_complex", fc, "-map", "[v]", "-frames:v", frames, "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", out])
    return out


def pick_music():
    tracks = [p for p in (ASSETS / "music").glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}]
    return random.choice(tracks) if tracks else None


def build_reel(topic, cfg, workdir: Path, out_path: Path):
    v, a = cfg["video"], cfg.get("audio", {})
    fps = int(v.get("fps", 30))
    T = float(v.get("transition_seconds", 0.45))
    trans = v.get("transition", "fade")
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    log.info("1/4 Drawing text screens")
    screens = render_screens(topic, cfg, workdir)
    shade_png = shade(workdir / "shade.png", float(v.get("theme", {}).get("darken", 0.28)))

    voices = None
    if a.get("voiceover"):
        log.info("    Making voiceover")
        voices = speak_all([s["text"] for s in screens], workdir, a.get("voice", "en-IN-NeerjaNeural"),
                           a.get("voice_rate", "+0%"))
    for i, s in enumerate(screens):
        s["seconds"] = s["base_seconds"]
        if voices:
            s["seconds"] = max(s["seconds"], voices[i][1] + 0.7)
        s["seconds"] += T  # overlap eaten by the transition

    log.info("2/4 Finding background clips")
    bgs = get_backgrounds(topic, len(screens), cfg)
    credits = sorted({b.credit for b in bgs if b.credit})

    log.info("3/4 Rendering screens")
    segs = []
    for i, (s, bg) in enumerate(zip(screens, bgs)):
        seg = workdir / f"seg_{i:02d}.mp4"
        try:
            render_segment(bg, s["png"], shade_png, s["seconds"], fps, seg, i)
        except Exception as e:
            log.warning(f"    background {bg} failed ({e}); using a plain gradient")
            from .stock import gradient
            render_segment(gradient(i, {}), s["png"], shade_png, s["seconds"], fps, seg, i)
        segs.append(seg)

    # transitions
    durs = [s["seconds"] for s in screens]
    total = sum(durs) - T * (len(durs) - 1)
    starts, acc = [], 0.0
    for d in durs:
        starts.append(acc)
        acc += d - T
    parts, inputs = [], []
    for sg in segs:
        inputs += ["-i", sg]
    last = "[0:v]"
    for k in range(1, len(segs)):
        off = sum(durs[:k]) - T * k
        lbl = f"[x{k}]"
        parts.append(f"{last}[{k}:v]xfade=transition={trans}:duration={T}:offset={off:.3f}{lbl}")
        last = lbl
    vf = ";".join(parts) + (";" if parts else "") + f"{last}format=yuv420p[vout]"

    log.info("4/4 Mixing audio and encoding")
    n = len(segs)
    afilters, amix_in = [], []
    music = pick_music() if a.get("music", True) else None
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        vol = a.get("music_volume_with_voice", 0.16) if voices else a.get("music_volume", 0.55)
        afilters.append(f"[{n}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume={vol},"
                        f"afade=t=in:st=0:d=0.6,afade=t=out:st={max(0, total - 1.4):.3f}:d=1.4[mus]")
        amix_in.append("[mus]")
    if voices:
        for i, (p, _) in enumerate(voices):
            inputs += ["-i", p]
            delay = int((starts[i] + (0.35 if i else 0.25)) * 1000)
            afilters.append(f"[{n + (1 if music else 0) + i}:a]aresample=48000,adelay={delay}|{delay},volume=1.25[vo{i}]")
            amix_in.append(f"[vo{i}]")
    if not amix_in:
        inputs += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        afilters.append(f"[{n}:a]anull[aout]")
    else:
        afilters.append("".join(amix_in) + f"amix=inputs={len(amix_in)}:duration=longest:normalize=0,"
                        f"atrim=0:{total:.3f},aresample=48000,alimiter=limit=0.95[aout]")
    fc = vf + ";" + ";".join(afilters)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ff(inputs + ["-filter_complex", fc, "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
                 "-c:v", "libx264", "-preset", "medium", "-profile:v", "high", "-crf", "21",
                 "-maxrate", "6M", "-bufsize", "12M", "-r", fps, "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                 "-movflags", "+faststart", out_path], timeout=900)
    log.info(f"    Reel ready: {out_path.name}  ({total:.1f} s, {out_path.stat().st_size / 1e6:.1f} MB)")
    return {"path": out_path, "seconds": round(total, 2), "credits": credits,
            "music": music.name if music else None, "voiceover": bool(voices)}
