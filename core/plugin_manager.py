
from __future__ import annotations
from pathlib import Path
import importlib.util

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins"

def discover() -> list[str]:
    PLUGIN_DIR.mkdir(exist_ok=True)
    return sorted(p.stem for p in PLUGIN_DIR.glob("*.py") if p.name != "__init__.py")

def load_all() -> dict[str, object]:
    loaded={}
    for name in discover():
        path=PLUGIN_DIR/f"{name}.py"
        spec=importlib.util.spec_from_file_location(f"reyes_plugin_{name}", path)
        if not spec or not spec.loader: continue
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        loaded[name]=module
    return loaded
