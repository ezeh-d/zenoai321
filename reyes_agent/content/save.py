"""Save intelligence (#18) -- write, then PROVE it, never claim success blind.

ZENO must tell SAVE / SAVE AS / EXPORT / OVERWRITE apart, and after any write it
must verify the result before saying "done":
  1. the file exists,
  2. it reopens,
  3. it is the expected format,
  4. the expected change is present.
Only then is it a success. And it never overwrites the user's only copy without
a restore point first (see versioning.py).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _abs(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".zeno-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def verify_write(path: str | Path, *, expect_contains: str = "",
                 expect_format: str = "") -> dict[str, Any]:
    """The post-write checks. Returns {"ok": bool, "checks": {...}} -- ok is True
    only when every applicable check passed."""
    p = _abs(path)
    checks: dict[str, Any] = {}
    checks["exists"] = p.exists() and p.is_file()
    if not checks["exists"]:
        return {"ok": False, "checks": checks, "error": "file was not written"}
    try:
        raw = p.read_bytes()
        checks["reopens"] = True
    except OSError as exc:
        checks["reopens"] = False
        return {"ok": False, "checks": checks, "error": f"cannot reopen: {exc}"}

    from reyes_agent.content import format_router as fr
    info = fr.detect(p)
    checks["detected_format"] = info.fmt
    checks["format_ok"] = (not expect_format) or info.fmt == expect_format

    if expect_contains:
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            text = ""
        checks["change_present"] = expect_contains in text
    else:
        checks["change_present"] = True

    ok = bool(checks["exists"] and checks["reopens"]
              and checks["format_ok"] and checks["change_present"])
    return {"ok": ok, "checks": checks,
            "error": "" if ok else "post-write verification failed"}


def write_verified(path: str | Path, data: bytes | str, *,
                   expect_contains: str = "", checkpoint: bool = True,
                   note: str = "edit") -> dict[str, Any]:
    """Overwrite a file safely: restore-point first, atomic write, then verify.
    Never reports success unless verification passed; the restore point means a
    failed or wrong edit is always recoverable via versioning.undo()."""
    p = _abs(path)
    payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    result: dict[str, Any] = {"ok": False, "path": str(p)}

    if checkpoint and p.exists():
        from reyes_agent.content.versioning import get_version_manager
        cp = get_version_manager().checkpoint(p, note=f"before {note}")
        result["checkpoint"] = cp.get("version") if cp.get("ok") else None
        if not cp.get("ok"):
            # Refuse to overwrite the only copy if we couldn't protect it.
            return {**result, "error": f"could not create a restore point: "
                    f"{cp.get('error')}; edit refused to protect your file"}

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(p, payload)
    except OSError as exc:
        return {**result, "error": f"write failed: {exc}"}

    verify = verify_write(p, expect_contains=expect_contains)
    result["ok"] = verify["ok"]
    result["verified"] = verify["checks"]
    if not verify["ok"]:
        result["error"] = verify["error"]
        result["recoverable"] = bool(result.get("checkpoint"))
    return result


def classify_save_intent(phrase: str) -> str:
    """SAVE / SAVE_AS / EXPORT / OVERWRITE / CONVERT from a natural phrase (#18)."""
    low = str(phrase or "").casefold()
    if any(w in low for w in ("another copy", "save a copy", "save as", "new copy",
                              "separate copy")):
        return "SAVE_AS"
    if any(w in low for w in ("replace the original", "overwrite")):
        return "OVERWRITE"
    if any(w in low for w in ("turn this into", "make it a", "as pdf", "as a pdf",
                              "export", "convert")):
        return "EXPORT"
    if "save" in low:
        return "SAVE"
    return "SAVE"
