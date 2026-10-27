"""Uploads the reel as a YouTube Short with the official YouTube Data API (free quota)."""
from .common import log, secret

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


class YouTubeError(RuntimeError):
    pass


def service():
    cid, csec, rtok = secret("YT_CLIENT_ID"), secret("YT_CLIENT_SECRET"), secret("YT_REFRESH_TOKEN")
    missing = [n for n, v in [("YT_CLIENT_ID", cid), ("YT_CLIENT_SECRET", csec), ("YT_REFRESH_TOKEN", rtok)] if not v]
    if missing:
        raise YouTubeError("Missing secrets: " + ", ".join(missing))
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=rtok, client_id=cid, client_secret=csec,
                        token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_name(yt=None):
    yt = yt or service()
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    return items[0]["snippet"]["title"] if items else None


def upload_short(video_path, title, description, tags, privacy="public", category="26", yt=None, made_for_kids=False):
    from googleapiclient.http import MediaFileUpload
    yt = yt or service()
    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": str(category)},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids), "containsSyntheticMedia": False},
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    got = (resp.get("status") or {}).get("privacyStatus")
    log.info(f"    YouTube Short uploaded: https://youtube.com/shorts/{vid}  (privacy: {got})")
    if privacy == "public" and got and got != "public":
        log.warning("    YouTube kept this video as '%s'. If your Google Cloud project is unverified, YouTube may "
                    "lock API uploads to private - see the guide (Step 9) for the audit form.", got)
    return vid
