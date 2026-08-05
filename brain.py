"""REYES's brain: conversation + memory + tool use.

Flow for each user message:
  1. Build the message list (system prompt + recent memory + user text).
  2. Ask the LLM.
  3. If the LLM asked to use a tool (JSON), run it, feed the result back, loop.
  4. Otherwise, that's the final reply.

Tool protocol is provider-agnostic (works with GPT, Claude, Gemini, Ollama):
the model replies with a fenced JSON block to call a tool, or plain text to
answer the user.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from config import settings
from llm import LLM
from logger import log
from memory.conversation import ConversationMemory
from memory.second_brain import SecondBrain
from skills.browser import Browser
from skills.coder import Coder
from skills.computer import Computer
from skills.gui import GUI
from skills.messaging import Messaging
from skills.obsidian import Obsidian
from skills.slack import Slack

MAX_STEPS = 6


class Brain:
    def __init__(self, approver: Callable[[str], bool], on_tool: Callable[[str], None] | None = None):
        self.llm = LLM()
        self.memory = ConversationMemory(settings.data_dir)
        self.brain2 = SecondBrain(settings.data_dir)
        self.computer = Computer(approver, settings.data_dir)
        self.browser = Browser()
        self.messaging = Messaging()
        self.gui = GUI(approver, settings.data_dir)
        self.slack = Slack()
        self.coder = Coder(approver)
        self.obsidian = Obsidian()
        self.on_tool = on_tool or (lambda _s: None)
        self.tools = self._register_tools()

    # ------------------------------------------------------------------
    def _register_tools(self) -> dict[str, tuple[Callable, str]]:
        c, b, m, s = self.computer, self.browser, self.messaging, self.brain2
        g, sl, cd = self.gui, self.slack, self.coder
        ob = self.obsidian
        # advanced subsystems (planning, multi-agent, security)
        from core.planner import quick_plan
        from agents.orchestrator import delegate as _delegate, solve_goal as _solve
        from security import defense as _sec, lab as _lab
        return {
            # computer
            "list_dir": (c.list_dir, "List a folder. args: {path}"),
            "read_file": (c.read_file, "Read a file. args: {path, max_chars?}"),
            "search_files": (c.search_files, "Find files by name. args: {query, root?, limit?}"),
            "write_file": (c.write_file, "Write/overwrite a file. args: {path, content}"),
            "append_file": (c.append_file, "Append to a file. args: {path, content}"),
            "make_dir": (c.make_dir, "Create a folder. args: {path}"),
            "delete_path": (c.delete_path, "Delete file/folder (asks permission). args: {path}"),
            "move_path": (c.move_path, "Move/rename (asks permission). args: {src, dst}"),
            "open_app": (c.open_app, "Open an application. args: {name}"),
            "run_command": (c.run_command, "Run a shell command (asks permission). args: {command}"),
            "screenshot": (c.screenshot, "Take a screenshot. args: {path?}"),
            "clipboard_get": (c.clipboard_get, "Read the clipboard. args: {}"),
            "clipboard_set": (c.clipboard_set, "Set the clipboard. args: {text}"),
            "system_info": (c.system_info, "System/hardware info. args: {}"),
            # browser
            "browse": (b.browse, "Open a website. args: {url}"),
            "find_on_page": (b.find_on_page, "Search current page text. args: {query}"),
            "type_text": (b.type_text, "Fill a field. args: {selector, text}"),
            "click": (b.click, "Click an element. args: {selector}"),
            "read_page": (b.read_page, "Read current page text. args: {}"),
            "close_browser": (b.close_browser, "Close the browser. args: {}"),
            # messaging
            "send_email": (m.send_email, "Send an email. args: {to, subject, body}"),
            "read_email": (m.read_email, "Read inbox. args: {limit?, unread_only?}"),
            "send_telegram": (m.send_telegram, "Send a Telegram message. args: {text, chat_id?}"),
            "read_telegram": (m.read_telegram, "Read recent Telegram. args: {limit?}"),
            # second brain
            "remember": (s.remember, "Save a note to long-term memory. args: {text, tags?}"),
            "recall": (s.recall, "Search your notes. args: {query, k?}"),
            "list_notes": (s.list_notes, "List recent notes. args: {limit?}"),
            # universal GUI control (works in ANY app)
            "gui_screen_size": (g.screen_size, "Get screen resolution. args: {}"),
            "gui_mouse_position": (g.mouse_position, "Get mouse coords. args: {}"),
            "gui_move": (g.move, "Move mouse. args: {x, y}"),
            "gui_click": (g.click, "Click (asks permission). args: {x?, y?, button?, clicks?}"),
            "gui_type": (g.type_text, "Type text into focused app (asks permission). args: {text}"),
            "gui_press": (g.press, "Press a key (asks permission). args: {key}"),
            "gui_hotkey": (g.hotkey, "Key combo like ctrl+c (asks permission). args: {combo}"),
            "gui_scroll": (g.scroll, "Scroll. args: {amount}"),
            "gui_locate": (g.locate, "Find an image on screen. args: {image_path}"),
            "gui_read_screen": (g.read_screen, "OCR the screen to text. args: {}"),
            # slack
            "slack_channels": (sl.slack_channels, "List Slack channels + ids. args: {}"),
            "slack_send": (sl.slack_send, "Post to a Slack channel. args: {channel, text}"),
            "slack_read": (sl.slack_read, "Read recent Slack messages. args: {channel, limit?}"),
            # coder / website builder
            "create_project": (cd.create_project,
                               "Scaffold a runnable project. args: {name, kind}  kind=static-site|react|flask|python"),
            "write_code": (cd.write_code, "Write a code file in a project. args: {project, relpath, content}"),
            "run_project": (cd.run, "Run a build/dev/test command in a project (asks permission). args: {project, command}"),
            # obsidian (editable markdown second brain / knowledge graph)
            "obsidian_save": (ob.obsidian_save, "Save a note to the Obsidian vault. args: {title, content, tags?, links?}"),
            "obsidian_read": (ob.obsidian_read, "Read a note from the vault. args: {title}"),
            "obsidian_search": (ob.obsidian_search, "Search the vault. args: {query, k?}"),
            "obsidian_list": (ob.obsidian_list, "List recent vault notes. args: {limit?}"),
            # planning & reasoning
            "plan": (quick_plan, "Draft an ordered step-plan for a goal. args: {goal}"),
            # multi-agent
            "delegate": (_delegate, "Hand a task to the best specialist agent "
                         "(researcher/coder/operator/writer/analyst). args: {task, agent?}"),
            "solve_goal": (_solve, "Plan a complex goal and run it across agents. args: {goal}"),
            # long-term memory
            "deep_recall": (self._deep_recall, "Search long-term memory (notes + history) "
                            "for what's relevant. args: {query, k?}"),
            # security (defense + authorized learning only)
            "sec_passcheck": (_sec.passcheck, "Rate a password's strength locally. args: {password}"),
            "sec_hash": (_sec.hash_file, "Integrity hash of a file. args: {path, algo?}"),
            "sec_ports": (_sec.scan_ports, "Audit open ports on THIS machine. args: {start?, end?}"),
            "sec_scanlog": (_sec.scan_log, "Flag suspicious lines in a log. args: {path}"),
            "sec_learn": (_lab.learn, "Explain a security topic / list legal labs. args: {topic}"),
            # vision (read what's on screen)
            "see_screen": (self._see, "Capture the screen and read its text (OCR). args: {}"),
        }

    def _deep_recall(self, query: str, k: int = 3) -> str:
        """Relevance search over long-term notes + recent conversation."""
        from memory.retrieval import deep_recall
        notes: list[str] = []
        try:
            raw = self.brain2.list_notes(limit=200)
            notes = [str(raw)] if isinstance(raw, str) else [str(n) for n in raw]
        except Exception:
            pass
        history = [f"{t['role']}: {t['content']}" for t in self.memory.recent(limit=50)]
        return deep_recall(query, notes=notes, history=history, k=k)

    def _see(self) -> str:
        """Vision-lite: screenshot the screen and OCR its text."""
        try:
            self.computer.screenshot()
        except Exception:
            pass
        try:
            text = self.gui.read_screen()
            return text or "Captured the screen, but found no readable text."
        except Exception as e:
            return (f"Screen captured, but OCR isn't available ({e}). "
                    "Install pytesseract + the Tesseract binary to read screen text.")

    def _system_prompt(self) -> str:
        tool_lines = "\n".join(f"- {name}: {desc}" for name, (_fn, desc) in self.tools.items())
        return (
            f"You are {settings.assistant_name} — {settings.user_name}'s personal AI: a "
            "brilliant, unflappable right hand, the quiet genius who runs everything "
            "behind the scenes and makes it look effortless. Less chatbot, more the "
            f"operator {settings.user_name} trusts to just handle it.\n\n"

            "── MANNER ──\n"
            "Composed, precise, quick. Dry, understated wit; light teasing, never "
            "disrespect. Economy of words — answer first, elaborate only when it earns "
            f"its place. Address {settings.user_name} directly, an occasional 'sir'/'ma'am' "
            "when it fits. Never sycophantic; if it's a bad idea, say so once, politely. "
            "Report status crisply: 'Done.' 'Handled.' 'One moment.'\n\n"

            "── HOW YOU WORK ──\n"
            "You don't just talk — you act, using real tools on this machine. For a "
            "complex or multi-part goal, `plan` it first, then work the steps; hand "
            "specialist work to `delegate` (research, coding, desktop ops, writing, "
            "analysis) or `solve_goal` for the whole thing. Pull relevant history with "
            "`deep_recall`. On security you work defense and authorized testing ONLY — "
            "never intrusion or malware. Confirm before anything destructive, and never "
            f"help with anything that would harm {settings.user_name} or others.\n\n"

            "── TOOLS ──\n"
            "To use one, reply with ONLY a JSON object in a fenced block, nothing else:\n"
            '```json\n{"tool": "tool_name", "args": {"key": "value"}}\n```\n'
            "You then receive a line starting with [TOOL RESULT]. Use it, then call "
            "another tool or give your final answer in plain text (no JSON). Only reach "
            "for a tool when the task needs a real action or fresh info; otherwise just "
            "talk. Save things worth keeping with `remember`; recall the past with "
            "`recall` or `deep_recall`.\n\n"

            f"Available tools:\n{tool_lines}"
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_tool_call(text: str) -> dict | None:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidate = fenced.group(1) if fenced else None
        if candidate is None:
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                candidate = stripped
        if candidate is None:
            return None
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "tool" in data:
                return data
        except json.JSONDecodeError:
            return None
        return None

    def _run_tool(self, name: str, args: dict) -> str:
        entry = self.tools.get(name)
        if not entry:
            return f"Unknown tool '{name}'."
        func, _desc = entry
        try:
            return str(func(**(args or {})))
        except TypeError as e:
            return f"Bad arguments for {name}: {e}"
        except Exception as e:  # noqa: BLE001
            log.exception("Tool %s failed", name)
            return f"Tool {name} error: {e}"

    # ------------------------------------------------------------------
    def chat(self, user_message: str) -> str:
        self.memory.add("user", user_message)

        # Fast path: built-in core commands (capabilities, tasks, plugins, model
        # routing, safety). If one matches, answer directly without the LLM.
        try:
            from core.orchestrator import handle_core_command
            core_reply = handle_core_command(user_message)
        except Exception:
            core_reply = None
        if core_reply:
            self.memory.add("assistant", core_reply)
            return core_reply

        messages = [{"role": "system", "content": self._system_prompt()}]
        messages += self.memory.recent(limit=20)

        reply = ""
        for _ in range(MAX_STEPS):
            reply = self.llm.complete(messages)
            call = self._extract_tool_call(reply)
            if not call:
                break
            name, args = call.get("tool"), call.get("args", {})
            self.on_tool(f"{name} {args}")
            result = self._run_tool(name, args)
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"[TOOL RESULT] {result}"})
        else:
            reply = reply or "I hit my action limit on that one — can you narrow it down?"

        self.memory.add("assistant", reply)
        return reply

    def close(self) -> None:
        self.memory.close()
        self.brain2.close()
        self.browser.close_browser()

# ---------------------------------------------------------------------------
# Module-level bridge for the GUI, mobile server, and Telegram.
# ---------------------------------------------------------------------------
# The HUD's voice_controller, the mobile HTTP server, and the Telegram bridge
# all import `brain` and call think()/respond()/ask(). One shared Brain is
# reused so memory and resources persist across calls. It auto-approves only
# when REQUIRE_CONFIRMATION is off; destructive skills stay gated otherwise.

_shared_brain = None


def _gui_approver(action: str) -> bool:
    return not settings.require_confirmation


def get_brain() -> "Brain":
    global _shared_brain
    if _shared_brain is None:
        _shared_brain = Brain(approver=_gui_approver)
    return _shared_brain


def think(user_message: str) -> str:
    """Primary entry point external front-ends look for."""
    return get_brain().chat(user_message)


respond = think
ask = think
process_command = think
handle_command = think
