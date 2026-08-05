"""Offline lifecycle regressions for ZENO Peak Core, Part 1."""
from __future__ import annotations

import ast
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent.kernel import STAGE_CORE, ZenoKernel


def test_interface_stage_starts_only_shared_local_runtime() -> None:
    kernel = ZenoKernel()
    try:
        started = time.perf_counter()
        kernel.start_interface()
        elapsed = time.perf_counter() - started
        health = kernel.diagnostics()
        assert health["stage"] == 1
        assert health["workers"]["workers_alive"] >= 1
        assert health["scheduler"]["alive"]
        assert elapsed < 1.0
    finally:
        kernel.shutdown()


def test_core_service_runs_in_background_and_only_once() -> None:
    kernel = ZenoKernel()
    done = threading.Event()
    calls: list[int] = []

    def start() -> None:
        calls.append(threading.get_ident())
        done.set()

    try:
        kernel.register_service("test-core", stage=STAGE_CORE, start=start)
        caller = threading.get_ident()
        kernel.start_core()
        assert done.wait(2)
        kernel.start_core()
        time.sleep(0.05)
        assert len(calls) == 1
        assert calls[0] != caller
        assert kernel.diagnostics()["services"]["test-core"]["state"] == "ready"
    finally:
        kernel.shutdown()


def test_kernel_rejects_new_tasks_after_shutdown() -> None:
    kernel = ZenoKernel()
    kernel.shutdown()
    try:
        kernel.submit(lambda: None)
    except RuntimeError as exc:
        assert "not accepting new tasks" in str(exc)
    else:
        raise AssertionError("Kernel accepted a task during shutdown")


def test_desktop_has_single_instance_guard_before_window_creation() -> None:
    source = (ROOT / "reyes_agent" / "desktop_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    text = ast.get_source_segment(source, main) or ""
    assert "SingleInstanceGuard" in text
    assert "if not instance.acquire():" in text
    assert text.index("instance.acquire()") < text.index("create_window(")


def test_web_lifecycle_delegates_to_kernel_and_has_no_unreachable_shutdown() -> None:
    source = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    startup = ast.get_source_segment(source, functions["_on_startup"]) or ""
    shutdown = ast.get_source_segment(source, functions["_on_shutdown"]) or ""
    prepare = ast.get_source_segment(source, functions["prepare_shutdown"]) or ""
    assert "kernel.start_interface()" in startup
    assert "kernel.start_service(\"core-runtime\"" in startup
    assert "get_kernel().shutdown()" in shutdown
    assert "get_kernel().shutdown(event_flush_timeout=2.0)" in prepare
    assert prepare.rfind("return") > prepare.find("get_kernel().shutdown")


def test_single_instance_guard_has_safe_non_windows_fallback() -> None:
    source = (ROOT / "reyes_agent" / "single_instance.py").read_text(encoding="utf-8")
    assert "CreateMutexW" in source
    assert "os.O_CREAT | os.O_EXCL" in source
    assert "focus_existing()" in source


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
