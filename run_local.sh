#!/usr/bin/env bash
# Test on Mac/Linux (needs python3 + ffmpeg). Nothing is posted.
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
python3 -m autopilot run --no-post
echo "Open the output folder to watch your reel."
