"""Run this ONCE on your laptop to connect YouTube.

1. Put the file you downloaded from Google Cloud (client_secret_....json) in this folder
   and rename it to:  client_secret.json
2. Run:   python tools/get_youtube_token.py
3. A browser opens -> choose your YouTube channel's Google account -> "Advanced" ->
   "Go to (app name) (unsafe)" -> Continue.   (It says "unsafe" only because the app is yours
   and not reviewed by Google. That's normal.)
4. Copy the 3 lines it prints into GitHub Secrets.
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
here = Path(__file__).resolve().parent.parent
f = here / "client_secret.json"
if not f.exists():
    f = here / "tools" / "client_secret.json"
if not f.exists():
    sys.exit("client_secret.json not found. Put it in the main folder (see step 1 at the top of this file).")

flow = InstalledAppFlow.from_client_secrets_file(str(f), SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.loads(f.read_text())
info = info.get("installed") or info.get("web")
print("\n\nCopy these into GitHub > Settings > Secrets and variables > Actions > New repository secret:\n")
print("YT_CLIENT_ID      =", info["client_id"])
print("YT_CLIENT_SECRET  =", info["client_secret"])
print("YT_REFRESH_TOKEN  =", creds.refresh_token)
print("\nKeep these private. Never post them anywhere.")
