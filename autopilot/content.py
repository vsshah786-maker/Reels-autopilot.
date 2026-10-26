from .common import log


def pick_topic(topics, posted, cfg, force_id=None):
    """Next topic that has not been posted yet (in list order), respecting content_types."""
    if force_id is not None:
        for t in topics:
            if str(t["id"]) == str(force_id):
                return t
        raise ValueError(f"No topic with id {force_id} in topics.yaml")
    types = (cfg.get("topics") or {}).get("content_types") or ["tip", "fact", "quote", "find"]
    allowed = [t for t in topics if t.get("type", "tip") in types]
    if not allowed:
        raise ValueError("No topics left after filtering by content_types in config.yaml")
    done = [p["topic_id"] for p in posted.get("posts", []) if p.get("success")]
    done_set = set(map(str, done))
    for t in allowed:
        if str(t["id"]) not in done_set:
            return t
    mode = (cfg.get("topics") or {}).get("when_finished", "repeat")
    if mode == "stop":
        log.warning("All topics have been posted and when_finished=stop. Add more to topics.yaml.")
        return None
    # repeat: pick the one posted longest ago
    last_seen = {}
    for i, tid in enumerate(done):
        last_seen[str(tid)] = i
    allowed.sort(key=lambda t: last_seen.get(str(t["id"]), -1))
    log.info("All topics used once - repeating the oldest one. Tip: add new ideas to topics.yaml")
    return allowed[0]
