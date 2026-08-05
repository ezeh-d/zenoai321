from __future__ import annotations

from speech import speak, current_engine
from voice import microphone_status

print("REYES Audio Engine Test")
print("Microphone:", microphone_status())
speak("Hello. I am REYES. My new local Kokoro voice engine is active.")
print("TTS engine used:", current_engine())
print("Now run REYES with: python main.py")
