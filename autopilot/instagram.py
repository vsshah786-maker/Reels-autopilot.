"""Posts a Reel with the official Instagram API (free).

Two kinds of token work:
  * "Instagram Login" token (starts with IGAA..., from Meta app dashboard > Instagram > API setup
    with Instagram login).  Host graph.instagram.com.  RECOMMENDED - no Facebook Page needed.
  * "Facebook Login" token (starts with EAA...).  Host graph.facebook.com.  Needs IG linked to a
    Facebook Page and IG_USER_ID.  This route can upload the file directly (no public link needed).
"""
import time

import requests

from .common import log, secret
from .hosting import public_url

API_VERSION = "v25.0"


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self, token=None, user_id=None, host=None, version=None, session=None):
        self.token = token or secret("IG_ACCESS_TOKEN")
        if not self.token:
            raise InstagramError("IG_ACCESS_TOKEN secret is missing")
        self.facebook = self.token.startswith("EAA") or (host or "").endswith("facebook.com")
        self.host = host or secret("IG_API_HOST") or ("graph.facebook.com" if self.facebook else "graph.instagram.com")
        self.version = version or secret("IG_API_VERSION", API_VERSION)
        self.http = session or requests.Session()
        self.user_id = user_id or secret("IG_USER_ID")

    def _url(self, path):
        return f"https://{self.host}/{self.version}/{path.lstrip('/')}"

    def _check(self, r):
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:300]}
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", data)
            raise InstagramError(f"Instagram said: {err.get('message', err) if isinstance(err, dict) else err}")
        return data

    def get(self, path, **params):
        params["access_token"] = self.token
        return self._check(self.http.get(self._url(path), params=params, timeout=60))

    def post(self, path, **params):
        params["access_token"] = self.token
        return self._check(self.http.post(self._url(path), data=params, timeout=120))

    def whoami(self):
        if self.facebook:
            if not self.user_id:
                raise InstagramError("IG_USER_ID is needed with a Facebook-login token")
            return self.get(self.user_id, fields="id,username")
        me = self.get("me", fields="user_id,username")
        self.user_id = self.user_id or str(me.get("user_id") or me.get("id"))
        return me

    def wait_ready(self, container_id, max_wait=600):
        t0 = time.time()
        while time.time() - t0 < max_wait:
            st = self.get(container_id, fields="status_code,status")
            code = st.get("status_code")
            log.info(f"    Instagram processing: {code}")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram could not process the video: {st.get('status')}")
            time.sleep(10)
        raise InstagramError("Instagram took too long to process the video")

    @staticmethod
    def _thumb():
        """Cover frame: IG_THUMB_OFFSET_MS (set by illustrated mode) picks the frame where the text is fully shown."""
        import os
        ms = os.environ.get("IG_THUMB_OFFSET_MS", "").strip()
        return {"thumb_offset": ms} if ms.isdigit() else {}

    def publish_reel(self, video_path, caption, share_to_feed=True, video_host="auto", tag="reel"):
        me = self.whoami()
        log.info(f"    Posting to Instagram as @{me.get('username')}")
        cleanup = None
        try:
            if self.facebook and video_host in ("auto", "direct"):
                container = self._resumable(video_path, caption, share_to_feed)
            else:
                url, cleanup = public_url(video_path, "auto" if video_host in ("auto", "direct") else video_host, tag)
                container = self.post(f"{self.user_id}/media", media_type="REELS", video_url=url,
                                      caption=caption, share_to_feed=str(bool(share_to_feed)).lower(),
                                      **self._thumb())["id"]
            self.wait_ready(container)
            media = self.post(f"{self.user_id}/media_publish", creation_id=container)
            log.info(f"    Instagram reel published, id {media['id']}")
            return media["id"]
        finally:
            if cleanup:
                try:
                    cleanup()
                except Exception:
                    pass

    def _resumable(self, video_path, caption, share_to_feed):
        import os
        c = self.post(f"{self.user_id}/media", media_type="REELS", upload_type="resumable",
                      caption=caption, share_to_feed=str(bool(share_to_feed)).lower(), **self._thumb())
        size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            r = self.http.post(f"https://rupload.facebook.com/ig-api-upload/{self.version}/{c['id']}",
                               headers={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)},
                               data=f, timeout=600)
        self._check(r)
        return c["id"]

    def refresh_token(self):
        """Instagram-login tokens last 60 days; this gives a fresh 60-day token (token must be >24 h old)."""
        if self.facebook:
            log.info("    Facebook-login token: auto-refresh not supported, renew it in the Meta dashboard")
            return None
        r = self.http.get("https://graph.instagram.com/refresh_access_token",
                          params={"grant_type": "ig_refresh_token", "access_token": self.token}, timeout=60)
        data = self._check(r)
        days = int(data.get("expires_in", 0)) // 86400
        log.info(f"    Instagram token refreshed - valid for {days} more days")
        return data.get("access_token")
