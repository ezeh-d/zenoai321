"""Offline regression checks for Creator, Mastery and Foodie integration."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_fast_food_questions_stay_fast_and_multi_step_work_is_deep() -> None:
    from reyes_agent import cognition

    eggs = cognition.route("How long do eggs boil?")
    assert eggs.path == cognition.FAST
    assert cognition.FOODIE in eggs.modes
    plan = cognition.route("Create a seven day meal plan using my ingredients and budget.")
    assert plan.path == cognition.DEEP
    assert cognition.FOODIE in plan.modes
    creator = cognition.route("Zeno, Creator Mode. I want to build a clothing brand.")
    assert creator.path == cognition.DEEP
    assert cognition.CREATOR in creator.modes
    assert cognition.SPECIALIST in creator.modes


def test_creator_and_mastery_use_existing_state_db_without_workers() -> None:
    from reyes_agent import config, creator_mode

    with tempfile.TemporaryDirectory() as raw:
        old = config.VAULT_PATH
        old_publish = creator_mode._publish
        try:
            config.VAULT_PATH = Path(raw) / "vault"
            creator_mode._publish = lambda *_args, **_kwargs: None
            project = creator_mode.start_project("T21 Kits", "Launch a football clothing brand", project_id="kits")
            updated = creator_mode.update_project("kits", stage="POSITIONING", completed_stage="IDEA",
                                                  decision="Supporters first", open_task="Choose a name")
            assert project["project_id"] == "kits"
            assert updated and updated["current_stage"] == "POSITIONING"
            assert updated["decisions"] == ["Supporters first"]
            mastery = creator_mode.update_mastery("logo design", level="FOUNDATION", evidence="Three monochrome sketches",
                                                  weak_area="Type pairing", next_challenge="Refine one mark at 24 px")
            assert mastery["level"] == "FOUNDATION"
            assert creator_mode.mastery_status("logo design")["weak_areas"] == ["Type pairing"]
            source = (Path(__file__).parents[1] / "reyes_agent" / "creator_mode.py").read_text(encoding="utf-8")
            assert "threading.Thread" not in source and "worker_pool" not in source
        finally:
            creator_mode._publish = old_publish
            config.VAULT_PATH = old


def test_foodie_session_is_stepwise_and_scaling_warns_about_seasoning() -> None:
    from reyes_agent import config, foodie_intelligence as foodie

    with tempfile.TemporaryDirectory() as raw:
        old = config.VAULT_PATH
        old_publish = foodie._publish
        try:
            config.VAULT_PATH = Path(raw) / "vault"
            foodie._publish = lambda *_args, **_kwargs: None
            current = foodie.start_session("Jollof rice", ["Wash rice and set aside.", "Blend pepper base."])
            assert current["step_index"] == 0
            next_step = foodie.advance_session()
            assert next_step and next_step["current_step"] == "Blend pepper base."
            scaled = foodie.scale([{"name": "rice", "amount": 2, "unit": "cups"}], 4, 10)
            assert scaled == [{"name": "rice", "amount": 5.0, "unit": "cups"}]
            assert "exactly one safe next step" in foodie.directive("Let's cook it together")
            assert "do not advise tasting" in foodie.directive("My chicken might be raw")
        finally:
            foodie._publish = old_publish
            config.VAULT_PATH = old


def test_registered_tools_and_capabilities_are_real() -> None:
    from reyes_agent import intelligence
    from reyes_agent.tools import TOOLS, tool_definitions

    assert {"creator_project", "mastery_mode", "foodie_mode"} <= set(TOOLS)
    core = {tool["name"] for tool in tool_definitions()}
    assert {"creator_project", "mastery_mode", "foodie_mode"} <= core
    names = {row["capability"] for row in intelligence.capabilities()}
    assert {"creator_mode", "mastery_coaching", "foodie_mode"} <= names


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
