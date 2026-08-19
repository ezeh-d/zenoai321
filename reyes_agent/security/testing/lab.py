"""A real vulnerable lab on localhost, for AVA to exploit end to end.

WHY THIS IS THE REAL THING, NOT A MOCK
--------------------------------------
These are the actual, industry-standard vulnerable applications -- DVWA, OWASP
Juice Shop, WebGoat -- running as real servers in Docker on this machine. AVA
gets real shells, real SQL injection, real privilege escalation against them.
The only thing "safe" about it is that the target is your own laptop, so there
is no one to authorize but you.

Starting a lab auto-authorizes its localhost address in AVA's scope (as a
lab/CTF target), because localhost is definitionally yours. Stopping it leaves
the scope entry to lapse or be revoked normally.

DOCKER IS REQUIRED
------------------
Each lab is a container. If the Docker engine is not running, `start` says so
plainly rather than pretending a server came up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from reyes_agent.security.testing import authorization

# The standard teaching targets. Real, well-known, intentionally vulnerable.
LABS: dict[str, dict[str, Any]] = {
    "dvwa": {
        "image": "vulnerables/web-dvwa",
        "port": 8080, "container_port": 80,
        "summary": "Damn Vulnerable Web Application -- SQLi, XSS, command injection, file upload, the classics.",
        "login": "admin / password, then 'Create / Reset Database'.",
    },
    "juice-shop": {
        "image": "bkimminich/juice-shop",
        "port": 3000, "container_port": 3000,
        "summary": "OWASP Juice Shop -- a modern single-page app covering the whole OWASP Top Ten.",
        "login": "Register an account, or find the admin one through the app's own flaws.",
    },
    "webgoat": {
        "image": "webgoat/webgoat",
        "port": 8081, "container_port": 8080,
        "summary": "OWASP WebGoat -- guided lessons through common web vulnerabilities.",
        "login": "Register a user at /WebGoat.",
    },
}

_NAME_PREFIX = "zeno-ava-lab-"


def _docker() -> str | None:
    """The docker executable, or None if it is not installed."""
    candidates = [
        shutil.which("docker"),
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        "/usr/local/bin/docker", "/usr/bin/docker",
    ]
    return next((c for c in candidates if c and os.path.exists(c)), None) or shutil.which("docker")


def _run(docker: str, args: list[str], timeout: float = 60.0) -> tuple[int, str]:
    try:
        proc = subprocess.run([docker, *args], capture_output=True, text=True,
                              timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "docker command timed out"
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def engine_ready() -> tuple[bool, str]:
    docker = _docker()
    if not docker:
        return False, "Docker is not installed. The lab needs the Docker engine."
    code, out = _run(docker, ["version", "--format", "{{.Server.Version}}"], timeout=15)
    if code != 0:
        return False, "Docker is installed but the engine is not running. Start Docker Desktop."
    return True, f"Docker engine {out} ready."


@dataclass
class LabResult:
    ok: bool
    lab: str
    detail: str
    url: str = ""
    authorized: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "lab": self.lab, "detail": self.detail,
                "url": self.url, "authorized": self.authorized}


def catalog() -> list[dict[str, Any]]:
    return [{"name": name, **{k: v for k, v in spec.items() if k != "container_port"}}
            for name, spec in LABS.items()]


def start(name: str) -> LabResult:
    key = str(name or "").strip().lower()
    spec = LABS.get(key)
    if spec is None:
        return LabResult(False, key, f"Unknown lab. Available: {', '.join(LABS)}")

    ready, why = engine_ready()
    if not ready:
        return LabResult(False, key, why)

    docker = _docker()
    container = _NAME_PREFIX + key
    _run(docker, ["rm", "-f", container])   # clear any previous instance

    port = spec["port"]
    code, out = _run(docker, [
        "run", "-d", "--name", container,
        "-p", f"127.0.0.1:{port}:{spec['container_port']}",
        spec["image"]], timeout=180)
    if code != 0:
        return LabResult(False, key, f"Could not start the container: {out[:200]}")

    url = f"http://localhost:{port}"
    # localhost is the owner's own machine -- authorize the lab target so AVA
    # can work it immediately, with a short TTL matched to a session.
    ok, message = authorization.get_scope().authorize(
        url, "ctf_or_lab", ttl_s=24 * 3600,
        note=f"Local {key} lab (auto-authorized: localhost is yours)")
    authorization.get_scope().authorize(
        "127.0.0.1", "ctf_or_lab", ttl_s=24 * 3600, note=f"Local {key} lab")

    return LabResult(True, key,
                     f"{spec['summary']}\nAccess: {url}\nLogin: {spec['login']}\n"
                     f"AVA is authorized on it: {message.split('.')[0]}.",
                     url=url, authorized=url)


def stop(name: str) -> LabResult:
    key = str(name or "").strip().lower()
    docker = _docker()
    if not docker:
        return LabResult(False, key, "Docker is not installed.")
    code, out = _run(docker, ["rm", "-f", _NAME_PREFIX + key])
    if code != 0:
        return LabResult(False, key, f"Nothing to stop, or: {out[:120]}")
    return LabResult(True, key, f"Stopped the {key} lab. Revoke its scope with security_revoke if you are done.")


def status() -> dict[str, Any]:
    docker = _docker()
    if not docker:
        return {"engine": "not installed", "running": []}
    ready, why = engine_ready()
    if not ready:
        return {"engine": why, "running": []}
    code, out = _run(docker, ["ps", "--filter", f"name={_NAME_PREFIX}",
                              "--format", "{{.Names}} {{.Status}} {{.Ports}}"])
    running = [line for line in out.splitlines() if line.strip()] if code == 0 else []
    return {"engine": "ready", "running": running,
            "available": list(LABS)}
