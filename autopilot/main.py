"""Command line:
  python -m autopilot run              make today's reel and post it
  python -m autopilot run --no-post    only make the video (to check how it looks)
  python -m autopilot run --topic 7    use topic id 7
  python -m autopilot check            test that your keys/tokens work (posts nothing)
  python -m autopilot refresh-token    renew the 60-day Instagram token
"""
import argparse
import json
import os
import sys
import traceback

from .common import (OUTPUT, ROOT, load_config, load_env_file, load_posted, load_topics, log, now_ist,
                     save_posted, secret, setup_logging)


def cmd_run(args):
    cfg = load_config()
    mode = str(cfg.get("content_mode", "tips")).strip().lower()
    if mode == "illustrated":
        # backup pictures uploaded from a phone can be named x.jpg.jpeg: make a .jpg copy for this run
        import shutil
        _ill = ROOT / "assets" / "illustrated"
        if _ill.exists():
            for _p in list(_ill.glob("*.jpeg")) + list(_ill.glob("*.JPEG")):
                _t = _ill / (_p.name.split(".")[0] + ".jpg")
                if not _t.exists():
                    shutil.copy(_p, _t)
        from .illustrated import run_illustrated
        return run_illustrated(args, cfg, load_posted(), save_posted)
    if mode == "quotes":
        from .quotes import run_quotes
        return run_quotes(args, cfg, load_posted(), save_posted)
    if mode == "beauty":
        from .beauty import run_beauty
        return run_beauty(args, cfg, load_posted(), save_posted)
    if mode == "story":
        from .story import run_story
        return run_story(args, cfg, load_posted(), save_posted)
    topics = load_topics()
    posted = load_posted()
    from .content import pick_topic
    topic = pick_topic(topics, posted, cfg, args.topic)
    if not topic:
        return 0
    log.info(f"Today's reel: #{topic['id']} [{topic['type']}] {topic['hook']}")

    from .video import build_reel
    from .captions import build_captions
    stamp = now_ist().strftime("%Y-%m-%d")
    out = OUTPUT / f"reel-{stamp}-{topic['id']}.mp4"
    reel = build_reel(topic, cfg, OUTPUT / "work", out)
    caps = build_captions(topic, cfg, reel["credits"])
    (OUTPUT / "caption.txt").write_text(caps["instagram_caption"], encoding="utf-8")
    (OUTPUT / "youtube.json").write_text(json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Caption saved to output/caption.txt")

    if args.no_post:
        log.info(f"--no-post: video is at {out}")
        return 0

    p = cfg.get("posting", {})
    record = {"topic_id": topic["id"], "type": topic["type"], "hook": topic["hook"],
              "date": now_ist().isoformat(timespec="minutes"), "instagram": None, "youtube": None, "errors": []}
    if p.get("instagram", True):
        try:
            from .instagram import Instagram
            record["instagram"] = Instagram().publish_reel(out, caps["instagram_caption"], p.get("share_to_feed", True),
                                                           p.get("video_host", "auto"), f"reel-{stamp}-{topic['id']}")
        except Exception as e:
            log.error(f"Instagram FAILED: {e}")
            record["errors"].append(f"instagram: {e}")
    if p.get("youtube", True):
        try:
            from .youtube import upload_short
            record["youtube"] = upload_short(out, caps["youtube_title"], caps["youtube_description"],
                                             caps["youtube_tags"], p.get("youtube_privacy", "public"),
                                             p.get("youtube_category", "26"))
        except Exception as e:
            log.error(f"YouTube FAILED: {e}")
            record["errors"].append(f"youtube: {e}")
    wanted = [k for k in ("instagram", "youtube") if p.get(k, True)]
    record["success"] = any(record[k] for k in wanted) if wanted else False
    posted["posts"].append(record)
    save_posted(posted)
    if not record["success"]:
        log.error("Nothing was posted today. The video is saved in the run's 'reel' download (Artifacts).")
        return 1
    log.info("Done! " + ", ".join(k for k in wanted if record[k]) + " posted.")
    return 2 if record["errors"] else 0


def cmd_check(args):
    ok = True
    cfg = load_config()
    print("Topics:", len(load_topics()), "| content types:", cfg.get("topics", {}).get("content_types"))
    print("Stock video key (Pexels or Pixabay):", "found" if (secret("PEXELS_API_KEY") or secret("PIXABAY_API_KEY")) else "MISSING (free Openverse photos will be used)")
    if cfg["posting"].get("instagram", True):
        try:
            from .instagram import Instagram
            me = Instagram().whoami()
            print("Instagram: OK, connected to @" + str(me.get("username")))
        except Exception as e:
            ok = False
            print("Instagram: PROBLEM ->", e)
    if cfg["posting"].get("youtube", True):
        try:
            from .youtube import channel_name
            print("YouTube: OK, channel:", channel_name())
        except Exception as e:
            ok = False
            print("YouTube: PROBLEM ->", e)
    return 0 if ok else 1


def cmd_refresh(args):
    from .instagram import Instagram
    try:
        new = Instagram().refresh_token()
    except Exception as e:
        log.warning(f"Token refresh skipped: {e}")
        return 0
    if new:
        (ROOT / ".ig_token_new").write_text(new, encoding="utf-8")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::add-mask::{new}")
    return 0


def main(argv=None):
    load_env_file()
    setup_logging()
    ap = argparse.ArgumentParser(prog="autopilot")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--no-post", action="store_true")
    r.add_argument("--topic", default=None)
    sub.add_parser("check")
    sub.add_parser("refresh-token")
    args = ap.parse_args(argv)
    if not args.cmd:
        args = ap.parse_args(["run"] + (argv or sys.argv[1:]))
    try:
        code = {"run": cmd_run, "check": cmd_check, "refresh-token": cmd_refresh}[args.cmd](args)
    except Exception:
        log.error("Unexpected problem:\n" + traceback.format_exc())
        code = 1
    sys.exit(0 if code == 2 else code)  # 2 = partly posted: keep the run green but logged


if __name__ == "__main__":
    main()
