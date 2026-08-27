"""Hosting a supervisor: conversation, not recital; evidence, not story."""

from __future__ import annotations

import json

import pytest

from reyes_agent.presentation import readiness, timeline, visit


class TestOpening:
    def test_the_opening_asks_one_question_and_stops(self):
        """He has just come off a road. The first thing he gets is a turn."""
        opening = visit.session().start()
        assert opening["then"] == "WAIT_FOR_ANSWER"
        assert opening["say"].count("?") == 1
        assert "Engr Bello" in opening["say"]

    def test_the_opening_does_not_start_selling_the_project(self):
        said = visit.session().start()["say"].lower()
        for premature in ("agent", "python", "architecture", "reyes",
                          "multi-agent", "feature"):
            assert premature not in said

    def test_the_visitor_is_addressed_respectfully(self):
        said = visit.session().start()["say"]
        assert "Engr Bello" in said or "sir" in said.lower()


class TestNothingAdvancesByItself:
    def test_next_topic_is_a_suggestion_not_an_instruction(self):
        session = visit.session()
        session.start()
        suggestion = session.suggest_next()
        assert "suggest" in suggestion
        # Suggesting must not mark anything covered -- that is the difference
        # between offering a topic and delivering it.
        assert not any(t.covered for t in session.topics if t.key == suggestion["suggest"])

    def test_a_topic_is_never_explained_twice(self):
        session = visit.session()
        session.start()
        assert session.repeat_guard("python") == ""
        session.mark("python")
        assert "Already covered" in session.repeat_guard("python")

    def test_long_turns_trigger_a_pause(self):
        """"If ZENO has just spoken for 60-90 seconds: prefer pausing.\""""
        session = visit.session()
        session.start()
        pause, why = session.should_pause(120)
        assert pause and "too long" in why.lower()

        session.spoken_seconds = 95
        pause, why = session.should_pause(10)
        assert pause and "turn" in why.lower()


class TestAdaptsToTheVisitor:
    @pytest.mark.parametrize("said,expected", [
        ("Can you explain the architecture?", "technical"),
        ("How does the implementation handle latency?", "technical"),
        ("Just explain it simply please", "simple"),
        ("It was fine, the road was busy", "normal"),
    ])
    def test_technical_depth_follows_his_questions(self, said, expected):
        session = visit.session()
        session.start()
        assert session.heard(said)["technical_depth"] == expected

    def test_what_he_said_is_remembered(self):
        session = visit.session()
        session.start()
        session.heard("I visited three students yesterday")
        assert any("three students" in s for s in session.visitor_said)


class TestOwnerOutranksVisitor:
    @pytest.mark.parametrize("directive,action", [
        ("ZENO, keep it short", "BRIEF"),
        ("explain technically", "TECHNICAL"),
        ("move on", "MOVE_ON"),
        ("show him", "DEMO_ALLOWED"),
        ("let him ask", "LISTEN"),
        ("end presentation", "END"),
        ("standby", "STANDBY"),
    ])
    def test_directives_are_obeyed_immediately(self, directive, action):
        session = visit.session()
        session.start()
        result = session.owner_says(directive)
        assert result["action"] == action
        assert result["obey"] == "immediately"

    def test_ending_closes_warmly_and_stops(self):
        session = visit.session()
        session.start()
        farewell = session.end()
        assert not session.active
        assert "Engr Bello" in farewell and "journey" in farewell.lower()


class TestTruthfulness:
    def test_the_timeline_separates_proof_from_account(self):
        kinds = {s.evidence_kind for s in timeline.stages()}
        assert timeline.EVIDENCED in kinds
        assert timeline.ATTESTED in kinds

    def test_the_reyes_era_is_never_claimed_as_git_evidenced(self):
        """The repo's first commit is already called ZENO.

        Presenting the rename as something git proves would be the easiest
        lie in this system to tell, and a supervisor could check it.
        """
        rename = timeline.naming()
        assert rename.evidence_kind != timeline.EVIDENCED
        assert "reyes_agent" in rename.evidence

    def test_the_gap_before_version_control_is_stated_not_hidden(self):
        gap = timeline.gap()
        assert gap["unrecorded_before_git"] is True
        assert timeline.SIWES_START in gap["say"]
        assert "no commit history" in gap["say"]

    def test_the_visitor_profile_carries_no_invented_detail(self):
        assert "as supplied by the owner" in visit.VISITOR["field"]
        for forbidden in ("rank", "personal history", "private information"):
            assert forbidden in visit.DO_NOT_INVENT

    def test_the_guest_briefing_excludes_private_material(self):
        blob = json.dumps(visit.briefing()).lower()
        for private in ("password", "api_key", "secret", "token"):
            assert private not in blob


