"""`zeno language setup` and `zeno language status`.

WHY SETUP IS A COMMAND AND NOT AN AUTOMATIC DOWNLOAD
----------------------------------------------------
The brief is explicit: do not silently download tens of gigabytes. So nothing
downloads on import, on first use, or on startup. This command tells the owner
what each tier costs in disk and RAM, and installs only what they name.

Every tier reports its ACTUAL measured size, not an estimate, once installed.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

# Sizes are the real on-disk footprint of the CTranslate2 int8 conversions
# Systran publishes. `base` was measured at 148 MB on this machine; the rest
# are the published archive sizes and are marked as such.
TIERS: dict[str, dict[str, Any]] = {
    "essential": {
        "description": "Language detection and Pidgin/slang understanding.",
        "models": (),
        "disk_mb": 0,
        "ram_mb": 30,
        "note": "Already working. Rule-based, offline, no download.",
    },
    "standard": {
        "description": "Multilingual speech recognition in ~100 languages.",
        "models": ("Systran/faster-whisper-base",),
        # 148 MB downloaded, but ~296 MB on disk: the HuggingFace cache keeps
        # a blob and a snapshot, and Windows without developer mode cannot
        # symlink between them, so it copies. Measured on this machine.
        "disk_mb": 296,
        "ram_mb": 500,
        "note": "148 MB download, ~296 MB on disk on Windows. int8 on CPU.",
    },
    "max": {
        "description": "Higher-accuracy speech, better with accents.",
        "models": ("Systran/faster-whisper-small",),
        "disk_mb": 976,
        "ram_mb": 1200,
        "note": "488 MB download; doubled on Windows as above. Not measured here.",
    },
}


def _model_root() -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE)


def _installed(repo: str) -> tuple[bool, int]:
    """Whether a model is on disk, and how many bytes it occupies."""
    folder = _model_root() / ("models--" + repo.replace("/", "--"))
    if not folder.exists():
        return False, 0
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    return True, size


def _free_disk_mb() -> int:
    try:
        return int(shutil.disk_usage(_model_root().anchor).free / 1e6)
    except Exception:  # noqa: BLE001
        return -1


def hardware() -> dict[str, Any]:
    """What this machine can actually run."""
    info: dict[str, Any] = {"gpu": False, "gpu_name": "", "ram_gb": 0.0,
                            "cpu_threads": 0, "free_disk_mb": _free_disk_mb()}
    try:
        import psutil

        info["ram_gb"] = round(psutil.virtual_memory().total / 1e9, 1)
        info["cpu_threads"] = psutil.cpu_count() or 0
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
        info["gpu"] = count > 0
        if count:
            info["gpu_name"] = f"{count} CUDA device(s)"
    except Exception:  # noqa: BLE001
        pass
    return info


def recommend() -> str:
    """The tier this machine should use.

    RAM matters more than disk: a model that loads and then makes the desktop
    swap is worse than a smaller one that does not.
    """
    machine = hardware()
    if machine["ram_gb"] and machine["ram_gb"] < 8:
        return "essential"
    if machine["gpu"] or (machine["ram_gb"] or 0) >= 16:
        return "max"
    return "standard"


def status() -> dict[str, Any]:
    """What is installed, honestly. Never claims a model that is not there."""
    from reyes_agent.language import status as engine_status

    tiers = {}
    for name, tier in TIERS.items():
        models = []
        for repo in tier["models"]:
            present, size = _installed(repo)
            models.append({"model": repo, "installed": present,
                           "size_mb": round(size / 1e6) if present else 0})
        tiers[name] = {
            "description": tier["description"],
            "installed": all(m["installed"] for m in models) if models else True,
            "models": models,
            "disk_mb": tier["disk_mb"],
            "ram_mb": tier["ram_mb"],
            "note": tier["note"],
        }

    engine = engine_status()
    return {
        "engine": engine,
        "hardware": hardware(),
        "recommended_tier": recommend(),
        "tiers": tiers,
        "speech": _speech_status(),
    }


def _speech_status() -> dict[str, Any]:
    from reyes_agent.voice.stt import faster_whisper as local

    detail = local.status()
    return {"state": detail.get("state"), "model": detail.get("model"),
            "installed": detail.get("installed"),
            "configured": bool(detail.get("model")),
            "hint": ("Set ZENO_FASTER_WHISPER_MODEL to a downloaded model "
                     "to enable local multilingual speech.")
                    if not detail.get("model") else ""}


def install(tier: str, *, yes: bool = False) -> dict[str, Any]:
    """Download one tier. Nothing happens without an explicit tier name."""
    tier = (tier or "").strip().lower()
    if tier not in TIERS:
        return {"ok": False, "detail": f"Unknown tier. Choose one of: {sorted(TIERS)}"}

    plan = TIERS[tier]
    if not plan["models"]:
        return {"ok": True, "detail": "Nothing to download; this tier is rule-based."}

    free = _free_disk_mb()
    needed = plan["disk_mb"] * 2      # download plus extraction headroom
    if free >= 0 and free < needed:
        return {"ok": False,
                "detail": f"Not enough disk: {free} MB free, {needed} MB needed."}

    if not yes:
        return {"ok": False, "needs_confirmation": True,
                "detail": (f"Tier '{tier}' downloads {plan['disk_mb']} MB and uses "
                           f"about {plan['ram_mb']} MB of RAM when loaded. "
                           f"Re-run with --yes to proceed.")}

    from huggingface_hub import snapshot_download

    installed = []
    for repo in plan["models"]:
        try:
            path = snapshot_download(repo)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"{repo} failed: {type(exc).__name__}: {exc}",
                    "installed": installed}
        present, size = _installed(repo)
        installed.append({"model": repo, "path": str(path),
                          "size_mb": round(size / 1e6)})

    return {"ok": True, "tier": tier, "installed": installed,
            "next": ("Set ZENO_FASTER_WHISPER_MODEL="
                     f"{plan['models'][0]} to use it.")}


def smoke_test() -> dict[str, Any]:
    """Prove the pipeline works, rather than asserting that it does."""
    from reyes_agent.language import understand_text

    cases = [
        ("Open Chrome", "en"),
        ("Abeg open Chrome", "pcm"),
        ("Make you no delete am", "pcm"),
    ]
    results = []
    for text, expected in cases:
        try:
            understanding = understand_text(text)
            results.append({
                "input": text, "english": understanding.english,
                "language": understanding.language,
                "expected_language": expected,
                "ok": understanding.language == expected,
                "latency_ms": round(understanding.latency_ms, 1),
            })
        except Exception as exc:  # noqa: BLE001
            results.append({"input": text, "ok": False,
                            "error": f"{type(exc).__name__}: {exc}"})
    passed = sum(1 for r in results if r.get("ok"))
    return {"ok": passed == len(cases), "passed": passed, "total": len(cases),
            "results": results}


def main(argv: list[str] | None = None) -> int:
    import json

    args = list(argv if argv is not None else sys.argv[1:])
    command = args[0] if args else "status"

    if command == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if command == "setup":
        tier = args[1] if len(args) > 1 else recommend()
        outcome = install(tier, yes="--yes" in args)
        print(json.dumps(outcome, indent=2))
        if outcome.get("ok"):
            print(json.dumps(smoke_test(), indent=2))
        return 0 if outcome.get("ok") else 1
    if command == "test":
        outcome = smoke_test()
        print(json.dumps(outcome, indent=2))
        return 0 if outcome["ok"] else 1

    print("usage: python -m reyes_agent.language.cli [status|setup [tier] [--yes]|test]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
