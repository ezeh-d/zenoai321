
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelChoice:
    provider: str
    reason: str

def choose_model(prompt: str, online: bool = True) -> ModelChoice:
    text = prompt.lower()
    if not online:
        return ModelChoice("ollama", "Offline mode")
    if any(k in text for k in ("code", "debug", "python", "javascript", "program")):
        return ModelChoice("claude-or-ollama", "Coding task")
    if any(k in text for k in ("screen", "image", "photo", "see")):
        return ModelChoice("vision-capable-cloud-or-local", "Vision task")
    if len(prompt) > 6000:
        return ModelChoice("long-context-cloud-or-ollama", "Long context")
    return ModelChoice("configured-default", "General task")
