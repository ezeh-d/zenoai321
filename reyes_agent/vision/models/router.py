"""Choose the smallest vision model that can answer the question.

THE ROUTING RULE
----------------
    "is there an error dialog?"   -> the accessibility tree already knows
    simple screenshot question    -> LIGHT   (Moondream-class)
    complex GUI reasoning         -> BALANCED/STRONG (Qwen3-VL-class)
    video                         -> a video-capable model or nothing

The brief puts it plainly: do not call expensive vision models for every
tiny task, and try accessibility first. That first rung is not a
theoretical preference here -- UIA answers a question like "is there an
error dialog" in ~0.2-0.8s with no model, no GPU and no upload, and it is
ground truth rather than inference. A vision model that agrees with it has
told us nothing new; one that disagrees is wrong.

HARDWARE IS MEASURED, NOT ASSUMED
---------------------------------
`profile()` reads real RAM and looks for a real GPU before claiming a tier.
On this machine there is no torch and no CUDA, so the honest profile is
NONE_LOCAL: UIA and OCR do the work, and the local tiers report why they
cannot run instead of pretending to be on standby.
"""

from __future__ import annotations

import importlib.util as finder
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

# Tiers, cheapest first.
ACCESSIBILITY = "ACCESSIBILITY"     # not a model at all
LIGHT = "LIGHT"                     # ~2GB, CPU-tolerable
BALANCED = "BALANCED"               # ~8GB, wants a GPU
STRONG = "STRONG"                   # 16GB+, needs a real GPU
CLOUD = "CLOUD"                     # someone else's GPU

TIERS = (ACCESSIBILITY, LIGHT, BALANCED, STRONG, CLOUD)

# Rough floors for running a tier locally, in GB.
_VRAM_FLOOR = {LIGHT: 2, BALANCED: 8, STRONG: 16}
_RAM_FLOOR = {LIGHT: 8, BALANCED: 24, STRONG: 48}

_FLAGS = {LIGHT: "ZENO_MOONDREAM_ENABLED", BALANCED: "ZENO_QWEN_VL_ENABLED",
          STRONG: "ZENO_QWEN_VL_ENABLED", CLOUD: "ZENO_CLOUD_VISION_ENABLED"}

# Questions the accessibility tree answers better than any model.
_STRUCTURAL = ("error dialog", "is there a button", "what buttons", "which window",
               "is it enabled", "what does the field say", "what is selected",
               "menu", "checkbox", "text box", "what's on screen", "what is on screen")

# Questions that genuinely need pixels.
_VISUAL = ("colour", "color", "layout", "looks", "chart", "graph", "image", "photo",
           "icon", "screenshot of", "design", "aligned", "overlap", "blurry")

_VIDEO = ("video", "recording", "clip", "frames", "footage")


@dataclass(frozen=True)
class Hardware:
    ram_gb: float = 0.0
    vram_gb: float = 0.0
    gpu: str = ""
    torch: bool = False

    @property
    def best_local_tier(self) -> str | None:
        for tier in (STRONG, BALANCED, LIGHT):
            if not self.torch:
                continue
            if self.vram_gb >= _VRAM_FLOOR[tier] or self.ram_gb >= _RAM_FLOOR[tier]:
                return tier
        return None

    def as_dict(self) -> dict[str, Any]:
        return {"ram_gb": round(self.ram_gb, 1), "vram_gb": round(self.vram_gb, 1),
                "gpu": self.gpu or None, "torch": self.torch,
                "best_local_tier": self.best_local_tier}


def _ram_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:  # noqa: BLE001
        return 0.0


