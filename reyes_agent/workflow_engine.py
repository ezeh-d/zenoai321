"""Owner-taught, reviewable desktop workflows.

Teaching is explicit and local.  While it is active the recorder captures
only replayable structure: foreground applications, pointer clicks, safe
navigation hotkeys, and ZENO's own browser-tool events.  It intentionally
does *not* save printable keystrokes, clipboard contents, passwords, or
browser cookies.  A replay pauses for text that the owner entered during a
demonstration, rather than quietly retaining it.

The engine owns one recorder and one managed replay task at most.  It
reuses the existing worker pool, Event Bus, permission engine, browser
runtime, and Living Memory instead of introducing parallel runtimes.
"""

from __future__ import annotations

import json
import queue
import re
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from reyes_agent import config


NORMAL = "NORMAL"
TEACH_MODE_STARTING = "TEACH_MODE_STARTING"
TEACH_MODE_RECORDING = "TEACH_MODE_RECORDING"
TEACH_MODE_PAUSED = "TEACH_MODE_PAUSED"
TEACH_MODE_REVIEW = "TEACH_MODE_REVIEW"
WORKFLOW_SAVING = "WORKFLOW_SAVING"
WORKFLOW_READY = "WORKFLOW_READY"
WORKFLOW_RUNNING = "WORKFLOW_RUNNING"
WORKFLOW_WAITING_FOR_INPUT = "WORKFLOW_WAITING_FOR_INPUT"
WORKFLOW_WAITING_FOR_CONFIRMATION = "WORKFLOW_WAITING_FOR_CONFIRMATION"
WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
WORKFLOW_FAILED = "WORKFLOW_FAILED"
WORKFLOW_CANCELLED = "WORKFLOW_CANCELLED"

MODES = frozenset({
    NORMAL, TEACH_MODE_STARTING, TEACH_MODE_RECORDING, TEACH_MODE_PAUSED,
    TEACH_MODE_REVIEW, WORKFLOW_SAVING, WORKFLOW_READY, WORKFLOW_RUNNING,
    WORKFLOW_WAITING_FOR_INPUT, WORKFLOW_WAITING_FOR_CONFIRMATION,
    WORKFLOW_COMPLETED, WORKFLOW_FAILED, WORKFLOW_CANCELLED,
})

_MAX_STEPS = 500
_MAX_NAME = 80
_WORKFLOW_DIR = config.VAULT_PATH / "07-System" / "workflows"
_SAFE_HOTKEYS = frozenset({
    "c", "v", "x", "a", "s", "l", "f", "r", "z", "y", "p",
})
_SAFE_KEYS = frozenset({
    "enter", "tab", "esc", "up", "down", "left", "right", "home", "end",
    "page up", "page down", "f5",
})
_REPLAYABLE_TOOLS = frozenset({
    "browser_open", "browser_click", "browser_scroll", "browser_read",
    "browser_extract", "browser_screenshot", "browser_vision_click",
    "open_app", "open_path",
})
_TEXT_TOOL_INPUTS = frozenset({"browser_fill", "write_clipboard"})
_NAME_RE = re.compile(r"[^a-z0-9]+")


class WorkflowError(ValueError):
    """A review, persistence, or replay problem shown plainly to the owner."""


class WorkflowNeedsInput(RuntimeError):
    def __init__(self, prompt: str, *, retry_step: bool = False) -> None:
        super().__init__(prompt)
        self.retry_step = retry_step


def _now() -> float:
    return time.time()


def _slug(value: str) -> str:
    value = _NAME_RE.sub("-", (value or "").strip().lower()).strip("-")
    return value[:_MAX_NAME] or "workflow"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _clean_url(value: str) -> str:
    """Retain a destination but never query parameters that may hold tokens."""
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:  # noqa: BLE001 - review can omit a malformed URL
        return ""


def _friendly_app(app: str) -> str:
    lowered = (app or "").strip().lower()
    aliases = {
        "chrome.exe": "chrome", "msedge.exe": "edge", "firefox.exe": "firefox",
        "winword.exe": "winword", "excel.exe": "excel", "powerpnt.exe": "powerpnt",
        "notepad.exe": "notepad", "explorer.exe": "explorer",
    }
    return aliases.get(lowered, lowered.removesuffix(".exe"))


