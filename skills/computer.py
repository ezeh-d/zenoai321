"""Computer control: files, apps, system, screenshots, clipboard.

Destructive actions (delete / move / rename / overwrite / run command) go
through an `approver` callback so REYES asks you before doing them.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Callable


class Computer:
    def __init__(self, approver: Callable[[str], bool], data_dir: str = "./data"):
        self.approver = approver
        self.data_dir = data_dir
        self.os = platform.system()  # 'Windows', 'Darwin', 'Linux'

    # ---------- reading (safe) ----------
    def list_dir(self, path: str = ".") -> str:
        try:
            entries = sorted(os.listdir(os.path.expanduser(path)))
        except Exception as e:  # noqa: BLE001
            return f"Error listing '{path}': {e}"
        if not entries:
            return f"'{path}' is empty."
        lines = []
        for name in entries[:200]:
            full = os.path.join(os.path.expanduser(path), name)
            kind = "dir " if os.path.isdir(full) else "file"
            lines.append(f"[{kind}] {name}")
        return "\n".join(lines)

    def read_file(self, path: str, max_chars: int = 5000) -> str:
        try:
            with open(os.path.expanduser(path), "r", encoding="utf-8", errors="replace") as f:
                data = f.read(max_chars)
            return data if data else "(file is empty)"
        except Exception as e:  # noqa: BLE001
            return f"Error reading '{path}': {e}"

    def search_files(self, query: str, root: str = ".", limit: int = 50) -> str:
        matches: list[str] = []
        root = os.path.expanduser(root)
        q = query.lower()
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if q in name.lower():
                    matches.append(os.path.join(dirpath, name))
                    if len(matches) >= limit:
                        return "\n".join(matches) + f"\n... (stopped at {limit})"
        return "\n".join(matches) if matches else f"No files matching '{query}' under {root}."

    def system_info(self) -> str:
        info = {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpu": platform.processor() or "unknown",
            "cwd": os.getcwd(),
            "home": os.path.expanduser("~"),
        }
        try:
            import psutil  # optional

            info["cpu_percent"] = f"{psutil.cpu_percent()}%"
            info["ram_percent"] = f"{psutil.virtual_memory().percent}%"
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(f"{k}: {v}" for k, v in info.items())

    # ---------- writing (guarded) ----------
    def write_file(self, path: str, content: str) -> str:
        path = os.path.expanduser(path)
        if os.path.exists(path):
            if not self.approver(f"Overwrite existing file: {path}"):
                return "Cancelled by user."
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Wrote {len(content)} chars to {path}."
        except Exception as e:  # noqa: BLE001
            return f"Error writing '{path}': {e}"

    def append_file(self, path: str, content: str) -> str:
        path = os.path.expanduser(path)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended {len(content)} chars to {path}."
        except Exception as e:  # noqa: BLE001
            return f"Error appending to '{path}': {e}"

    def make_dir(self, path: str) -> str:
        try:
            os.makedirs(os.path.expanduser(path), exist_ok=True)
            return f"Created folder {path}."
        except Exception as e:  # noqa: BLE001
            return f"Error creating '{path}': {e}"

    def delete_path(self, path: str) -> str:
        path = os.path.expanduser(path)
        if not self.approver(f"DELETE (permanent): {path}"):
            return "Cancelled by user."
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return f"Deleted {path}."
        except Exception as e:  # noqa: BLE001
            return f"Error deleting '{path}': {e}"

    def move_path(self, src: str, dst: str) -> str:
        src, dst = os.path.expanduser(src), os.path.expanduser(dst)
        if not self.approver(f"Move '{src}' -> '{dst}'"):
            return "Cancelled by user."
        try:
            shutil.move(src, dst)
            return f"Moved to {dst}."
        except Exception as e:  # noqa: BLE001
            return f"Error moving: {e}"

    def rename_path(self, src: str, dst: str) -> str:
        return self.move_path(src, dst)

    # ---------- apps & commands ----------
    def open_app(self, name: str) -> str:
        try:
            if self.os == "Windows":
                subprocess.Popen(f'start "" "{name}"', shell=True)
            elif self.os == "Darwin":
                subprocess.Popen(["open", "-a", name])
            else:
                subprocess.Popen([name])
            return f"Opened {name}."
        except Exception as e:  # noqa: BLE001
            return f"Error opening '{name}': {e}"

    def run_command(self, command: str) -> str:
        if not self.approver(f"Run shell command: {command}"):
            return "Cancelled by user."
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=120
            )
            out = (result.stdout or "") + (result.stderr or "")
            return out.strip()[:5000] or "(no output)"
        except Exception as e:  # noqa: BLE001
            return f"Error running command: {e}"

    # ---------- screen & clipboard ----------
    def screenshot(self, path: str = "") -> str:
        path = path or os.path.join(self.data_dir, "screenshot.png")
        try:
            import mss

            with mss.mss() as sct:
                sct.shot(output=path)
            return f"Screenshot saved to {path}."
        except Exception as e:  # noqa: BLE001
            return f"Screenshot failed ({e}). Install 'mss' (pip install mss)."

    def clipboard_get(self) -> str:
        try:
            import pyperclip

            return pyperclip.paste() or "(clipboard empty)"
        except Exception as e:  # noqa: BLE001
            return f"Clipboard read failed ({e}). Install 'pyperclip'."

    def clipboard_set(self, text: str) -> str:
        try:
            import pyperclip

            pyperclip.copy(text)
            return "Copied to clipboard."
        except Exception as e:  # noqa: BLE001
            return f"Clipboard write failed ({e}). Install 'pyperclip'."