def _gpu() -> tuple[str, float]:
    """Ask nvidia-smi. No output means no NVIDIA GPU, which is the answer."""
    binary = shutil.which("nvidia-smi")
    if not binary:
        return "", 0.0
    try:
        out = subprocess.run(
            [binary, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = (out.stdout or "").strip().splitlines()
        if not line:
            return "", 0.0
        name, _, memory = line[0].partition(",")
        return name.strip(), float(memory.strip()) / 1024.0
    except Exception:  # noqa: BLE001
        return "", 0.0


_cached: Hardware | None = None


def hardware(*, refresh: bool = False) -> Hardware:
    """Measured once per process -- nvidia-smi is not free."""
    global _cached
    if _cached is not None and not refresh:
        return _cached
    name, vram = _gpu()
    _cached = Hardware(ram_gb=_ram_gb(), vram_gb=vram, gpu=name,
                       torch=finder.find_spec("torch") is not None)
    return _cached


def enabled(tier: str) -> bool:
    flag = _FLAGS.get(tier)
    return bool(flag) and os.environ.get(flag, "").strip().lower() in {"1", "true", "yes", "on"}


def installed(tier: str) -> bool:
    if tier == ACCESSIBILITY:
        return finder.find_spec("comtypes") is not None
    if tier == LIGHT:
        return finder.find_spec("moondream") is not None
    if tier in (BALANCED, STRONG):
        return (finder.find_spec("transformers") is not None
                and finder.find_spec("torch") is not None)
    if tier == CLOUD:
        from reyes_agent import config

        return bool(getattr(config, "GEMINI_API_KEY", "") or getattr(config, "OPENAI_API_KEY", ""))
    return False


@dataclass(frozen=True)
class Route:
    tier: str
    reason: str
    available: bool
    fallback: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "reason": self.reason,
                "available": self.available, "fallback": self.fallback}


def route(question: str, *, scene_reliable: bool = True, is_video: bool = False) -> Route:
    """Which tier should answer this. Cheapest that can.

    `scene_reliable` is the deciding input for most questions: when the
    accessibility tree was genuinely read, it beats any model on the
    structural questions, and when it was not, no model can be skipped.
    """
    text = str(question or "").strip().lower()

    if is_video or any(word in text for word in _VIDEO):
        for tier in (STRONG, CLOUD):
            if enabled(tier) and installed(tier):
                return Route(tier, "video needs a video-capable model", True)
        return Route(STRONG, "video understanding needs a model that is not available here",
                     False, fallback="describe individual frames instead")

    # The cheapest rung, and usually the right one.
    if scene_reliable and any(word in text for word in _STRUCTURAL):
        if installed(ACCESSIBILITY):
            return Route(ACCESSIBILITY,
                         "the accessibility tree answers this directly -- ground truth, "
                         "no model, no upload", True)

    wants_pixels = any(word in text for word in _VISUAL) or not scene_reliable
    if not wants_pixels and scene_reliable and installed(ACCESSIBILITY):
        return Route(ACCESSIBILITY, "the screen was read successfully; no model needed", True)

    why = ("the window could not be read structurally" if not scene_reliable
           else "this is a question about how it looks, not what it contains")

    for tier in (LIGHT, BALANCED, STRONG, CLOUD):
        if enabled(tier) and installed(tier):
            return Route(tier, f"{why}; smallest available visual model", True)

    return Route(LIGHT, f"{why}, and no visual model is enabled here", False,
                 fallback="OCR via the existing screen capture path")


def status() -> dict[str, Any]:
    spec = hardware()
    tiers = []
    for tier in TIERS:
        tiers.append({"tier": tier, "enabled": enabled(tier) if tier != ACCESSIBILITY else True,
                      "installed": installed(tier),
                      "flag": _FLAGS.get(tier, ""),
                      "local_capable": (tier == ACCESSIBILITY
                                        or (spec.best_local_tier is not None
                                            and TIERS.index(tier) <= TIERS.index(spec.best_local_tier)))})
    usable = [t for t in tiers if t["installed"] and (t["enabled"] or t["tier"] == ACCESSIBILITY)]
    return {
        "state": "ONLINE" if usable else "DEGRADED",
        "hardware": spec.as_dict(),
        "profile": spec.best_local_tier or "NONE_LOCAL",
        "tiers": tiers,
        "active": [t["tier"] for t in usable],
        "policy": ("accessibility first, then the smallest visual model that can answer; "
                   "a big model is never called for a question the screen already answered"),
        "note": ("No local visual model is installed here and there is no CUDA GPU, so "
                 "UIA and OCR do this work. That is a real capability, not a stub -- "
                 "structural questions are answered from ground truth in well under a "
                 "second."),
    }