class TestSupervisionExperience:
    def test_visit_profile_persists_the_safe_supervision_boundary(
        self, tmp_path, monkeypatch
    ):
        target = tmp_path / "visit.json"
        monkeypatch.setattr(visit, "profile_path", lambda: target)

        written = visit.write_profile()
        payload = json.loads(written.read_text(encoding="utf-8"))

        assert payload["supervision"]["supervisor"] == "Engr. Bello"
        assert payload["supervision"]["incident_details_known"] is False

    def test_guest_briefing_includes_the_same_safe_supervision_boundary(self):
        supervision = visit.briefing()["supervision"]
        assert supervision["supervisor"] == "Engr. Bello"
        assert supervision["incident_details_known"] is False
        assert "do not invent" in supervision["constraints"].lower()

    def test_the_normal_answer_is_brief_respectful_and_non_accusatory(self):
        result = visit.supervision_response("Who was your SIWES invigilator?")

        assert result["detail_level"] == "brief"
        assert result["hand_over_to_divine"] is False
        assert "Engr. Bello" in result["say"]
        assert "worked out" in result["say"].lower()
        assert len(result["say"].split()) <= 70
        for accusation in ("his fault", "to blame", "failed to", "refused to"):
            assert accusation not in result["say"].lower()

    @pytest.mark.parametrize("question", [
        "What happened?",
        "What were the issues that day?",
        "Tell us the full supervision story.",
    ])
    def test_requests_for_incident_details_are_handed_to_divine(self, question):
        result = visit.supervision_response(question)

        assert result["detail_level"] == "handoff"
        assert result["hand_over_to_divine"] is True
        assert "Divine can explain" in result["say"]
        assert result["known_details"] == []
        assert "do not invent" in result["constraint"].lower()

    @pytest.mark.parametrize("topic", ["placement", "challenges", "supervision"])
    def test_story_comments_are_optional_short_and_student_led(self, topic):
        result = visit.presentation_comment(topic)

        assert result["available"] is True
        assert result["optional"] is True
        assert result["student_leads"] is True
        assert result["read_slide_verbatim"] is False
        assert 0 < len(result["say"].split()) <= 55

    def test_unknown_story_topic_does_not_generate_a_comment(self):
        result = visit.presentation_comment("private incident details")
        assert result["available"] is False
        assert result["say"] == ""

    def test_supervision_is_a_real_visit_topic_with_safe_guidance(self):
        from reyes_agent.tools.visit_tools import visit_topic

        result = json.loads(visit_topic("supervision"))
        assert result["topic"] == "supervision"
        assert "Engr. Bello" in result["substance"]
        assert result["do_not_invent_incident"] is True
        assert result["optional_comment"]["student_leads"] is True

    def test_what_happened_through_the_tool_returns_only_the_handoff(self):
        from reyes_agent.tools.visit_tools import visit_topic

        result = json.loads(visit_topic("supervision", question="What happened?"))
        assert result["supervision"]["detail_level"] == "handoff"
        assert result["supervision"]["hand_over_to_divine"] is True
        assert result["substance"] == result["supervision"]["say"]
        assert "long story" not in result["substance"].lower()

    @pytest.mark.parametrize("question", [
        "Who was your SIWES invigilator?",
        "What happened when Engr. Bello came for supervision?",
    ])
    def test_supervision_questions_route_to_the_safe_topic_tool(self, question):
        from reyes_agent.routing.capability import tools_for

        route = tools_for(question)
        assert "presentation" in route.capabilities
        assert "visit_topic" in route.tools

    def test_agent_loads_the_lazy_visit_tool_for_a_supervision_question(
        self, monkeypatch
    ):
        from reyes_agent import agent
        from reyes_agent.provider import AgentTurn

        captured: list[set[str]] = []

        def fake_turn(_history, *, system, tools, on_text, cancel_check, task_kind):
            captured.append({item["name"] for item in tools})
            on_text("Divine can explain the full situation better if required.")
            return AgentTurn(text="Divine can explain the full situation better if required.")

        monkeypatch.setattr(agent, "run_turn", fake_turn)
        history = [{"role": "user", "content": "What happened with Engr. Bello?"}]
        agent.run_agent(history)

        assert len(captured) == 1
        assert "visit_topic" in captured[0]


class TestReadinessIsMeasured:
    def test_every_check_returns_a_real_verdict(self):
        result = readiness.run()
        assert result["checks"]
        for check in result["checks"]:
            assert check["state"] in (readiness.READY, readiness.PARTIAL,
                                      readiness.FAILED)
            assert check["detail"], f"{check['check']} gave no reason"

    def test_a_broken_probe_reports_failed_rather_than_ready(self, monkeypatch):
        monkeypatch.setattr(readiness, "CHECKS",
                            [("Exploding", lambda: (_ for _ in ()).throw(
                                RuntimeError("boom")))])
        result = readiness.run()
        assert result["state"] == readiness.FAILED
        assert "boom" in result["checks"][0]["detail"]

    def test_the_headline_names_what_is_broken(self, monkeypatch):
        monkeypatch.setattr(readiness, "CHECKS",
                            [("Microphone", lambda: (readiness.FAILED, "unplugged"))])
        assert "Microphone" in readiness.run()["headline"]


class TestRehearsalIsNotAVisit:
    def test_rehearsal_says_he_is_not_present(self):
        from reyes_agent.tools.visit_tools import rehearse_visit

        result = json.loads(rehearse_visit(5))
        assert result["mode"] == "REHEARSAL"
        assert "not here" in result["not_a_visit"]
        assert len(result["questions"]) == 5
