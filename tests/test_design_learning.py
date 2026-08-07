"""Regression tests for bounded Design Intelligence and Learning Mode."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_simple_design_questions_remain_fast_but_paths_are_deep() -> None:
    from reyes_agent import cognition

    assert cognition.route("Explain kerning like I'm a beginner.").path == cognition.FAST
    lesson = cognition.route("Teach me graphic design from zero.")
    assert lesson.path == cognition.DEEP
    assert cognition.SPECIALIST in lesson.modes
    identity = cognition.route("Create a complete brand identity for my clothing brand.")
    assert identity.path == cognition.DEEP
    assert cognition.SPECIALIST in identity.modes


def test_design_policy_is_original_evidence_based_and_print_aware() -> None:
    from reyes_agent import design_intelligence as design

    logo = design.directive("Make a logo for a sports company")
    assert "never imitate" in logo and "three materially different" in logo
    critique = design.directive("Why does this flyer look amateur?")
    assert "visual evidence" in critique and "request a screenshot" in critique
    printing = design.directive("Prepare this flyer for print with CMYK")
    assert "bleed" in printing and "print-ready" in printing
    assert design.directive("What is kerning?")


def test_learning_progress_is_local_persistent_and_adaptive() -> None:
    from reyes_agent import config, learning_mode

    with tempfile.TemporaryDirectory() as raw:
        prior = config.VAULT_PATH
        prior_publish = learning_mode._publish
        try:
            config.VAULT_PATH = Path(raw) / "vault"
            # Event Bus persistence is covered elsewhere. Keep this unit test
            # focused on the learning database and its short-lived handles.
            learning_mode._publish = lambda *_args, **_kwargs: None
            started = learning_mode.start("graphic design", level="beginner", goal="make better flyers")
            assert started["next_lesson"] == "Design fundamentals"
            progressed = learning_mode.update(
                "graphic design", completed_topic="Design fundamentals",
                struggle="spacing still feels difficult", exercise="one headline/date/CTA poster",
            )
            assert progressed["next_lesson"] == "Typography"
            recovered = learning_mode.status("graphic design")
            assert recovered is not None
            assert recovered["completed"] == ["Design fundamentals"]
            assert recovered["struggle"] == "spacing still feels difficult"
            rendered = learning_mode.format_path(recovered)
            assert "Current exercise" in rendered and "Adapt for" in rendered
        finally:
            learning_mode._publish = prior_publish
            config.VAULT_PATH = prior


def test_learning_mode_can_start_a_generic_skill_without_a_new_agent() -> None:
    from reyes_agent import config, learning_mode

    with tempfile.TemporaryDirectory() as raw:
        prior = config.VAULT_PATH
        prior_publish = learning_mode._publish
        try:
            config.VAULT_PATH = Path(raw) / "vault"
            learning_mode._publish = lambda *_args, **_kwargs: None
            plan = learning_mode.start("public speaking", level="unsure")
            assert learning_mode.curriculum("public speaking")[0] == "Foundations"
            assert plan["next_lesson"] == "Foundations"
            source = (ROOT / "reyes_agent" / "learning_mode.py").read_text(encoding="utf-8")
            assert "threading.Thread" not in source and "worker_pool" not in source
        finally:
            learning_mode._publish = prior_publish
            config.VAULT_PATH = prior


def test_tools_are_registered_lazily_and_zeal_is_upgraded() -> None:
    from reyes_agent import intelligence
    from reyes_agent.tools import TOOLS, tool_definitions
    from reyes_agent.tools import subagents

    assert "learning_mode" in TOOLS
    assert "design_capabilities" in TOOLS
    assert "critique_current_design" in TOOLS
    core = {tool["name"] for tool in tool_definitions()}
    creative = {tool["name"] for tool in tool_definitions(groups={"creative"})}
    assert "learning_mode" in core
    assert "critique_current_design" not in core
    assert "critique_current_design" in creative
    zeal = subagents._SPECIALISTS["zeal"]
    assert {"critique_current_design", "write_project_file", "learning_mode"} <= zeal["tools"]
    assert "original" in zeal["prompt"] and "monochrome" in zeal["prompt"]
    registered = {item["capability"] for item in intelligence.capabilities()}
    assert {"graphic_design", "logo_design", "brand_identity", "typography", "colour_theory", "layout",
            "ui_ux", "image_editing", "vector_design", "creative_direction", "design_education"} <= registered


def test_agent_adds_design_and_learning_to_the_existing_provider_turn() -> None:
    from reyes_agent import agent
    from reyes_agent.provider import AgentTurn

    captured: list[str] = []
    original_run_turn = agent.run_turn
    original_tools = agent.tool_definitions

    def fake_turn(_history, *, system, tools, on_text, cancel_check, task_kind):
        captured.append(system)
        assert task_kind == "reasoning"
        assert tools == []
        on_text("Lesson ready.")
        return AgentTurn(text="Lesson ready.")

    try:
        agent.run_turn = fake_turn
        agent.tool_definitions = lambda **_kwargs: []
        history = [{"role": "user", "content": "Teach me graphic design from zero."}]
        agent.run_agent(history)
    finally:
        agent.run_turn = original_run_turn
        agent.tool_definitions = original_tools

    assert len(captured) == 1
    assert "Learning Mode:" in captured[0]
    assert "Design direction:" in captured[0]
    assert history[-1]["content"] == "Lesson ready."


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
