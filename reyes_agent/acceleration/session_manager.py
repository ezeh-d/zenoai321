"""Bounded shared ONNX sessions, created only on first real inference."""
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any


class SessionManager:
    def __init__(self, max_sessions: int = 3):
        self.max_sessions = max(1, min(int(max_sessions), 8))
        self._sessions: OrderedDict[tuple[str, tuple[str, ...]], Any] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, model_path: str | Path, providers: list[str] | None = None):
        import onnxruntime
        target = Path(model_path).resolve(strict=True)
        selected = tuple(providers or ["CPUExecutionProvider"])
        available = set(onnxruntime.get_available_providers())
        if not set(selected) <= available:
            raise RuntimeError(f"Unavailable ONNX provider(s): {sorted(set(selected) - available)}")
        key = (str(target), selected)
        with self._lock:
            session = self._sessions.pop(key, None)
            if session is None:
                options = onnxruntime.SessionOptions()
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
                options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
                session = onnxruntime.InferenceSession(str(target), sess_options=options, providers=list(selected))
            self._sessions[key] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            return session

    def clear(self) -> int:
        with self._lock:
            count = len(self._sessions)
            self._sessions.clear()
            return count

    def metrics(self) -> dict:
        with self._lock:
            return {"sessions": len(self._sessions), "max_sessions": self.max_sessions,
                    "models": [Path(key[0]).name for key in self._sessions]}


_MANAGER = SessionManager()


def get_session_manager() -> SessionManager:
    return _MANAGER
