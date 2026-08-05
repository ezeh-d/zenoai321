CAPABILITIES = {
    "Reasoning": ["multi-step planning", "goal decomposition", "reflection", "task queue", "model routing"],
    "Multi-agent": ["orchestrator", "researcher", "coder", "operator", "writer", "analyst", "delegate + solve_goal"],
    "Voice": ["Faster-Whisper STT", "Kokoro TTS", "wake phrases", "music ducking", "mic fallback"],
    "Vision": ["screenshots", "screen OCR (Tesseract)", "screen reading via see_screen"],
    "Memory": ["chat history", "second-brain notes", "Obsidian vault", "relevance recall (deep_recall)"],
    "Automation": ["apps", "mouse/keyboard", "browser", "files", "shell", "messaging"],
    "Internet + coding": ["web search", "browser automation", "project scaffolding", "write + run code"],
    "Security (defense only)": ["password audit", "file hashing", "localhost port audit", "log triage", "authorized learning lab"],
    "Mobile": ["local HTTP bridge (phone web UI)", "Telegram remote control"],
    "Extensibility": ["skills folder", "plugins folder", "auto plugin discovery"],
}


def describe() -> str:
    lines = ["REYES capabilities:"]
    lines.extend(f"- {name}: {', '.join(items)}" for name, items in CAPABILITIES.items())
    return "\n".join(lines)
