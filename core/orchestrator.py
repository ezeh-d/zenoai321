from __future__ import annotations

from core.capabilities import describe
from core.model_router import choose_model
from core.plugin_manager import load_all
from core.safety import assess
from core.task_queue import add, list_tasks


def handle_core_command(command: str) -> str | None:
    lower = command.lower().strip()

    if lower in {"capabilities", "what can you do", "show capabilities"}:
        return describe()

    if lower in {"list plugins", "show plugins"}:
        names = list(load_all())
        return "Plugins: " + (", ".join(names) if names else "none")

    if lower.startswith("queue task "):
        goal = command[11:].strip()
        task = add(goal)
        return f"Task {task.id} queued: {goal}"

    if lower in {"list tasks", "task status"}:
        items = list_tasks()
        if not items:
            return "No queued tasks."
        lines = ["Tasks:"]
        lines.extend(f"- {item['id']} [{item['status']}] {item['goal']}" for item in items)
        return "\n".join(lines)

    if lower.startswith("which model for "):
        choice = choose_model(command[16:])
        return f"Model route: {choice.provider} — {choice.reason}"

    for name, module in load_all().items():
        try:
            if hasattr(module, "can_handle") and module.can_handle(command):
                return str(module.handle(command))
        except Exception as error:
            return f"Plugin {name} failed: {error}"

    state, message = assess(command)
    if state in {"blocked", "confirm"}:
        return message

    return None
