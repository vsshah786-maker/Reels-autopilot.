import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
CACHE = ROOT / ".cache"
POSTED_FILE = ROOT / "posted.json"
IST = timezone(timedelta(hours=5, minutes=30))

log = logging.getLogger("autopilot")


def setup_logging():
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(fmt)
        log.addHandler(h)
        fh = logging.FileHandler(ROOT / "logs" / "autopilot.log", encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)


def load_env_file():
    """For running on your laptop: reads secrets from a file called .env (never upload it)."""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topics():
    with open(ROOT / "topics.yaml", encoding="utf-8") as f:
        topics = yaml.safe_load(f) or []
    ids = set()
    for t in topics:
        t.setdefault("type", "tip")
        t.setdefault("tips", [])
        t.setdefault("search", [])
        t.setdefault("hashtags", [])
        t.setdefault("cta", "Follow for more")
        if t["id"] in ids:
            raise ValueError(f"topics.yaml: id {t['id']} is used twice - every id must be different")
        ids.add(t["id"])
        t["tips"] = [str(x) for x in (t["tips"] or [])]
    return topics


def load_posted():
    if POSTED_FILE.exists():
        try:
            return json.loads(POSTED_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("posted.json was unreadable - starting a fresh list")
    return {"posts": []}


def save_posted(data):
    POSTED_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def now_ist():
    return datetime.now(IST)


def secret(name, default=None):
    v = os.environ.get(name, "").strip()
    return v or default
