from __future__ import annotations

import audioop
import os
import re
import tempfile
import time
import wave
from threading import Lock

import speech_recognition as sr

from speech import is_speaking
from config import (
    AUDIO_DUCKING_ENABLED,
    AUDIO_DUCKING_LEVEL,
    VOICE_DYNAMIC_ENERGY_RATIO,
    VOICE_ENERGY_THRESHOLD,
    VOICE_INPUT_GAIN,
    VOICE_MAX_CALIBRATED_THRESHOLD,
    VOICE_NON_SPEAKING_DURATION,
    VOICE_PAUSE_THRESHOLD,
    VOICE_PHRASE_THRESHOLD,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL,
)


# =========================================================
# REYES VOICE ENGINE
# =========================================================

recognizer = sr.Recognizer()
microphone_lock = Lock()

_selected_microphone_index: int | None = None
_selected_microphone_name = "Windows default microphone"
_microphone_calibrated = False
_last_voice_error = ""

_whisper_model_instance = None
_whisper_model_lock = Lock()


# =========================================================
# MICROPHONE PREFERENCES
# =========================================================

# REYES checks these names in order.
# This allows X10 Bluetooth earphones to be selected automatically.

PREFERRED_MICROPHONE_KEYWORDS = (
    "x10",
    "headset",
    "hands-free",
    "hands free",
    "bluetooth",
    "earphone",
    "microphone array",
)


# =========================================================
# LANGUAGE SETTINGS
# =========================================================

# Start with Nigerian English because it generally works best
# for Nigerian English and many Nigerian Pidgin expressions.

SUPPORTED_LANGUAGES = (
    "en-NG",
    "en-GB",
    "en-US",
)


# =========================================================
# RECOGNITION SETTINGS
# =========================================================

LISTEN_TIMEOUT = 8
PHRASE_TIME_LIMIT = 20
AMBIENT_NOISE_DURATION = 1.2

recognizer.dynamic_energy_threshold = True
recognizer.energy_threshold = VOICE_ENERGY_THRESHOLD
recognizer.dynamic_energy_adjustment_damping = 0.10
recognizer.dynamic_energy_ratio = VOICE_DYNAMIC_ENERGY_RATIO

recognizer.pause_threshold = VOICE_PAUSE_THRESHOLD
recognizer.phrase_threshold = VOICE_PHRASE_THRESHOLD
recognizer.non_speaking_duration = VOICE_NON_SPEAKING_DURATION


# =========================================================
# NIGERIAN PIDGIN NORMALIZATION
# =========================================================

PIDGIN_PHRASE_REPLACEMENTS = {
    "abeg": "",
    "oya": "",
    "wetin be the time": "what time is it",
    "wetin be time": "what time is it",
    "wetin time be": "what time is it",
    "wetin be today date": "what is today's date",
    "wetin be the date": "what is the date",
    "wetin be": "what is",
    "wetin": "what",
    "carry me go": "open",
    "waka go": "open",
    "go open": "open",
    "make you open": "open",
    "make i open": "open",
    "help me open": "open",
    "help me find": "search",
    "find am": "search",
    "search am": "search",
    "look for am": "search",
    "make you search": "search",
    "make i search": "search",
    "show me": "open",
    "no wahala": "okay",
    "e no dey": "it is not available",
    "e dey": "it is available",
    "where e dey": "where is it",
    "who be": "who is",
    "which one be": "what is",
    "how far": "hello",
    "how body": "how are you",
    "you dey hear me": "can you hear me",
    "you dey there": "are you there",
    "make we": "",
    "make i": "",
    "make you": "",
    "na wetin": "what",
    "na who": "who",
    "na where": "where",
    "na when": "when",
    "na why": "why",
    "na how": "how",
    "dey": "is",
    "don": "has",
    "fit": "can",
    "sabi": "know",
    "talk am": "say it",
    "send am": "send it",
    "close am": "close it",
    "open am": "open it",
}

PIDGIN_WORD_REPLACEMENTS = {
    "una": "you all",
    "dem": "them",
    "am": "it",
    "wey": "that",
    "dis": "this",
    "dat": "that",
    "dey": "is",
    "sabi": "know",
    "fit": "can",
    "pikin": "child",
    "wahala": "problem",
    "gist": "talk",
}


def normalize_nigerian_speech(text: str) -> str:
    """
    Convert common Nigerian Pidgin expressions into commands
    that the REYES brain and router can understand.
    """

    normalized = str(text).lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)

    for phrase in sorted(
        PIDGIN_PHRASE_REPLACEMENTS,
        key=len,
        reverse=True,
    ):
        replacement = PIDGIN_PHRASE_REPLACEMENTS[phrase]

        normalized = re.sub(
            rf"\b{re.escape(phrase)}\b",
            replacement,
            normalized,
            flags=re.IGNORECASE,
        )

    words = normalized.split()

    normalized_words = [
        PIDGIN_WORD_REPLACEMENTS.get(word, word)
        for word in words
    ]

    normalized = " ".join(normalized_words)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


