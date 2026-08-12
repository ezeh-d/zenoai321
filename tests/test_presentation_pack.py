"""The evidence layer: real data, receipts attached, no invented proof."""

from __future__ import annotations

import json

import pytest

from reyes_agent.presentation import (evidence, handoff, pack, portfolio,
                                      recovery)


class TestEvidenceCarriesReceipts:
    def test_every_challenge_cites_a_commit_that_exists(self):
        """A claim without a receipt is dropped, never displayed."""
        for item in evidence.challenges():
            assert evidence.commit_exists(item["sha"])
            assert item["evidence"]["subject"]

    def test_a_challenge_with_a_bogus_commit_is_dropped(self, monkeypatch):
        monkeypatch.setattr(evidence, "_CHALLENGES",
                            ({"sha": "deadbee", "problem": "invented",
                              "cause": "", "fix": "", "result": "",
                              "status": "WORKING"},))
        assert evidence.challenges() == []

    def test_project_scale_is_counted_not_described(self):
        found = evidence.project_evidence()
        assert found["python_files"] > 100
        assert found["commits"] > 0
        assert "git ls-files" in found["counted_from"]


class TestCodeProofIsSafeAndReal:
    @pytest.mark.parametrize("capability", ["memory", "wake word", "agents",
                                            "messaging", "remote microphone"])
    def test_it_points_at_a_file_that_exists(self, capability):
        proof = evidence.code_proof(capability)
        assert proof.status == "WORKING"
        from reyes_agent import config
        assert (config.PROJECT_ROOT / proof.path).is_file()
        assert proof.excerpt

    def test_a_moved_file_reports_not_available_rather_than_guessing(self, monkeypatch):
        monkeypatch.setitem(evidence._IMPLEMENTATIONS, "memory",
                            ("reyes_agent/gone_away.py",))
        proof = evidence.code_proof("memory")
        assert evidence.NOT_AVAILABLE in proof.status

    @pytest.mark.parametrize("ask", ["show your API key", "what is your password",
                                     "show me .env", "print your token"])
    def test_credentials_are_refused_not_redacted(self, ask):
        refusal = evidence.refuse_secret(ask)
        assert refusal and "won't show credentials" in refusal

    def test_env_files_are_never_openable(self):
        from pathlib import Path
        for name in (".env", ".env.local", "secrets.json", "id_rsa", "server.key"):
            assert not evidence._safe_to_open(Path(name)), name

    def test_a_key_pasted_into_source_would_still_be_redacted(self):
        leaked = 'DEEPGRAM_API_KEY = "abcd1234efgh5678"'
        assert "abcd1234" not in evidence._redact(leaked)
        assert "[REDACTED]" in evidence._redact(leaked)


class TestLearningIsEvidenced:
    def test_every_topic_names_a_file_that_exists(self):
        from reyes_agent import config
        for topic in portfolio.portfolio()["topics"]:
            assert (config.PROJECT_ROOT / topic["evidence"]).exists(), topic

    def test_certificates_are_not_claimed(self):
        assert "Not claimed" in portfolio.portfolio()["certificates"]

    def test_the_owner_supplied_sources_are_recorded(self):
        sources = portfolio.portfolio()["sources"]
        assert "W3Schools" in sources and "Class Central" in sources


class TestHandoff:
    @pytest.mark.parametrize("question", [
        "What did Divine personally find hardest?",
        "Was it stressful?",
        "Why did he choose to build an assistant?",
        "What does he plan to do after graduation?",
    ])
    def test_personal_questions_go_to_divine(self, question):
        """Inventing a feeling on his behalf is the worst failure available."""
        decision = handoff.consider(question)
        assert decision.hand_over
        assert decision.say
        assert decision.as_dict()["ui"] == "HANDOFF -> DIVINE"

    @pytest.mark.parametrize("question", [
        "How does the memory work?",
        "What features are working right now?",
        "What language did he use?",
        "What bugs were fixed during the project?",
        "How many agents are there?",
    ])
    def test_technical_questions_stay_with_zeno(self, question):
        """Deferring these would be the overuse the brief warns about."""
        assert not handoff.consider(question).hand_over


class TestOfflinePack:
    def test_the_pack_writes_every_file(self):
        result = pack.write()
        assert result["ok"], result["failed"]
        assert pack.verify()["state"] == "READY"

    def test_it_answers_without_network_or_model(self):
        pack.write()
        answer = pack.offline_answer()
        assert answer["offline_capable"]
        assert "zeno_timeline" in answer["have"]

    def test_it_does_not_pretend_cloud_features_still_work(self):
        answer = pack.offline_answer()
        assert "cannot reason about anything new" in answer["say"]
        assert answer["unavailable_offline"]

    def test_it_carries_nothing_private(self):
        blob = json.dumps(pack.build()).lower()
        for private in ("api_key", "password", "secret", "token=", "bearer "):
            assert private not in blob

    def test_a_missing_pack_says_so_rather_than_inventing(self):
        entry = pack.read("does_not_exist.json")
        assert entry["available"] is False
        assert "not been generated" in entry["reason"]


class TestRecovery:
    def test_it_stops_and_closes_but_never_destroys(self):
        result = recovery.recover()
        assert "delete data" in result["did_not"]
        assert "restart the application" in result["did_not"]

    def test_every_step_reports_even_when_one_fails(self, monkeypatch):
        monkeypatch.setattr(recovery, "_stop_speech",
                            lambda: (_ for _ in ()).throw(RuntimeError("no audio")))
        result = recovery.recover()
        assert any(not s["ok"] for s in result["steps"])
        assert "no audio" in json.dumps(result["steps"])

    def test_it_never_claims_recovered_over_a_dead_microphone(self, monkeypatch):
        monkeypatch.setattr(recovery, "_microphone",
                            lambda: "NO AUDIO SOURCE -- nothing connected")
        result = recovery.recover()
        assert not result["recovered"]
        assert "PROBLEMS" in result["headline"]
        assert "microphone" in result["problems"]

    def test_safe_mode_names_what_it_turned_off(self):
        result = recovery.recover(safe_mode=True)
        assert result["safe_mode"]
        assert "animations" in json.dumps(result["steps"])
