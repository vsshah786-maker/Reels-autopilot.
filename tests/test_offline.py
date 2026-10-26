"""Offline tests: run with   python -m pytest -q   (no internet, no posting).
The Instagram/YouTube calls are replaced with fakes so nothing reaches a real account."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autopilot import captions, content, instagram  # noqa: E402
from autopilot.common import load_config, load_topics  # noqa: E402


def test_topics_load_and_rotate():
    cfg, topics = load_config(), load_topics()
    assert len(topics) >= 28
    assert {t["type"] for t in topics} == {"tip", "fact", "quote", "find"}
    posted = {"posts": [{"topic_id": topics[0]["id"], "success": True}]}
    assert content.pick_topic(topics, posted, cfg)["id"] == topics[1]["id"]
    cfg["topics"]["content_types"] = ["quote"]
    assert content.pick_topic(topics, {"posts": []}, cfg)["type"] == "quote"


def test_repeat_when_finished():
    cfg, topics = load_config(), load_topics()
    posted = {"posts": [{"topic_id": t["id"], "success": True} for t in topics]}
    assert content.pick_topic(topics, posted, cfg)["id"] == topics[0]["id"]
    cfg["topics"]["when_finished"] = "stop"
    assert content.pick_topic(topics, posted, cfg) is None


def test_captions():
    cfg, topics = load_config(), load_topics()
    for t in topics:
        c = captions.build_captions(t, cfg, ["Video by X on Pexels"])
        assert c["youtube_title"].endswith("#Shorts") and len(c["youtube_title"]) <= 100
        assert len(c["instagram_caption"]) <= 2200
        assert c["instagram_caption"].count("#") <= 31
        assert t["hook"] in c["instagram_caption"]


class FakeResp:
    def __init__(self, data, code=200):
        self._d, self.status_code, self.text = data, code, json.dumps(data)

    def json(self):
        return self._d


def test_instagram_flow_mocked(tmp_path):
    vid = tmp_path / "r.mp4"
    vid.write_bytes(b"0" * 1000)
    calls = []

    class S:
        def get(self, url, params=None, timeout=None, **k):
            calls.append(("GET", url))
            if url.endswith("/me"):
                return FakeResp({"user_id": "17841400000000000", "username": "dhruviverse.official"})
            return FakeResp({"status_code": "FINISHED"})

        def post(self, url, data=None, timeout=None, **k):
            calls.append(("POST", url, dict(data or {})))
            if url.endswith("/media"):
                assert data["media_type"] == "REELS" and data["video_url"].startswith("https://")
                return FakeResp({"id": "C123"})
            return FakeResp({"id": "M999"})

    with mock.patch.object(instagram, "public_url", return_value=("https://example.com/r.mp4", None)):
        ig = instagram.Instagram(token="IGAAfake", session=S())
        assert ig.host == "graph.instagram.com"
        assert ig.publish_reel(vid, "hello") == "M999"
    assert any(c[0] == "POST" and c[1].endswith("/media_publish") for c in calls)


def test_instagram_error_is_raised():
    class S:
        def get(self, *a, **k):
            return FakeResp({"error": {"message": "Invalid OAuth access token"}}, 400)
    ig = instagram.Instagram(token="IGAAbad", session=S())
    try:
        ig.whoami()
        assert False
    except instagram.InstagramError as e:
        assert "Invalid OAuth" in str(e)


def test_youtube_mocked(tmp_path):
    from autopilot import youtube
    vid = tmp_path / "r.mp4"
    vid.write_bytes(b"0" * 1000)
    fake = mock.MagicMock()
    fake.videos().insert().next_chunk.return_value = (None, {"id": "abc123", "status": {"privacyStatus": "public"}})
    assert youtube.upload_short(vid, "t #Shorts", "d", ["a"], yt=fake) == "abc123"