# =========================================================
# MICROPHONE DISCOVERY
# =========================================================

def list_microphones() -> list[dict[str, object]]:
    """
    Return all microphones detected by SpeechRecognition.
    """

    try:
        names = sr.Microphone.list_microphone_names()
    except Exception as error:
        print(f"[REYES Microphone List Error] {error}")
        return []

    return [
        {
            "index": index,
            "name": name,
        }
        for index, name in enumerate(names)
    ]


def print_microphones() -> None:
    """
    Print all detected microphones and their device indexes.
    """

    microphones = list_microphones()

    if not microphones:
        print("REYES: No microphones were detected.")
        return

    print("\nDetected microphones:")

    for microphone in microphones:
        marker = ""

        if microphone["index"] == _selected_microphone_index:
            marker = "  <-- SELECTED"

        print(
            f"{microphone['index']}: "
            f"{microphone['name']}"
            f"{marker}"
        )


def find_preferred_microphone() -> tuple[int | None, str]:
    """
    Find the best microphone using preferred-name keywords.

    X10 devices are prioritized before other headsets.
    """

    microphones = list_microphones()

    if not microphones:
        return None, "No microphone detected"

    # Search keyword-by-keyword so X10 receives first priority.
    for keyword in PREFERRED_MICROPHONE_KEYWORDS:
        for microphone in microphones:
            name = str(microphone["name"])
            lowered_name = name.lower()

            if keyword in lowered_name:
                return int(microphone["index"]), name

    return None, "Windows default microphone"


def select_microphone(
    device_index: int | None = None,
) -> tuple[int | None, str]:
    """
    Select a microphone manually or automatically.

    Passing None enables automatic microphone selection.
    """

    global _selected_microphone_index
    global _selected_microphone_name
    global _microphone_calibrated

    if device_index is None:
        selected_index, selected_name = find_preferred_microphone()
    else:
        microphones = list_microphones()

        matching_device = next(
            (
                microphone
                for microphone in microphones
                if microphone["index"] == device_index
            ),
            None,
        )

        if matching_device is None:
            raise ValueError(
                f"Microphone device index {device_index} does not exist."
            )

        selected_index = int(matching_device["index"])
        selected_name = str(matching_device["name"])

    _selected_microphone_index = selected_index
    _selected_microphone_name = selected_name
    _microphone_calibrated = False

    print(
        "REYES microphone selected: "
        f"{_selected_microphone_name}"
    )

    return (
        _selected_microphone_index,
        _selected_microphone_name,
    )


def get_microphone_name() -> str:
    """
    Return the selected microphone's readable name.
    """

    return _selected_microphone_name


def get_microphone_index() -> int | None:
    """
    Return the selected microphone device index.
    """

    return _selected_microphone_index


def get_last_voice_error() -> str:
    """
    Return the last microphone or recognition error.
    """

    return _last_voice_error


# =========================================================
# MICROPHONE CREATION
# =========================================================

def create_microphone() -> sr.Microphone:
    """
    Create a microphone instance using the selected device.
    """

    return sr.Microphone(
        device_index=_selected_microphone_index
    )


# =========================================================
# MICROPHONE CALIBRATION
# =========================================================

def calibrate_microphone(
    duration: float = AMBIENT_NOISE_DURATION,
    force: bool = False,
) -> bool:
    """
    Calibrate the selected microphone for background noise.

    Calibration normally happens once after REYES starts.
    """

    global _microphone_calibrated
    global _last_voice_error

    if _microphone_calibrated and not force:
        return True

    try:
        with microphone_lock:
            with create_microphone() as source:
                print(
                    "REYES: Calibrating microphone. "
                    "Please remain quiet."
                )

                recognizer.adjust_for_ambient_noise(
                    source,
                    duration=max(0.3, float(duration)),
                )

                # Loud music can make dynamic calibration far too insensitive.
                # Cap the threshold so whispered speech can still trigger REYES.
                recognizer.energy_threshold = min(
                    float(recognizer.energy_threshold),
                    float(VOICE_MAX_CALIBRATED_THRESHOLD),
                )

        _microphone_calibrated = True
        _last_voice_error = ""

        print(
            "REYES: Microphone calibrated."
        )

        print(
            "REYES: Energy threshold: "
            f"{recognizer.energy_threshold:.0f}"
        )

        return True

    except OSError as error:
        _last_voice_error = (
            f"Microphone unavailable: {error}"
        )

        print(f"REYES: {_last_voice_error}")
        return False

    except Exception as error:
        _last_voice_error = (
            f"Microphone calibration failed: {error}"
        )

        print(f"REYES: {_last_voice_error}")
        return False


