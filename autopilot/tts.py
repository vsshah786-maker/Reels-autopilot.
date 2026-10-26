"""Free AI voiceover using Microsoft Edge's online voices (edge-tts). No key, no cost.
If it fails for any reason the reel is made without voice (music only)."""
import asyncio
import subprocess
from pathlib import Path

from .common import log


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip() or 0)


def speak_all(texts, outdir: Path, voice="en-IN-NeerjaNeural", rate="+0%"):
    try:
        import edge_tts
    except ImportError:
        log.warning("edge-tts not installed - no voiceover")
        return None

    async def one(text, path):
        await edge_tts.Communicate(text, voice, rate=rate).save(str(path))

    async def run():
        paths = []
        for i, t in enumerate(texts):
            p = outdir / f"voice_{i:02d}.mp3"
            await asyncio.wait_for(one(t, p), timeout=60)
            paths.append(p)
        return paths

    try:
        paths = asyncio.run(run())
        return [(p, duration(p)) for p in paths]
    except Exception as e:
        log.warning(f"Voiceover failed ({e.__class__.__name__}: {e}) - making the reel with music only")
        return None
