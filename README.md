# Faceless Reels Autopilot

## NEW: Beauty mode (default) - for @dhruviverse.official
Every day one 30-40 s Hinglish makeup reel is made and posted to Instagram:
hook line -> 4 tips -> "Save karo aur follow karo @dhruviverse.official".
Each step gets its own soft, aesthetic AI beauty photo (products, hands, mirror, side profile - no faces),
the Hindi voice (Swara) reads it, small karaoke captions show the words in Roman Hinglish with the
spoken word in a purple box, soft lofi music underneath, your handle small at the top.

* Scripts: with a free GEMINI_API_KEY secret, Gemini writes a NEW script daily (it picks a model that works by itself).
  Without it (or if Gemini is busy) the 30 ready scripts in beauty_scripts.yaml are used in order.
* Pictures: FLUX on Hugging Face. Add the free HF_TOKEN secret (huggingface.co -> Settings -> Access Tokens -> Read)
  so the daily picture quota is yours. Without pictures it falls back to a soft colour background.
* Change the look in config.yaml -> beauty: -> image_style: realistic  or  3d_cartoon
* Posting: Instagram on. YouTube is skipped automatically until the YouTube secrets exist; a YouTube
  problem never makes the run fail when Instagram worked.
* Switch modes with ONE word in config.yaml: content_mode: beauty / story / tips

Secrets used: IG_ACCESS_TOKEN, IG_USER_ID (already there), HF_TOKEN (strongly recommended),
GEMINI_API_KEY (optional), YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN (later, for YouTube).


Makes **one faceless vertical reel every day** and posts it to **Instagram Reels** and **YouTube Shorts**. It runs free on GitHub Actions, so your laptop can stay off.

**Setup:** follow `faceless-autopilot-setup-guide.pdf` (the steps are numbered). Stuck? Send Tab a screenshot on WhatsApp.