def initialize_voice_engine() -> bool:
    """
    Select and calibrate the microphone.

    This function is safe to call more than once.
    """

    global _selected_microphone_name
    global _last_voice_error

    try:
        if _selected_microphone_name == "Windows default microphone":
            select_microphone()

        print(
            "REYES: Voice input device: "
            f"{_selected_microphone_name}"
        )

        return calibrate_microphone()

    except Exception as error:
        _last_voice_error = (
            f"Voice initialization failed: {error}"
        )

        print(f"REYES: {_last_voice_error}")
        return False


# =========================================================
# AUDIO CAPTURE
# =========================================================

def capture_audio(
    timeout: float = LISTEN_TIMEOUT,
    phrase_time_limit: float = PHRASE_TIME_LIMIT,
) -> sr.AudioData | None:
    """
    Capture one spoken phrase from the selected microphone.
    """

    global _last_voice_error

    while is_speaking():
        time.sleep(0.1)

    if not initialize_voice_engine():
        return None

    try:
        with microphone_lock:
            with create_microphone() as source:
                print(
                    f"Listening through: "
                    f"{_selected_microphone_name}"
                )

                audio = recognizer.listen(
                    source,
                    timeout=max(1.0, float(timeout)),
                    phrase_time_limit=max(
                        1.0,
                        float(phrase_time_limit),
                    ),
                )

        _last_voice_error = ""
        return audio

    except sr.WaitTimeoutError:
        _last_voice_error = (
            "No speech was detected before the listening timeout."
        )

        print(f"REYES: {_last_voice_error}")
        return None

    except OSError as error:
        _last_voice_error = (
            f"Microphone error: {error}"
        )

        print(f"REYES: {_last_voice_error}")
        return None

    except Exception as error:
        _last_voice_error = (
            f"Audio capture failed: {error}"
        )

        print(f"REYES: {_last_voice_error}")
        return None


# =========================================================
# WHISPER GAIN
# =========================================================

def amplify_audio(audio: sr.AudioData, gain: float = VOICE_INPUT_GAIN) -> sr.AudioData:
    """Boost quiet PCM speech before recognition, with safe clipping."""
    try:
        multiplier = max(1.0, min(3.0, float(gain)))
        raw = audio.get_raw_data(convert_rate=audio.sample_rate, convert_width=2)
        boosted = audioop.mul(raw, 2, multiplier)
        return sr.AudioData(boosted, audio.sample_rate, 2)
    except Exception as error:
        print(f"[REYES Whisper Gain Warning] {error}")
        return audio


# =========================================================
# FASTER-WHISPER
# =========================================================

def _get_whisper_model():
    """
    Lazily load Faster-Whisper once and reuse it.

    The first recognition can take longer because the model may need
    to be downloaded and initialized.
    """

    global _whisper_model_instance

    if _whisper_model_instance is not None:
        return _whisper_model_instance

    with _whisper_model_lock:
        if _whisper_model_instance is not None:
            return _whisper_model_instance

        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "Faster-Whisper is not installed. Run: "
                "python -m pip install faster-whisper"
            ) from error

        print(
            "REYES: Loading Faster-Whisper "
            f"model '{WHISPER_MODEL}' on {WHISPER_DEVICE}..."
        )

        _whisper_model_instance = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )

        print("REYES: Faster-Whisper is ready.")
        return _whisper_model_instance


