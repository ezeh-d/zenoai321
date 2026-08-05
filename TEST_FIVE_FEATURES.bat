@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -c "import brain, voice, speech, vision, desktop_control; print('BRAIN:', callable(brain.think)); print('VOICE MIC:', voice.select_microphone()); print('TTS:', speech.current_engine()); print('VISION:', callable(vision.describe_screen)); print('DESKTOP:', callable(desktop_control.click_mouse))"
pause
