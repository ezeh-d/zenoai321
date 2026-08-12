"""SenseVoice remains an optional non-English/audio-event adapter."""


def status() -> dict:
    from reyes_agent.audio.understanding.sensevoice import SenseVoiceBackend

    return SenseVoiceBackend().status()
