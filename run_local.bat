@echo off
REM ===== Test the autopilot on your Windows laptop =====
REM Needs: Python 3.11+ (python.org, tick "Add to PATH") and ffmpeg (run once:  winget install Gyan.FFmpeg )
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
echo.
echo Making a test reel (nothing will be posted)...
python -m autopilot run --no-post
echo.
echo Done! Open the "output" folder to watch your reel.
pause