def _write_audio_to_temp_wav(audio: sr.AudioData) -> str:
    """
    Save SpeechRecognition AudioData as a temporary mono WAV file.
    """

    raw_data = audio.get_raw_data(
        convert_rate=16000,
        convert_width=2,
    )

    temporary_file = tempfile.NamedTemporaryFile(
        prefix="reyes_",
        suffix=".wav",
        delete=False,
    )
    temporary_path = temporary_file.name
    temporary_file.close()

    with wave.open(temporary_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(raw_data)

    return temporary_path


# =========================================================
# SPEECH RECOGNITION
# =========================================================

def recognize_audio(
    audio: sr.AudioData,
    languages: tuple[str, ...] | list[str] | None = None,
) -> tuple[str, str] | None:
    """
    Recognize captured speech locally with Faster-Whisper.

    Faster-Whisper performs its own language detection. The ``languages``
    argument is retained for compatibility with existing REYES callers.
    """

    global _last_voice_error

    temporary_path = ""

    try:
        model = _get_whisper_model()
        temporary_path = _write_audio_to_temp_wav(audio)

        segments, info = model.transcribe(
            temporary_path,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        recognized_parts = [
            segment.text.strip()
            for segment in segments
            if segment.text and segment.text.strip()
        ]

        clean_text = " ".join(recognized_parts).strip()

        if not clean_text:
            _last_voice_error = (
                "Speech was detected, but Faster-Whisper "
                "could not understand the words."
            )
            print(f"REYES: {_last_voice_error}")
            return None

        detected_language = str(
            getattr(info, "language", None) or "unknown"
        )

        _last_voice_error = ""
        return clean_text, detected_language

    except Exception as error:
        _last_voice_error = (
            f"Faster-Whisper recognition failed: {error}"
        )
        print(f"REYES: {_last_voice_error}")
        return None

    finally:
        if temporary_path:
            try:
                os.remove(temporary_path)
            except OSError:
                pass


# =========================================================
# MAIN LISTEN FUNCTION
# =========================================================

def listen(
    timeout: float = LISTEN_TIMEOUT,
    phrase_time_limit: float = PHRASE_TIME_LIMIT,
    languages: tuple[str, ...] | list[str] | None = None,
    normalize_pidgin: bool = True,
    duck_audio: bool = True,
) -> str:
    """
    Listen once and return recognized text.

    This function remains compatible with gui/voice_controller.py.
    """

    if duck_audio and AUDIO_DUCKING_ENABLED:
        try:
            from audio_control import duck_music
            duck_music(AUDIO_DUCKING_LEVEL)
        except Exception as error:
            print(f"[REYES Audio Ducking Warning] {error}")

    audio = capture_audio(
        timeout=timeout,
        phrase_time_limit=phrase_time_limit,
    )

    if audio is None:
        return ""

    audio = amplify_audio(audio)

    result = recognize_audio(
        audio,
        languages=languages,
    )

    if result is None:
        return ""

    original_text, detected_language = result

    normalized_original = (
        original_text.lower().strip()
    )

    final_text = normalized_original

    if normalize_pidgin:
        final_text = normalize_nigerian_speech(
            original_text
        )

    print(
        f"You [{detected_language}]: "
        f"{original_text}"
    )

    if final_text != normalized_original:
        print(
            f"REYES understood: {final_text}"
        )

    return final_text


# =========================================================
# DETAILED LISTENING
# =========================================================

def listen_with_details(
    timeout: float = LISTEN_TIMEOUT,
    phrase_time_limit: float = PHRASE_TIME_LIMIT,
    languages: tuple[str, ...] | list[str] | None = None,
) -> dict[str, str] | None:
    """
    Return speech text, normalized text, language,
    microphone name, and error information.
    """

    audio = capture_audio(
        timeout=timeout,
        phrase_time_limit=phrase_time_limit,
    )

    if audio is None:
        return None

    result = recognize_audio(
        audio,
        languages=languages,
    )

    if result is None:
        return None

    original_text, language = result

    normalized_text = normalize_nigerian_speech(
        original_text
    )

    print(
        f"You [{language}]: {original_text}"
    )

    if normalized_text != original_text.lower().strip():
        print(
            f"REYES understood: {normalized_text}"
        )

    return {
        "original_text": original_text,
        "text": normalized_text,
        "language": language,
        "microphone": _selected_microphone_name,
        "error": "",
    }


# =========================================================
# DIAGNOSTICS
# =========================================================

def microphone_status() -> dict[str, object]:
    """
    Return microphone information for GUI diagnostics.
    """

    return {
        "available": bool(list_microphones()),
        "selected_index": _selected_microphone_index,
        "selected_name": _selected_microphone_name,
        "calibrated": _microphone_calibrated,
        "energy_threshold": round(
            float(recognizer.energy_threshold),
            2,
        ),
        "last_error": _last_voice_error,
    }


def run_microphone_test() -> None:
    """
    Run a simple terminal microphone test.
    """

    print("=" * 60)
    print("REYES MICROPHONE TEST")
    print("=" * 60)

    select_microphone()
    print_microphones()

    print(
        "\nSelected microphone: "
        f"{get_microphone_name()}"
    )

    if not calibrate_microphone(force=True):
        print(
            "\nCalibration failed:"
        )
        print(get_last_voice_error())
        return

    print(
        "\nSpeak a sentence after "
        "'Listening through' appears."
    )

    message = listen(
        timeout=10,
        phrase_time_limit=15,
    )

    if message:
        print(
            f"\nFinal recognized command: {message}"
        )
    else:
        print(
            "\nREYES did not recognize a command."
        )

        print(
            f"Reason: {get_last_voice_error()}"
        )


# =========================================================
# STANDALONE TEST
# =========================================================

if __name__ == "__main__":
    run_microphone_test()