"""Vendor the PixiJS browser bundle into the desktop static tree (reproducible).

The desktop ZENO UI (reyes_agent/static/index.html) loads its optional PixiJS
visual layer from ``static/vendor/pixi.min.mjs``. That file is a BUILD ARTIFACT
copied from the declared ``pixi.js`` dependency, so it is gitignored rather than
committed. This script recreates it after ``npm install`` on any machine.

It is safe to run repeatedly: it copies only when the destination is missing or
a different size. If pixi.js is not installed it prints a hint and exits 0 -- the
visual layer is OFF by default and the CSS orb works without it, so a missing
bundle must never fail a setup.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "node_modules" / "pixi.js" / "dist" / "pixi.min.mjs"
_DST = _ROOT / "reyes_agent" / "static" / "vendor" / "pixi.min.mjs"


def vendor_pixi() -> int:
    if not _SRC.exists():
        print("pixi.js not installed (run `npm install`); "
              "the optional Pixi visual layer will stay off, CSS orb unaffected.")
        return 0
    if _DST.exists() and _DST.stat().st_size == _SRC.stat().st_size:
        print(f"pixi already vendored ({_DST.stat().st_size} bytes) -- nothing to do.")
        return 0
    _DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_SRC, _DST)
    print(f"vendored pixi -> {_DST} ({_DST.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(vendor_pixi())
