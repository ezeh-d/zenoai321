from audio_control import restore_music
from voice import microphone_status, calibrate_microphone, listen

print("Microphone status:", microphone_status())
print("Calibrating. Stay quiet for a moment...")
calibrate_microphone(force=True)
print("Play music, then whisper a short sentence.")
text = listen(timeout=10, phrase_time_limit=12, duck_audio=True)
print("Recognized:", text or "<nothing>")
restore_music()
