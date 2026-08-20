"""Install ZENO Anywhere as a self-healing per-user Windows scheduled task."""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
TASK_NAME = "ZENO Anywhere"
BOOTSTRAP = ROOT / "tools" / "zeno_anywhere_bootstrap.py"


def _pythonw() -> Path:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.is_file() else Path(sys.executable)


def _user_id() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    user = os.environ.get("USERNAME", "").strip() or getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def task_xml(*, user_id: str | None = None) -> str:
    """Task definition: logon start, no duplicates, and supervisor recovery."""
    user = escape(user_id or _user_id())
    command = escape(str(_pythonw()))
    # -S skips the environment's very expensive global sitecustomize hook.
    # The bootstrap adds only this project's site-packages, avoiding a
    # multi-minute pythonw stall in the environment's global site hook.
    bootstrap = escape(f'-S "{BOOTSTRAP}"')
    working = escape(str(ROOT))
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Keep ZENO Anywhere available without an IDE or terminal.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled><Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>{command}</Command><Arguments>{bootstrap}</Arguments><WorkingDirectory>{working}</WorkingDirectory></Exec></Actions>
</Task>'''


def _schtasks(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks.exe", *args], capture_output=True, text=True,
        timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def install() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "Task Scheduler installation is available only on Windows."
    if not BOOTSTRAP.is_file():
        return False, f"Bootstrap file is missing: {BOOTSTRAP}"
    xml_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", prefix="zeno-anywhere-",
                encoding="utf-16", delete=False) as handle:
            handle.write(task_xml())
            xml_path = Path(handle.name)
        result = _schtasks("/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F")
        if result.returncode:
            detail = (result.stderr or result.stdout or "Task Scheduler rejected the task").strip()
            return False, detail[:500]
        started = _schtasks("/Run", "/TN", TASK_NAME)
        detail = "installed and start requested" if started.returncode == 0 else "installed; starts at next logon"
        return True, f"ZENO Anywhere startup task {detail}."
    finally:
        if xml_path is not None:
            try:
                xml_path.unlink(missing_ok=True)
            except OSError:
                pass


def start() -> tuple[bool, str]:
    """Start the installed task without detaching it from Task Scheduler."""
    result = _schtasks("/Run", "/TN", TASK_NAME)
    if result.returncode:
        detail = (result.stderr or result.stdout or "Task Scheduler rejected the start")
        return False, detail.strip()[:500]
    return True, "ZENO Anywhere start requested through Task Scheduler."


def uninstall() -> tuple[bool, str]:
    result = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if result.returncode:
        return False, (result.stderr or result.stdout or "task not found").strip()[:500]
    return True, "ZENO Anywhere startup task removed."


def status() -> tuple[bool, str]:
    result = _schtasks("/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V")
    if result.returncode:
        return False, "ZENO Anywhere startup task is not installed."
    return True, result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "status", "uninstall"))
    command = parser.parse_args(argv).command
    ok, message = {"install": install, "status": status,
                   "uninstall": uninstall}[command]()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