## What happens every day (7:00 PM IST)
1. Picks the next idea from `topics.yaml` (tips, facts, quotes and Meesho finds, rotating). It never repeats until the list is finished, because `posted.json` remembers what was posted.
2. Finds free vertical background videos on Pexels (or uses your own clips from `assets/my_clips`).
3. Builds a 1080x1920 reel (~10–25 s) with text screens, soft transitions and bundled copyright-free music. A free AI voice is optional.
4. Writes the caption + hashtags, then posts to Instagram and YouTube (#Shorts).
5. If one platform fails, the other still posts. The video is kept for 7 days under the run's **Artifacts**, and the log is in `logs/`.

## Files you may edit
| File | What |
|---|---|
| `topics.yaml` | your reel ideas: copy a block to add one |
| `config.yaml` | page handle, hashtags, voice on/off, background source, colours, content types |
| `.github/workflows/daily-reel.yml` | posting time (`cron`, in UTC = IST − 5:30) |
| `assets/music/` | background music (.mp3), one picked at random |
| `assets/my_clips/` | your own faceless clips (optional) |

## Secrets (GitHub → Settings → Secrets and variables → Actions)
| Name | Needed | From |
|---|---|---|
| `PEXELS_API_KEY` | recommended | pexels.com/api (free) |
| `IG_ACCESS_TOKEN` | for Instagram | Meta app → Instagram → API setup with Instagram login → Generate token |
| `IG_USER_ID` | only with a Facebook-login token (EAA…) | Graph API Explorer |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | for YouTube | `python tools/get_youtube_token.py` |
| `GH_PAT` | optional | fine-grained token with Secrets read/write: auto-saves the renewed Instagram token |
| `GEMINI_API_KEY` | optional | free Gemini key; set `captions.use_gemini: true` |

## Commands (on your laptop)
```
python -m autopilot run --no-post     # make a test reel into output/ (Windows: double-click run_local.bat)
python -m autopilot run --topic 7     # make + post topic 7
python -m autopilot check             # test your keys (posts nothing)
python -m pytest -q                   # offline tests (API calls are faked)
```
Needs Python 3.11+ and ffmpeg (Windows: `winget install Gyan.FFmpeg`). For laptop runs, put your keys in a `.env` file (see `.env.example`). Never upload `.env`.

## Honest limits
- **YouTube:** since July 2020, uploads from unverified Google API projects were locked to *Private* until the project passed Google's audit. Google's `videos.insert` page, checked 26 Oct 2026, now says unverified projects are not restricted to private. If uploads still come out Private, switch them to Public in YouTube Studio and apply through the YouTube API Services audit form. The log warns when this happens. Keep the OAuth app **In production**, because in "Testing" the refresh token dies after 7 days.
- **Instagram token:** lasts 60 days. It is refreshed at every run, and only saved automatically if `GH_PAT` is set. Otherwise generate a new one every ~50 days.
- **Instagram video link:** with an Instagram-login token, Instagram must download the video from a public URL. The software uses a temporary GitHub Release (public repo needed; deleted after posting) and falls back to litterbox.catbox.moe. A Facebook-login token (EAA…) uses direct upload instead. Not yet tested against a live account.
- **Music:** trending/Bollywood audio can't be added through the API. Use the bundled tracks or royalty-free ones.
- **Pexels:** free, attribution appreciated (credit lines are added to captions). Openverse fallback photos (no key) carry Creative Commons credits, also added automatically.
- **GitHub Actions:** public repos have free, unlimited minutes; private repos get 2,000 min/month free (one run ≈ 3–5 min). Scheduled runs can start late at busy times. Schedules in public repos pause after 60 days without commits, but the daily `posted.json` commit keeps it active.

Fonts: Poppins and Playfair Display (SIL Open Font License, included). Music: generated by `tools/make_music.py` (CC0).


## Kids story mode (Nanha Sitara Stories) — `content_mode: story`
Every day it makes a 30–40 s kids story reel and posts it to YouTube Shorts:
1. **Story**: a new story written by free Gemini (if the `GEMINI_API_KEY` secret exists), otherwise the next one from `stories.yaml` (30 ready stories, never repeated until all are used).
2. **Pictures**: one Pixar-style cartoon picture per scene (6 scenes), with the same character description and the same seed for every picture so the hero looks the same. Free picture makers are tried in order: Hugging Face FLUX → Cloudflare FLUX → Pollinations → Gemini → soft colour background.
3. **Voice**: free Microsoft storyteller voice (edge-tts) with exact word timings.
4. **Video**: slow zoom/pan on each picture, soft fades, small karaoke captions (1–3 words, the spoken word in a purple box), title for the first 3 s, soft kids music made by the program (no copyright).

**Switch things in `config.yaml`:**
| What | Line |
|---|---|
| story or old tips reels | `content_mode: story` / `content_mode: tips` |
| language | `language: hinglish` / `hindi` / `english` |
| caption size | `caption_font_size: 64` |
| glitch effect | `glitch: true` |
| Instagram too | `instagram: true` (under `story:`) |

Hinglish = the Hindi voice reads the story (sounds natural), and the captions show the same words in Roman letters.

**Optional free secrets for better pictures** (no credit card):
| Name | From |
|---|---|
| `HF_TOKEN` | huggingface.co → sign up → Settings → Access Tokens → New token (Read). Gives a bigger free daily picture quota. **Recommended.** |
| `CF_ACCOUNT_ID`, `CF_API_TOKEN` | dash.cloudflare.com (free plan) → Workers AI → "Use REST API". Backup picture maker. |
| `GEMINI_API_KEY` | aistudio.google.com → Get API key. A new story every day (free tier: 20 per day, we use 1). |

Test without posting: Actions → Daily reel → Run workflow → Post: no → download the "reel" artifact.
Use a story by number: put its id (e.g. `13`) in "Topic id".


## QUOTES MODE (default since v5)
`content_mode: quotes` in config.yaml. Every day: one calm aesthetic video clip (sky, flowers, coffee, rain, ocean...) from free Pixabay,
your line in elegant Playfair Display text appearing line by line, small @dhruviverse.official at the bottom, soft music, 8-14 s.
- Lines: free Gemini writes a new one daily (GEMINI_API_KEY secret), otherwise the next one from quotes.yaml (61 lines).
- Clips: picked by the line's mood; Gemini looks at 3 frames and skips clips with text, logos or close-up faces.
- Optional: a real free Pexels key as secret PEXELS_REAL_KEY adds Pexels clips (PEXELS_API_KEY keeps holding the Pixabay key).
- `quotes: voice: on` makes a soft voice read the line. Switch back with `content_mode: beauty` (makeup reels) or `tips`.

## ILLUSTRATED mode (default since v6)

`content_mode: illustrated` in config.yaml. Every day at 9 PM India time:

1. **Line**: free Gemini (GEMINI_API_KEY) writes a fresh viral line in the day's language
   (English → Hinglish → Hindi → Gujarati, rotating), in the style of the 80 lines in `quotes_multi.yaml`
   (about a third are heart-touching, plus attitude, funny, friendship, love and self-love lines). No Gemini = next unused line from `quotes_multi.yaml`.
2. **Art**: one illustration made fresh by free FLUX on Hugging Face (HF_TOKEN), then Pollinations;
   Gemini looks at it and throws away pictures with text/signatures or broken faces/hands (it tries again).
   If nothing works, one of the pictures in `assets/illustrated/` is used.
3. **Video**: 9 s, slow zoom + soft floating dust; the line in Baloo 2 / Baloo Bhai 2 ExtraBold
   (Hindi + Gujarati letters shaped correctly), `*word*` = orange/yellow; the text goes where the picture
   is calm (top or centre, never over the girl), dark or white text picked by the background; small @handle; soft music from `assets/music`.
4. **Caption**: the line + a hook ("Tag that friend 👀") + follow line + ~10 hashtags. The cover frame shows the text.

Settings: the `illustrated:` block in config.yaml (languages, text size, length, accent pop, Gemini checks).
Trending songs can't be added by any software - if you post by hand, add a trending sound in the Instagram app.
Run it by hand: GitHub → Actions → Daily reel → Run workflow (post: no = only make the video, download it from Artifacts).
