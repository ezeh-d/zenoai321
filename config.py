"""Central configuration for REYES.

Supports both:
1. Modern imports through ``settings``.
2. Older REYES modules that import uppercase constants directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identity ---
    user_name: str = "Boss"
    assistant_name: str = "REYES"
    version: str = "2.0"
    debug: bool = False

    # --- LLM / brain ---
    # Any LiteLLM-supported model string, for example:
    # "gpt-4o-mini", "claude-3-5-sonnet-latest",
    # "gemini/gemini-1.5-flash"
    llm_model: str = "gpt-4o-mini"
    # Optional comma-separated extra models to try, in order, before Ollama.
    # e.g. "gemini/gemini-1.5-flash,claude-3-5-sonnet-latest"
    llm_fallback_models: str = ""
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    # Offline fallback (requires a running local Ollama server)
    ollama_model: str = "ollama/llama3"
    ollama_base_url: str = "http://localhost:11434"

    # --- Audio output ---
    voice_rate: int = 170
    wake_word: str = "hello reyes"
    # --- Always-on voice assistant ---
    voice_assistant_cooldown: float = 1.0   # pause after each reply (debounce)
    wake_engine: str = "auto"               # auto | builtin | openwakeword
    # --- Natural voice (ElevenLabs) ---
    tts_engine: str = "auto"                 # auto | elevenlabs | pyttsx3
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str = "FVr8g66ZdLr7fVJct2Dh"
    elevenlabs_model: str = "eleven_turbo_v2_5"
    kokoro_voice: str = "af_heart"
    audio_models_dir: Path = BASE_DIR / "models" / "audio"
    kokoro_model_filename: str = "kokoro-v1.0.onnx"
    kokoro_voices_filename: str = "voices-v1.0.bin"

    # --- Speech recognition ---
    whisper_model: str = "base.en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # --- Microphone sensitivity ---
    voice_energy_threshold: float = 180.0
    voice_dynamic_energy_ratio: float = 1.35
    voice_pause_threshold: float = 0.8
    voice_phrase_threshold: float = 0.2
    voice_non_speaking_duration: float = 0.3
    voice_max_calibrated_threshold: float = 500.0
    voice_input_gain: float = 1.8

    # --- Smart audio ducking ---
    audio_ducking_enabled: bool = True
    audio_ducking_level: float = 0.25

    # --- Storage ---
    data_dir: Path = BASE_DIR / "data"

    # --- Email ---
    smtp_host: str | None = None
    smtp_port: int = 587
    imap_host: str | None = None
    email_address: str | None = None
    email_password: str | None = None

    # --- Telegram ---
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # --- Slack ---
    slack_bot_token: str | None = None

    # --- Obsidian ---
    obsidian_vault_path: str | None = None

    # --- Safety ---
    require_confirmation: bool = True


settings = Settings()

# Create required local directories safely.
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.audio_models_dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Backward-compatible constants
# ---------------------------------------------------------------------------
# Older REYES modules import these names directly from config.py. Keeping these
# aliases allows those modules to work while newer modules use `settings`.

ASSISTANT_NAME = settings.assistant_name
USER_NAME = settings.user_name
VERSION = settings.version
DEBUG = settings.debug

LLM_MODEL = settings.llm_model
MODEL = settings.ollama_model.removeprefix("ollama/")
OLLAMA_MODEL = settings.ollama_model
OLLAMA_BASE_URL = settings.ollama_base_url

VOICE_RATE = settings.voice_rate
WAKE_WORD = settings.wake_word
TTS_ENGINE = settings.tts_engine
ELEVENLABS_API_KEY = settings.elevenlabs_api_key
ELEVENLABS_VOICE_ID = settings.elevenlabs_voice_id
ELEVENLABS_MODEL = settings.elevenlabs_model
WHISPER_MODEL = settings.whisper_model
WHISPER_DEVICE = settings.whisper_device
WHISPER_COMPUTE_TYPE = settings.whisper_compute_type
KOKORO_VOICE = settings.kokoro_voice

VOICE_ENERGY_THRESHOLD = settings.voice_energy_threshold
VOICE_DYNAMIC_ENERGY_RATIO = settings.voice_dynamic_energy_ratio
VOICE_PAUSE_THRESHOLD = settings.voice_pause_threshold
VOICE_PHRASE_THRESHOLD = settings.voice_phrase_threshold
VOICE_NON_SPEAKING_DURATION = settings.voice_non_speaking_duration
VOICE_MAX_CALIBRATED_THRESHOLD = settings.voice_max_calibrated_threshold
VOICE_INPUT_GAIN = settings.voice_input_gain

AUDIO_DUCKING_ENABLED = settings.audio_ducking_enabled
AUDIO_DUCKING_LEVEL = settings.audio_ducking_level

DATA_DIR = settings.data_dir
AUDIO_MODELS_DIR = settings.audio_models_dir
KOKORO_MODEL_PATH = AUDIO_MODELS_DIR / settings.kokoro_model_filename
KOKORO_VOICES_PATH = AUDIO_MODELS_DIR / settings.kokoro_voices_filename