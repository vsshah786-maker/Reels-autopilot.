# Reels Autopilot - @dhruviverse.official

Every day at **9:00 PM IST** one illustrated quote reel is made and posted to Instagram Reels automatically. Free, runs on GitHub Actions.

## What each reel looks like
* A brand NEW AI illustration every day (soft digital art / pencil sketch / watercolor, often an Indian girl), made fresh for that day's line.
* One short bold line in a rounded font, with 1-2 key words in orange. The text sits wherever the picture has empty space, never over the girl.
* No voice, soft copyright-free music, about 9 seconds, small @dhruviverse.official at the bottom.

## Language rotates daily
English -> Hinglish -> Hindi -> Gujarati -> repeat.

## Lines
Mix of attitude, funny desi, friendship, love, self-love and heart-touching (papa, maa, home) lines.
* With the GEMINI_API_KEY secret, a NEW line is written every day in that day's language.
* Backup: 80 ready lines in `quotes_multi.yaml` (20 per language). Lines never repeat (`posted.json` remembers).

## Pictures
* Made daily with FLUX on Hugging Face (HF_TOKEN secret). Gemini checks each picture (no text, no strange faces/hands) and redraws if needed.
* `assets/illustrated/` = 13 emergency backup pictures, used ONLY if the picture maker is down that day.

## Caption
The line + a hook ("Tag that friend", "Comment if you agree") + "Follow @dhruviverse.official" + 8-10 hashtags.

## Secrets used
IG_ACCESS_TOKEN, IG_USER_ID, HF_TOKEN, GEMINI_API_KEY (PEXELS_API_KEY only for other modes).

## Run it by hand
Actions -> Daily reel -> Run workflow. post = no makes the video only (download it under Artifacts); post = yes posts it.

## Files
| File | What |
|---|---|
| `config.yaml` | settings; `content_mode: illustrated` (other modes: quotes / beauty / story / tips) |
| `quotes_multi.yaml` | the 80 backup lines |
| `.github/workflows/daily-reel.yml` | the daily 9 PM timer |
| `assets/fonts/` | fonts (Baloo 2 for English/Hindi, Baloo Bhai 2 for Gujarati) |
| `assets/illustrated/` | backup pictures |
| `assets/music/` | copyright-free music |

Stuck? Send Tab a screenshot on WhatsApp.
