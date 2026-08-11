"""SenseVoice availability and inference boundary.

Emotion/audio-event output is always a weak conversational signal and never
an identity, diagnosis, permission or consequential-decision input.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


class SenseVoiceBackend:
    def status(self) -> dict:
        installed = importlib.util.find_spec("funasr") is not None
        model = os.environ.get("ZENO_SENSEVOICE_MODEL", "").strip()
        ready = installed and bool(model and Path(model).exists())
        return {"state": "STANDBY" if ready else "NOT_CONFIGURED", "installed": installed,
                "model_configured": bool(model), "ready": ready, "lazy": True,
                "use_for_diagnosis": False, "use_for_permissions": False}

    def analyze(self, audio_path: str) -> dict:
        state = self.status()
        if not state["ready"]:
            return {"ok": False, **state, "reason": "SenseVoice package/model is not configured"}
        # FunASR model construction may download artifacts. Require a local
        # configured model path and import only on an explicit audio request.
        from funasr import AutoModel
        model = AutoModel(model=os.environ["ZENO_SENSEVOICE_MODEL"], disable_update=True)
        result = model.generate(input=str(Path(audio_path).resolve(strict=True)))
        return {"ok": True, "state": "COMPLETED", "verified": True,
                "result": result, "interpretation": "weak conversational signal only"}
