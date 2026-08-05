
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import json, threading, uuid

STORE = Path(__file__).resolve().parents[1] / "data" / "tasks.json"
LOCK = threading.Lock()

@dataclass
class Task:
    id: str
    goal: str
    status: str
    created_at: str
    result: str = ""

def _load() -> list[dict]:
    if not STORE.exists(): return []
    try: return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception: return []

def _save(items: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(items, indent=2), encoding="utf-8")

def add(goal: str) -> Task:
    task=Task(uuid.uuid4().hex[:8], goal, "queued", datetime.now().isoformat(timespec="seconds"))
    with LOCK:
        items=_load(); items.append(asdict(task)); _save(items)
    return task

def list_tasks(limit: int = 20) -> list[dict]:
    return _load()[-limit:]