def _describe_step(step: dict[str, Any], index: int) -> str:
    operation = step.get("op", "")
    if operation == "ensure_app":
        return f"Open or activate {step.get('app', 'the application')}"
    if operation == "focus":
        title = step.get("title", "")
        return f"Work in {step.get('app', 'the active application')}" + (f" ({title})" if title else "")
    if operation == "desktop_click":
        return f"Click {step.get('button', 'left')} in {step.get('expected_app', 'the active application')}"
    if operation == "hotkey":
        return f"Press {step.get('keys', '').upper()}"
    if operation == "key":
        return f"Press {step.get('key', '')}"
    if operation == "input_required":
        return "Enter the variable text manually (it was deliberately not saved)"
    if operation == "tool":
        return f"Use ZENO automation: {step.get('tool', 'tool')}"
    return f"Recorded action {index}"


class TeachingRecorder:
    """One explicit, bounded desktop demonstration recorder.

    ``keyboard`` delivers global callbacks on its own listener.  Its callback
    only queues a tiny event; a single recorder thread consumes at most 40 Hz
    while teaching.  Pointer state is sampled only while the owner has
    explicitly enabled Teach Mode.  No work touches the WebView host thread.
    """

    def __init__(self, engine: "WorkflowEngine") -> None:
        self._engine = engine
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._keyboard_events: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=256)
        self._keyboard_hook: Any = None
        self._subscription: queue.Queue | None = None
        self._modifiers: set[str] = set()
        self._typing = False
        self._last_left = False
        self._last_right = False
        self._last_foreground = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        from reyes_agent import event_bus

        self._stop.clear()
        self._paused.clear()
        self._subscription = event_bus.subscribe()
        try:
            import keyboard

            self._keyboard_hook = keyboard.hook(self._on_keyboard_event)
        except Exception as exc:  # mouse/app structure still remains useful
            self._engine.note_recorder_issue(f"Keyboard hotkeys unavailable: {type(exc).__name__}")
        self._thread = threading.Thread(target=self._loop, name="zeno-teach-recorder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._keyboard_hook is not None:
            try:
                import keyboard

                keyboard.unhook(self._keyboard_hook)
            except Exception:  # noqa: BLE001 - a hook must not block shutdown
                pass
            self._keyboard_hook = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._subscription is not None:
            try:
                from reyes_agent import event_bus

                event_bus.unsubscribe(self._subscription)
            except Exception:  # noqa: BLE001
                pass
            self._subscription = None

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def _on_keyboard_event(self, event: Any) -> None:
        try:
            self._keyboard_events.put_nowait((str(event.event_type), str(event.name or "").lower()))
        except queue.Full:
            # A key storm cannot turn a demonstration into an unbounded queue.
            pass

    @staticmethod
    def _pointer_state() -> tuple[int, int, bool, bool] | None:
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            point = POINT()
            user32 = ctypes.windll.user32
            if not user32.GetCursorPos(ctypes.byref(point)):
                return None
            left = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
            right = bool(user32.GetAsyncKeyState(0x02) & 0x8000)
            return int(point.x), int(point.y), left, right
        except Exception:  # noqa: BLE001 - capture remains optional, never fatal
            return None

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        try:
            import pyautogui

            width, height = pyautogui.size()
            return max(1, int(width)), max(1, int(height))
        except Exception:  # noqa: BLE001
            return 1920, 1080

    def _loop(self) -> None:
        last_foreground_sample = 0.0
        while not self._stop.wait(0.025):
            if self._paused.is_set():
                continue
            now = time.monotonic()
            if now - last_foreground_sample >= 0.2:
                last_foreground_sample = now
                self._record_foreground()
            self._record_pointer()
            self._drain_keyboard(max_events=20)
            self._drain_tool_events(max_events=20)

    def _record_foreground(self) -> None:
        try:
            from reyes_agent.activity_monitor import foreground_app

            app, title = foreground_app()
        except Exception:  # noqa: BLE001
            return
        app = (app or "").lower()
        title = (title or "").strip()
        if not app or (app.startswith("python") and "zeno" in title.lower()):
            return
        marker = app + "\n" + title
        if marker == self._last_foreground:
            return
        app_changed = not self._last_foreground or self._last_foreground.split("\n", 1)[0] != app
        self._last_foreground = marker
        if app_changed:
            self._engine.record_action({"op": "ensure_app", "app": _friendly_app(app), "expected_app": app})
        self._engine.record_action({"op": "focus", "app": app, "title": title[:160]})

    def _record_pointer(self) -> None:
        state = self._pointer_state()
        if state is None:
            return
        x, y, left, right = state
        # Record button release so a drag does not become a click at its start.
        button = "left" if self._last_left and not left else "right" if self._last_right and not right else ""
        self._last_left, self._last_right = left, right
        if not button:
            return
        width, height = self._screen_size()
        app = self._last_foreground.split("\n", 1)[0] if self._last_foreground else ""
        # A click that launched/focused the first demonstrated app can arrive
        # before the foreground sampler observes it. Do not save an unguarded
        # taskbar/dashboard coordinate that would be unsafe to replay later.
        if not app:
            return
        self._typing = False
        self._engine.record_action({
            "op": "desktop_click", "button": button,
            "x": round(max(0, min(width - 1, x)) / width, 5),
            "y": round(max(0, min(height - 1, y)) / height, 5),
            "expected_app": app,
            # Coordinates are only a fallback. The app guard is checked
            # before replay so an unexpected foreground window never gets a
            # blind click; the post-run owner check handles visual outcomes
            # a generic desktop recorder cannot infer safely.
            "verification": "foreground_guarded_manual_action",
        })

    def _drain_keyboard(self, *, max_events: int) -> None:
        for _ in range(max_events):
            try:
                event_type, key = self._keyboard_events.get_nowait()
            except queue.Empty:
                return
            if not key:
                continue
            modifier = key.replace("left ", "").replace("right ", "")
            if modifier in {"ctrl", "shift", "alt", "windows"}:
                if event_type == "down":
                    self._modifiers.add(modifier)
                else:
                    self._modifiers.discard(modifier)
                continue
            if event_type != "down":
                continue
            if "ctrl" in self._modifiers and key in _SAFE_HOTKEYS:
                self._typing = False
                self._engine.record_action({"op": "hotkey", "keys": f"ctrl+{key}"})
            elif key in _SAFE_KEYS:
                if self._typing and key in {"enter", "tab"}:
                    # The owner will enter and submit this variable manually
                    # before choosing Resume during replay; never submit twice.
                    self._typing = False
                else:
                    self._engine.record_action({"op": "key", "key": key})
            elif len(key) == 1 or key in {"space", "backspace", "delete"}:
                if not self._typing:
                    self._typing = True
                    app = self._last_foreground.split("\n", 1)[0] if self._last_foreground else "the application"
                    self._engine.record_action({"op": "input_required", "app": app})

    def _drain_tool_events(self, *, max_events: int) -> None:
        if self._subscription is None:
            return
        for _ in range(max_events):
            try:
                event = self._subscription.get_nowait()
            except queue.Empty:
                return
            if getattr(event, "type", "") == "tool.completed":
                self._engine.record_tool_action(getattr(event, "payload", {}))


class WorkflowEngine:
    """The one authoritative workflow draft and replay owner."""

    def __init__(self, *, root: Path | None = None,
                 recorder_factory: Callable[["WorkflowEngine"], TeachingRecorder] | None = None,
                 memory_writer: Callable[[str, int], str] | None = None) -> None:
        self._root = root or _WORKFLOW_DIR
        self._recorder_factory = recorder_factory or TeachingRecorder
        self._memory_writer = memory_writer
        self._lock = threading.RLock()
        self._mode = NORMAL
        self._draft: dict[str, Any] | None = None
        self._recorder: TeachingRecorder | None = None
        self._run_handle: Any = None
        # Replays can only be paused between recorded operations.  Cancelling
        # an in-flight browser/desktop call would make it ambiguous whether its
        # effect happened and could cause a duplicate action on resume.
        self._pause_requested = threading.Event()
        self._runtime: dict[str, Any] = {"mode": NORMAL, "workflow_id": "", "index": 0, "prompt": "", "error": ""}

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            from reyes_agent import event_bus

            event_bus.publish(event_type, payload, source="workflow_engine")
        except Exception:  # noqa: BLE001 - observability never breaks work
            pass

    def _set_mode(self, mode: str, *, prompt: str = "", error: str = "", **extra: Any) -> None:
        if mode not in MODES:
            raise WorkflowError(f"Unknown workflow mode '{mode}'.")
        with self._lock:
            self._mode = mode
            self._runtime.update({"mode": mode, "prompt": prompt, "error": error, **extra})
            snapshot = dict(self._runtime)
        self._publish("workflow.state_changed", snapshot)

    def note_recorder_issue(self, message: str) -> None:
        self._publish("workflow.recorder_notice", {"message": message[:300]})

    def start_teaching(self) -> str:
        try:
            from reyes_agent.kernel import get_kernel

            get_kernel().start_lazy("workflow-engine")
        except KeyError:
            # CLI use has no web-registered service but keeps the same one
            # engine instance; it must not create a second recorder.
            pass
        with self._lock:
            if self._mode in {TEACH_MODE_STARTING, TEACH_MODE_RECORDING, TEACH_MODE_PAUSED}:
                return "Teach Mode is already active. Demonstrate the task, then say 'stop learning'."
            if self._run_handle is not None and not self._run_handle.done:
                return "A workflow is running. Pause or cancel it before starting Teach Mode."
            self._draft = {"id": uuid.uuid4().hex[:12], "started_at": _now(), "steps": [], "issues": []}
        self._set_mode(TEACH_MODE_STARTING, prompt="Starting Teach Mode...")
        try:
            recorder = self._recorder_factory(self)
            recorder.start()
        except Exception as exc:  # noqa: BLE001
            self._set_mode(WORKFLOW_FAILED, error=f"Couldn't start Teach Mode: {type(exc).__name__}: {exc}")
            return self._runtime["error"]
        with self._lock:
            self._recorder = recorder
        self._set_mode(TEACH_MODE_RECORDING, prompt="Teach Mode is recording safe replay steps.")
        return ("Teach Mode is recording. Demonstrate the task. ZENO records apps, clicks, safe hotkeys, "
                "and its own browser actions, but never typed text, clipboard data, passwords, or cookies. "
                "Say 'ZENO, stop learning' when you are done.")

    def pause_teaching(self) -> str:
        with self._lock:
            recorder = self._recorder
            if self._mode != TEACH_MODE_RECORDING:
                return "Teach Mode is not recording."
        if recorder is not None:
            recorder.pause()
        self._set_mode(TEACH_MODE_PAUSED, prompt="Teach Mode is paused.")
        return "Teach Mode paused. Say 'resume learning' when you are ready."

    def resume_teaching(self) -> str:
        with self._lock:
            recorder = self._recorder
            if self._mode != TEACH_MODE_PAUSED:
                return "Teach Mode is not paused."
        if recorder is not None:
            recorder.resume()
        self._set_mode(TEACH_MODE_RECORDING, prompt="Teach Mode is recording safe replay steps.")
        return "Teach Mode resumed."

    def stop_teaching(self) -> str:
        with self._lock:
            if self._mode not in {TEACH_MODE_RECORDING, TEACH_MODE_PAUSED}:
                return "Teach Mode is not active."
            recorder, self._recorder = self._recorder, None
        if recorder is not None:
            recorder.stop()
        with self._lock:
            count = len((self._draft or {}).get("steps", []))
        self._set_mode(TEACH_MODE_REVIEW, prompt="Review the learned workflow before saving it.")
        return (f"Learning stopped. I captured {count} reviewable step(s). What should I call this workflow? "
                "Say the name, then ask me to review or save it.")

    def discard_teaching(self) -> str:
        with self._lock:
            recorder, self._recorder = self._recorder, None
            self._draft = None
        if recorder is not None:
            recorder.stop()
        self._set_mode(NORMAL)
        self._publish("workflow.discarded", {})
        return "Discarded the unsaved workflow."

    def record_action(self, action: dict[str, Any]) -> None:
        with self._lock:
            if self._mode != TEACH_MODE_RECORDING or self._draft is None:
                return
            steps = self._draft["steps"]
            if len(steps) >= _MAX_STEPS:
                self._draft["issues"].append("Recording reached the 500-step safety limit.")
                recorder = self._recorder
                if recorder is not None:
                    recorder.pause()
                pause = True
            else:
                action = {k: v for k, v in action.items() if isinstance(k, str)}
                steps.append(action)
                pause = False
                sequence = len(steps)
        if pause:
            self._set_mode(TEACH_MODE_PAUSED, prompt="Recording reached the 500-step limit.")
            return
        self._publish("workflow.step_recorded", {"sequence": sequence, "operation": action.get("op", "")})

    def record_tool_action(self, payload: dict[str, Any]) -> None:
        tool = str(payload.get("tool", "")).strip()
        params = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        if tool in _TEXT_TOOL_INPUTS:
            self.record_action({"op": "input_required", "app": "browser", "source": tool})
            return
        if tool not in _REPLAYABLE_TOOLS:
            return
        safe_params = dict(params)
        if tool == "browser_open":
            safe_params["url"] = _clean_url(str(safe_params.get("url", "")))
            if not safe_params["url"]:
                return
        self.record_action({"op": "tool", "tool": tool, "params": safe_params})

    def review(self) -> str:
        with self._lock:
            draft = dict(self._draft or {})
            mode = self._mode
        if not draft or mode not in {TEACH_MODE_REVIEW, WORKFLOW_SAVING, WORKFLOW_READY}:
            return "There is no learned workflow awaiting review."
        steps = draft.get("steps", [])
        lines = [f"LEARNED WORKFLOW REVIEW — {len(steps)} step(s)"]
        for index, step in enumerate(steps, start=1):
            lines.append(f"{index}. {_describe_step(step, index)}")
        if draft.get("issues"):
            lines.append("Notes:")
            lines.extend(f"- {issue}" for issue in draft["issues"])
        lines.append("Typed values, clipboard data, passwords, and cookies were not retained; replay pauses for those inputs.")
        lines.append("Say 'save it as <name>' to approve and save this workflow, or 'discard learning'.")
        return "\n".join(lines)

    def save(self, name: str) -> str:
        clean_name = " ".join((name or "").split())[:_MAX_NAME]
        with self._lock:
            draft = self._draft
            if self._mode != TEACH_MODE_REVIEW or draft is None:
                return "Stop learning and review the steps before saving a workflow."
            if not clean_name:
                return "Give the workflow a short name before saving it."
            if not draft.get("steps"):
                return "Nothing replayable was captured, so there is no workflow to save."
        self._set_mode(WORKFLOW_SAVING, prompt="Saving approved workflow...")
        identifier = _slug(clean_name)
        path = self._root / f"{identifier}.json"
        suffix = 2
        while path.exists():
            path = self._root / f"{identifier}-{suffix}.json"
            suffix += 1
        workflow = {
            "id": path.stem,
            "name": clean_name,
            "schema": 1,
            "created_at": _now(),
            "approved_at": _now(),
            "steps": list(draft["steps"]),
            "requires_owner_visual_confirmation": any(
                step.get("op") in {"desktop_click", "hotkey", "key"}
                for step in draft["steps"]
            ),
            "issues": list(draft.get("issues", [])),
            "privacy": "Typed text, clipboard data, passwords, and cookies are intentionally excluded.",
            "memory_id": "",
        }
        try:
            _atomic_json(path, workflow)
            try:
                if self._memory_writer is not None:
                    workflow["memory_id"] = self._memory_writer(clean_name, len(workflow["steps"]))
                else:
                    from reyes_agent import living_memory

                    memory = living_memory.create(
                        f"Approved reusable workflow: {clean_name}. {len(workflow['steps'])} replayable step(s).",
                        title=f"Workflow: {clean_name}", memory_type="workflow", actor="user",
                        reason="Owner approved a demonstrated workflow", source="workflow_engine",
                        tags=["workflow"],
                    )
                    workflow["memory_id"] = memory.get("id", "")
                _atomic_json(path, workflow)
            except Exception as exc:  # persistence is authoritative; memory is an indexed reference
                workflow["issues"].append(f"Living Memory reference deferred: {type(exc).__name__}")
                _atomic_json(path, workflow)
        except OSError as exc:
            self._set_mode(WORKFLOW_FAILED, error=f"Couldn't save workflow: {exc}")
            return self._runtime["error"]
        with self._lock:
            self._draft = dict(workflow)
        self._set_mode(WORKFLOW_READY, workflow_id=workflow["id"], prompt="Workflow is approved and ready.")
        self._publish("workflow.saved", {"id": workflow["id"], "name": clean_name, "steps": len(workflow["steps"])})
        return f"Saved and approved '{clean_name}' with {len(workflow['steps'])} step(s). You can ask ZENO to run it later."

    def _load_all(self) -> list[dict[str, Any]]:
        if not self._root.exists():
            return []
        records = []
        for path in sorted(self._root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("id") and data.get("name"):
                records.append(data)
        return sorted(records, key=lambda item: item.get("created_at", 0), reverse=True)

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            {"id": item["id"], "name": item["name"], "steps": len(item.get("steps", [])),
             "approved_at": item.get("approved_at", 0), "issues": list(item.get("issues", []))}
            for item in self._load_all()
        ]

    def _find(self, value: str) -> dict[str, Any] | None:
        wanted = (value or "").strip().casefold()
        if not wanted:
            return None
        for workflow in self._load_all():
            if workflow["id"].casefold() == wanted or workflow["name"].casefold() == wanted:
                return workflow
        return None

    @staticmethod
    def _required_capabilities(workflow: dict[str, Any]) -> set[str]:
        from reyes_agent import permissions

        needed: set[str] = set()
        for step in workflow.get("steps", []):
            operation = step.get("op")
            if operation in {"desktop_click", "hotkey", "key"}:
                needed.add("desktop_automation")
            elif operation == "ensure_app":
                needed.add("app_control")
            elif operation == "tool":
                capability = permissions.capability_for_tool(str(step.get("tool", "")))
                if capability:
                    needed.add(capability)
        return needed

    def _permission_state(self, workflow: dict[str, Any]) -> tuple[list[str], list[str]]:
        from reyes_agent import permissions

        blocked, confirmation = [], []
        for capability in sorted(self._required_capabilities(workflow)):
            state = permissions.state_for(capability)
            if state == permissions.BLOCKED:
                blocked.append(capability)
            elif state == permissions.CONFIRM:
                confirmation.append(capability)
        return blocked, confirmation

    def start_run(self, name: str, *, confirmed: bool = False, resume: bool = False) -> str:
        workflow = self._find(name)
        if workflow is None:
            return f"No approved workflow named '{name}'."
        if not workflow.get("approved_at"):
            return f"'{workflow.get('name', name)}' has not been approved in review."
        blocked, confirmation = self._permission_state(workflow)
        if blocked:
            self._set_mode(WORKFLOW_FAILED, workflow_id=workflow["id"],
                           error="Workflow requires blocked capability: " + ", ".join(blocked))
            return self._runtime["error"]
        if confirmation and not confirmed:
            self._set_mode(WORKFLOW_WAITING_FOR_CONFIRMATION, workflow_id=workflow["id"],
                           prompt="Workflow needs confirmation for: " + ", ".join(confirmation))
            return (f"'{workflow['name']}' is ready but needs confirmation for: {', '.join(confirmation)}. "
                    "Review the workflow, then confirm that run.")
        with self._lock:
            if self._run_handle is not None and not self._run_handle.done:
                return "Another workflow is already running. Pause or cancel it first."
            prior = self._runtime if resume and self._runtime.get("workflow_id") == workflow["id"] else {}
            start_index = int(prior.get("index", 0)) if resume else 0
            owner_visual_confirmed = bool(prior.get("owner_visual_confirmed", False))
            if resume and prior.get("awaiting_owner_visual_confirmation"):
                owner_visual_confirmed = True
            self._runtime.update({"workflow_id": workflow["id"], "name": workflow["name"], "index": start_index,
                                  "total": len(workflow.get("steps", [])), "prompt": "", "error": "",
                                  "owner_visual_confirmed": owner_visual_confirmed,
                                  "awaiting_owner_visual_confirmation": False})
        if owner_visual_confirmed and resume and prior.get("awaiting_owner_visual_confirmation"):
            self._record_verification(True, "Owner visually confirmed the final desktop result.")
        self._pause_requested.clear()
        self._set_mode(WORKFLOW_RUNNING, workflow_id=workflow["id"], index=start_index,
                       prompt=f"Running {workflow['name']}.")
        from reyes_agent.kernel import get_kernel
        from reyes_agent.worker_pool import PRIORITY_MISSION

        try:
            handle = get_kernel().submit(
                self._run_job, workflow["id"], start_index,
                name=f"workflow:{workflow['id']}", priority=PRIORITY_MISSION,
                timeout=900, with_context=True,
            )
        except Exception as exc:  # noqa: BLE001
            self._set_mode(WORKFLOW_FAILED, workflow_id=workflow["id"], error=f"Couldn't schedule workflow: {exc}")
            return self._runtime["error"]
        with self._lock:
            self._run_handle = handle
        self._publish("workflow.started", {"id": workflow["id"], "name": workflow["name"], "start_index": start_index})
        return f"Started '{workflow['name']}'. The Mini Orb will show its live progress."

    def confirm_run(self, name: str) -> str:
        with self._lock:
            waiting = self._mode == WORKFLOW_WAITING_FOR_CONFIRMATION
            current = self._runtime.get("workflow_id", "")
        workflow = self._find(name)
        if workflow is None:
            return f"No workflow named '{name}'."
        if not waiting or current != workflow["id"]:
            return "That workflow is not waiting for confirmation."
        return self.start_run(workflow["id"], confirmed=True)

    def pause_run(self) -> str:
        with self._lock:
            if self._mode != WORKFLOW_RUNNING:
                return "No workflow is running."
        # The required state list has no separate workflow-pause state.  Do
        # not cancel a current operation: it could have already clicked or
        # submitted something.  The worker observes this after the operation
        # and changes to the resumable input-wait state at that safe boundary.
        self._pause_requested.set()
        return "Pause requested. ZENO will pause after the current safe step."

    def cancel_run(self) -> str:
        with self._lock:
            handle = self._run_handle
            if self._mode not in {WORKFLOW_RUNNING, WORKFLOW_WAITING_FOR_INPUT, WORKFLOW_WAITING_FOR_CONFIRMATION}:
                return "No active workflow to cancel."
        self._pause_requested.clear()
        self._set_mode(WORKFLOW_CANCELLED, prompt="Workflow cancelled by owner.")
        if handle is not None:
            handle.cancel()
        self._publish("workflow.cancelled", {"workflow_id": self._runtime.get("workflow_id", "")})
        return "Workflow cancelled. No further actions will run."

    def resume_run(self, name: str) -> str:
        with self._lock:
            state = self._mode
        if state != WORKFLOW_WAITING_FOR_INPUT:
            return "That workflow is not paused or waiting for input."
        return self.start_run(name, confirmed=True, resume=True)

    def _run_job(self, context, workflow_id: str, start_index: int) -> None:
        from reyes_agent.worker_pool import TaskCancelled

        workflow = self._find(workflow_id)
        if workflow is None:
            raise WorkflowError("The saved workflow no longer exists.")
        steps = workflow.get("steps", [])
        try:
            for index in range(start_index, len(steps)):
                context.check_cancelled()
                step = steps[index]
                with self._lock:
                    self._runtime["index"] = index
                context.progress("workflow_step", workflow_id=workflow_id, step=index + 1, total=len(steps))
                self._publish("workflow.progress", {"workflow_id": workflow_id, "step": index + 1,
                                                     "total": len(steps), "operation": step.get("op", "")})
                try:
                    result = self._execute_step(context, step)
                    self._verify_step(step, result)
                except WorkflowNeedsInput as need:
                    next_index = index if need.retry_step else index + 1
                    self._set_mode(WORKFLOW_WAITING_FOR_INPUT, workflow_id=workflow_id, index=next_index,
                                   prompt=str(need))
                    self._publish("workflow.waiting_for_input", {"workflow_id": workflow_id, "step": index + 1,
                                                                   "prompt": str(need)})
                    return
                if self._pause_requested.is_set():
                    self._pause_requested.clear()
                    self._set_mode(
                        WORKFLOW_WAITING_FOR_INPUT,
                        workflow_id=workflow_id,
                        index=index + 1,
                        prompt="Workflow paused after a completed step. Resume when you are ready.",
                    )
                    self._publish("workflow.paused", {"workflow_id": workflow_id, "step": index + 1})
                    return
            with self._lock:
                needs_owner_check = bool(workflow.get("requires_owner_visual_confirmation"))
                owner_checked = bool(self._runtime.get("owner_visual_confirmed"))
            if needs_owner_check and not owner_checked:
                self._set_mode(
                    WORKFLOW_WAITING_FOR_INPUT, workflow_id=workflow_id, index=len(steps),
                    prompt="Inspect the final desktop result, then choose Resume to confirm it is correct.",
                    awaiting_owner_visual_confirmation=True,
                )
                self._publish("workflow.waiting_for_visual_verification", {"workflow_id": workflow_id})
                return
            self._set_mode(WORKFLOW_COMPLETED, workflow_id=workflow_id, index=len(steps),
                           prompt=f"Completed {workflow['name']}.")
            self._publish("workflow.completed", {"workflow_id": workflow_id, "name": workflow["name"]})
        except TaskCancelled:
            with self._lock:
                mode = self._mode
            if mode not in {WORKFLOW_WAITING_FOR_INPUT, WORKFLOW_CANCELLED}:
                self._set_mode(WORKFLOW_CANCELLED, workflow_id=workflow_id, prompt="Workflow cancelled.")
            raise
        except Exception as exc:  # noqa: BLE001 - one bad replay must remain isolated
            self._set_mode(WORKFLOW_FAILED, workflow_id=workflow_id, error=f"{type(exc).__name__}: {exc}")
            self._publish("workflow.failed", {"workflow_id": workflow_id, "error": f"{type(exc).__name__}: {exc}"})
            raise

    def _record_verification(self, verified: bool, evidence: str) -> None:
        """Record evidence, not an optimistic success label."""
        try:
            from reyes_agent.confidence import record_verification

            record_verification(verified, evidence)
        except Exception:  # noqa: BLE001 -- verification telemetry is best effort
            pass
        self._publish("workflow.verification", {"verified": verified, "evidence": evidence[:240]})

    def _verify_step(self, step: dict[str, Any], result: str | None) -> None:
        """Use a real app/browser observation wherever one is available."""
        operation = step.get("op")
        expected = str(step.get("expected_app") or (step.get("app") if operation == "focus" else "")).lower()
        # Raw desktop actions are foreground-guarded immediately *before*
        # they run in _execute_step. Do not demand that they leave the same
        # app in front afterwards: opening/saving may legitimately change it.
        if expected and operation not in {"desktop_click", "hotkey", "key"}:
            try:
                from reyes_agent.activity_monitor import foreground_app

                active, _title = foreground_app()
            except Exception:  # noqa: BLE001
                active = ""
            if not active:
                try:
                    from reyes_agent.confidence import record

                    record("visual", None, f"Foreground application could not be observed for {expected}.")
                except Exception:  # noqa: BLE001
                    pass
                self._publish("workflow.verification", {
                    "verified": None,
                    "evidence": f"Foreground application unavailable; did not claim {expected} was focused.",
                })
                return
            if expected not in active.lower():
                self._record_verification(False, f"Expected foreground app '{expected}', observed '{active or 'unknown'}'.")
                # The raw action has not run when this is checked before a
                # desktop action; focus/manual recovery is safer than retrying
                # a potentially consequential click.
                raise WorkflowNeedsInput(f"Focus {expected} before ZENO continues.", retry_step=True)
            self._record_verification(True, f"Foreground app verified as {expected}.")
            return
        if operation in {"desktop_click", "hotkey", "key"}:
            try:
                from reyes_agent.confidence import record

                record("visual", None, "Manual desktop action awaits the owner's final visual confirmation.")
            except Exception:  # noqa: BLE001
                pass
            self._publish("workflow.verification", {
                "verified": None,
                "evidence": "Manual desktop action dispatched; final visual confirmation is required.",
            })
            return
        if operation == "tool":
            tool = str(step.get("tool", ""))
            evidence = str(result or "")
            verified = bool(evidence) and not evidence.lower().startswith(("error", "browser error"))
            self._record_verification(verified, f"{tool} returned observed browser/tool evidence.")
            if not verified:
                raise WorkflowError(f"{tool} did not return verification evidence.")

    def _execute_step(self, context, step: dict[str, Any]) -> str | None:
        operation = step.get("op")
        if operation == "focus":
            return None
        if operation == "input_required":
            raise WorkflowNeedsInput(
                f"Enter the needed text in {step.get('app', 'the application')} yourself, then choose Resume. "
                "ZENO deliberately did not save the demonstrated text."
            )
        if operation == "ensure_app":
            from reyes_agent.tools import run_tool

            result = run_tool("open_app", {"name_or_path": step.get("app", "")})
            if str(result).lower().startswith("error"):
                raise WorkflowError(str(result))
            context.wait(1.0)
            return str(result)
        expected = str(step.get("expected_app", "")).lower()
        if expected:
            try:
                from reyes_agent.activity_monitor import foreground_app

                active, _title = foreground_app()
            except Exception:  # noqa: BLE001
                active = ""
            if expected not in (active or "").lower():
                raise WorkflowNeedsInput(f"Focus {expected} before ZENO continues.", retry_step=True)
        if operation in {"desktop_click", "hotkey", "key"}:
            try:
                import pyautogui
            except ImportError as exc:
                raise WorkflowError(f"Desktop automation is unavailable: {exc}") from exc
            pyautogui.FAILSAFE = True
            if operation == "desktop_click":
                width, height = pyautogui.size()
                x = max(0, min(width - 1, round(float(step.get("x", 0)) * width)))
                y = max(0, min(height - 1, round(float(step.get("y", 0)) * height)))
                pyautogui.click(x, y, button=step.get("button", "left"))
            elif operation == "hotkey":
                pyautogui.hotkey(*str(step.get("keys", "")).split("+"))
            else:
                pyautogui.press(str(step.get("key", "enter")))
            context.wait(0.25)
            return "desktop action dispatched"
        if operation == "tool":
            tool = str(step.get("tool", ""))
            if tool not in _REPLAYABLE_TOOLS:
                raise WorkflowError(f"Workflow step uses unsupported tool '{tool}'.")
            from reyes_agent.tools import run_tool

            result = run_tool(tool, dict(step.get("params", {})))
            if str(result).startswith("Queued as request"):
                raise WorkflowNeedsInput("This step needs a pending approval in ZENO before it can continue.", retry_step=True)
            if str(result).lower().startswith("error") or str(result).lower().startswith("browser error"):
                raise WorkflowError(str(result))
            return str(result)
        raise WorkflowError(f"Unknown recorded operation '{operation}'.")

    def status(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._runtime)
            result["mode"] = self._mode
            result["draft_steps"] = len((self._draft or {}).get("steps", []))
            result["task"] = self._run_handle.snapshot() if self._run_handle is not None else None
        return result

    def shutdown(self) -> None:
        with self._lock:
            recorder, self._recorder = self._recorder, None
            handle = self._run_handle
        if recorder is not None:
            recorder.stop()
        if handle is not None and not handle.done:
            handle.cancel()


_engine: WorkflowEngine | None = None
_engine_lock = threading.Lock()


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = WorkflowEngine()
    return _engine
