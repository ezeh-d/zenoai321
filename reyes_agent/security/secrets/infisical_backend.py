"""Optional Infisical CLI backend. No CLI/account is created automatically."""
from __future__ import annotations

import os
import shutil
import subprocess


def status() -> dict:
    enabled = os.environ.get("ZENO_INFISICAL_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    cli = shutil.which("infisical")
    project = os.environ.get("INFISICAL_PROJECT_ID", "").strip()
    environment = os.environ.get("INFISICAL_ENVIRONMENT", "").strip()
    token = bool(os.environ.get("INFISICAL_TOKEN", "").strip())
    ready = enabled and bool(cli and project and environment and token)
    if not enabled:
        state = "DISABLED"
    elif not token:
        state = "AUTH_REQUIRED"
    elif not (cli and project and environment):
        state = "NOT_CONFIGURED"
    else:
        state = "STANDBY"
    return {"state": state, "enabled": enabled, "cli_installed": bool(cli),
            "project_configured": bool(project), "environment_configured": bool(environment),
            "authenticated": token, "ready": ready}


def get(name: str, *, token: str) -> str:
    enabled = os.environ.get("ZENO_INFISICAL_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    cli = shutil.which("infisical")
    project = os.environ.get("INFISICAL_PROJECT_ID", "").strip()
    environment = os.environ.get("INFISICAL_ENVIRONMENT", "").strip()
    if not (enabled and cli and project and environment and token):
        return ""
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}}
    env["INFISICAL_TOKEN"] = token
    command = [shutil.which("infisical"), "secrets", "get", str(name), "--plain", "--silent",
               "--projectId", os.environ["INFISICAL_PROJECT_ID"], "--env", os.environ["INFISICAL_ENVIRONMENT"]]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=8, shell=False,
                              env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""
