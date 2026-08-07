"""Foodie policy and an optional step-by-step cooking session for ZENO.

No provider, chef agent, food-memory vault or idle process is created here.
Recipes remain composed by the existing conversation engine; this module keeps
the response practical, safety-aware and stateful only when the owner asks to
cook together.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any

from reyes_agent import config


_LOCK = threading.RLock()
_FOOD_RE = re.compile(r"\b(foodie|cook|recipe|jollof|egusi|stew|soup|rice|bake|baking|meal plan|ingredients?|too salty|mushy|watery|allerg|vegan|vegetarian|gluten|dairy|chicken|fish|eggs?)\b", re.I)
_TOGETHER_RE = re.compile(r"\b(cook (?:it |this )?together|talk me through|we(?:'re| are) making|next step)\b", re.I)
_SAFETY_RE = re.compile(r"\b(raw|poultry|chicken|turkey|meat|seafood|leftovers?|reheat|spoiled|mould|mold|canning|ferment)\b", re.I)


def is_food_request(message: str) -> bool:
    return bool(_FOOD_RE.search(str(message or "")))


def directive(message: str) -> str:
    text = str(message or "")
    if not is_food_request(text):
        return ""
    policy = ("[Foodie Mode: be practical and culturally respectful. For a recipe give dish, servings, prep/cook time, "
              "ingredients and numbered steps first; history only if requested. Treat regional/family versions as variations, "
              "not one absolute correct recipe. Never claim to taste food or invent current prices. ")
    if _TOGETHER_RE.search(text):
        return policy + "Cooking together: give exactly one safe next step, then wait for the owner to say done. Use foodie_mode to keep the optional session step truthful.]"
    if _SAFETY_RE.search(text):
        return policy + "Safety: do not advise tasting questionable/raw food to test it. State uncertainty and recommend cautious handling, separation and proper temperature/storage guidance.]"
    if re.search(r"\b(unfamiliar|authentic|traditional|current price|restaurant|where can i buy)\b", text, re.I):
        return policy + "For unfamiliar regional technique or changing product/price information, use the existing research path or state uncertainty; do not invent authority.]"
    return policy + "For allergies/restrictions, never casually reintroduce the allergen. Explain realistic substitutions and their effect.]"


@contextmanager
def _connection():
    path = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS foodie_sessions (id INTEGER PRIMARY KEY CHECK(id=1), dish TEXT NOT NULL, steps_json TEXT NOT NULL, step_index INTEGER NOT NULL, updated_at REAL NOT NULL)")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus
        event_bus.publish(event_type, payload, source="foodie_mode")
    except Exception:
        pass


def _clean(value: object, limit: int = 360) -> str:
    return " ".join(str(value or "").split())[:limit]


def start_session(dish: object, steps: list[str]) -> dict[str, Any]:
    clean_steps = [_clean(step) for step in steps if _clean(step)][:24]
    if not clean_steps:
        raise ValueError("Provide at least one practical cooking step.")
    snapshot = {"dish": _clean(dish, 120) or "Cooking session", "steps": clean_steps, "step_index": 0, "updated_at": time.time()}
    with _LOCK, _connection() as conn:
        conn.execute("INSERT OR REPLACE INTO foodie_sessions VALUES(1,?,?,?,?)", (snapshot["dish"], json.dumps(clean_steps), 0, snapshot["updated_at"]))
    _publish("foodie.session_started", snapshot)
    return snapshot


def session_status() -> dict[str, Any] | None:
    with _LOCK, _connection() as conn:
        row = conn.execute("SELECT dish,steps_json,step_index,updated_at FROM foodie_sessions WHERE id=1").fetchone()
    if not row:
        return None
    try:
        steps = [str(x) for x in json.loads(row[1])]
    except (ValueError, TypeError):
        steps = []
    index = min(max(0, int(row[2])), len(steps))
    return {"dish": row[0], "steps": steps, "step_index": index, "current_step": steps[index] if index < len(steps) else "Completed", "updated_at": row[3]}


def advance_session() -> dict[str, Any] | None:
    snapshot = session_status()
    if snapshot is None:
        return None
    snapshot["step_index"] = min(len(snapshot["steps"]), snapshot["step_index"] + 1)
    snapshot["updated_at"] = time.time()
    with _LOCK, _connection() as conn:
        conn.execute("UPDATE foodie_sessions SET step_index=?,updated_at=? WHERE id=1", (snapshot["step_index"], snapshot["updated_at"]))
    snapshot["current_step"] = snapshot["steps"][snapshot["step_index"]] if snapshot["step_index"] < len(snapshot["steps"]) else "Completed"
    _publish("foodie.step_advanced", snapshot)
    return snapshot


def scale(ingredients: list[dict[str, Any]], from_servings: float, to_servings: float) -> list[dict[str, Any]]:
    if from_servings <= 0 or to_servings <= 0:
        raise ValueError("Serving counts must be positive.")
    ratio = to_servings / from_servings
    result = []
    for item in ingredients[:40]:
        amount = item.get("amount")
        name = _clean(item.get("name"), 120)
        if not name:
            continue
        try:
            adjusted = round(float(amount) * ratio, 2)
        except (TypeError, ValueError):
            adjusted = None
        result.append({"name": name, "amount": adjusted, "unit": _clean(item.get("unit"), 40)})
    return result
