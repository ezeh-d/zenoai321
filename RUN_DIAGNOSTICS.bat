@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m compileall -q .
python test_audio_engine.py
python -c "from core.capabilities import describe; print(describe())"
pause
