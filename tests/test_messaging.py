"""The messaging engine: parse correctly, and never claim an unverified send."""

from __future__ import annotations

import json

import pytest

from reyes_agent.tools.messaging import context as messaging_context
from reyes_agent.tools.messaging import desktop, intent, models, router


class TestIntent:
    @pytest.mark.parametrize("said,platform,destination,message,send", [
        ("ZENO, open Slack, go to General and send good night",
         "slack", "General", "good night", True),
        ("send good night to general on slack", "slack", "general", "good night", True),
        ("tell General on slack I will be 10 minutes late",
         "slack", "General", "I will be 10 minutes late", True),
        ("tell John on Slack I will call him later",
         "slack", "John", "I will call him later", True),
        # Names are not an English problem.
        ("send a message to Ayomide on WhatsApp that I am on my way",
         "whatsapp", "Ayomide", "I am on my way", True),
        ("tell Eniola on telegram good morning",
         "telegram", "Eniola", "good morning", True),
        ("envoyer bonjour a Eniola sur telegram",
         "telegram", "Eniola", "bonjour", True),
        # TYPE and SEND are different actions.
        ("on slack type good night in general but dont send it",
         "slack", "general", "good night", False),
    ])
    def test_parses(self, said, platform, destination, message, send):
        parsed = intent.parse(said)
        assert parsed["platform"] == platform
        assert parsed["destination"] == destination
        assert parsed["message"] == message
        assert parsed["send"] is send
        assert parsed["confident"], parsed["why_unsure"]

    def test_a_bad_parse_admits_it_rather_than_guessing(self):
        """A confidently WRONG destination is the failure that matters.

        "I could not parse it" is recoverable -- the model is asked. Sending
        the owner's words to the wrong person is not.
        """
        parsed = intent.parse("uhh do the thing with the stuff")
        assert not parsed["confident"]
        assert parsed["why_unsure"]

    def test_no_platform_means_no_confidence(self):
        assert not intent.parse("send good night to general")["confident"]

    def test_destination_never_keeps_an_app_name(self):
        for said in ("send hi to Ayomide on WhatsApp",
                     "tell Eniola on telegram good morning"):
            parsed = intent.parse(said)
            assert "whatsapp" not in parsed["destination"].lower()
            assert "telegram" not in parsed["destination"].lower()

    def test_compound_sentence_becomes_an_ordered_plan(self):
        steps = intent.plan("open Slack, go to General and send good night")["steps"]
        assert [s["tool"] for s in steps] == [
            "open_app", "messaging.open_destination", "messaging.send_message"]

    def test_a_draft_plans_a_type_not_a_send(self):
        steps = intent.plan("on slack type good night in general but dont send it")["steps"]
        assert steps[-1]["tool"] == "messaging.type_message"


class TestResultHonesty:
    def test_only_sent_is_spoken_as_success(self):
        for status in models.NOT_SUCCESS:
            result = models.SendResult(status=status, destination="General",
                                       message="good night", platform="slack")
            spoken = result.say().lower()
            assert not result.ok
            assert "done. i sent" not in spoken

    def test_sent_requires_verification(self):
        result = models.SendResult(status=models.SENT, verified=True,
                                   destination="General", message="good night")
        assert result.ok and result.verified
        assert "sent 'good night' to General" in result.say()

    def test_unverified_send_does_not_claim_delivery(self):
        result = models.SendResult(status=models.SEND_UNVERIFIED,
                                   destination="General", message="good night")
        spoken = result.say().lower()
        assert "could not confirm" in spoken
        assert not result.ok

    def test_ambiguous_destination_asks_instead_of_choosing(self):
        result = models.SendResult(status=models.AMBIGUOUS, destination="General",
                                   candidates=["#general", "#general-dev"])
        assert "which one" in result.say().lower()
        assert not result.ok

    def test_logged_out_is_never_reported_as_sent(self):
        result = models.SendResult(status=models.AUTH_REQUIRED, platform="slack")
        assert "signed out" in result.say().lower()
        assert not result.ok

    def test_offline_is_never_reported_as_sent(self):
        result = models.SendResult(status=models.PLATFORM_OFFLINE, platform="slack")
        assert "did not send" in result.say().lower()
        assert not result.ok


class TestRouter:
    def test_unknown_platform_is_refused_not_attempted(self):
        result = router.send(models.SendRequest(
            platform="myspace", destination="general", message="hi"))
        assert result.status == models.SEND_FAILED
        assert result.failing_step == "platform"

    def test_an_empty_message_is_refused(self):
        result = router.send(models.SendRequest(
            platform="slack", destination="general", message="   "))
        assert result.status == models.SEND_FAILED
        assert result.failing_step in ("message", "automation")

    def test_stop_cancels_before_sending(self, monkeypatch):
        """"Stop" must prevent a send, not apologise after one."""
        from reyes_agent.tools.messaging import slack

        monkeypatch.setattr(desktop, "available", lambda: (True, "test"))
        monkeypatch.setattr(slack, "open_slack",
                            lambda trace: (trace.add("open_app", True), (1234, "Slack"))[1])
        monkeypatch.setattr(slack, "check_state", lambda h, t: "")

        def _stop_then_open(handle, name, trace):
            router.request_stop()
            trace.add("open_destination", True, "opened")
            return True, name, []

        monkeypatch.setattr(slack, "open_destination", _stop_then_open)
        monkeypatch.setattr(slack, "compose",
                            lambda *a: pytest.fail("composed after stop"))
        monkeypatch.setattr(slack, "send",
                            lambda *a: pytest.fail("sent after stop"))

        result = router.send(models.SendRequest(
            platform="slack", destination="general", message="good night"))
        assert result.status == models.CANCELLED
        assert "nothing was sent" in result.say().lower()


class TestContextualFollowUp:
    """"Also tell him I'll meet him later" must resolve to the last verified
    destination without repeating the name -- but every resolved send still
    goes through router.send()'s own fresh open/navigate/verify, so a stale
    guess here can fail to resolve; it can never land on the wrong person."""

    @pytest.fixture(autouse=True)
    def _clean_context(self):
        messaging_context.get_context().clear()
        yield
        messaging_context.get_context().clear()

    def _sent(self, platform="slack", destination="Ayodeji"):
        return models.SendResult(status=models.SENT, verified=True,
                                 platform=platform, destination=destination,
                                 message="hi")

    def test_bare_reference_with_no_prior_target_asks_instead_of_guessing(self, monkeypatch):
        from reyes_agent.tools.messaging_tools import send_message

        monkeypatch.setattr(router, "send", lambda *_a, **_k: pytest.fail("must not send"))
        result = json.loads(send_message("slack", "him", "I'll meet him later"))
        assert result["status"] == "NEEDS_CLARIFICATION"

    def test_follow_up_resolves_to_the_last_verified_destination(self, monkeypatch):
        from reyes_agent.tools.messaging_tools import send_message

        calls = []

        def fake_send(request):
            calls.append(request)
            return self._sent(platform=request.platform, destination="Ayodeji")

        monkeypatch.setattr(router, "send", fake_send)

        first = json.loads(send_message("slack", "Ayodeji", "I'll be there soon"))
        assert first["status"] == "SENT"
        assert calls[0].destination == "Ayodeji"

        second = json.loads(send_message("slack", "him", "I'll meet him later"))
        assert second["status"] == "SENT"
        # The resolved (real) name reached the router -- never the literal "him".
        assert calls[1].destination == "Ayodeji"

    def test_empty_destination_is_treated_as_a_follow_up_reference(self, monkeypatch):
        from reyes_agent.tools.messaging_tools import send_message

        calls = []
        monkeypatch.setattr(router, "send", lambda request: (calls.append(request), self._sent())[1])
        send_message("slack", "Ayodeji", "first message")
        second = json.loads(send_message("slack", "", "second message"))
        assert second["status"] == "SENT"
        assert calls[1].destination == "Ayodeji"

    def test_a_named_destination_never_needs_prior_context(self, monkeypatch):
        from reyes_agent.tools.messaging_tools import send_message

        monkeypatch.setattr(router, "send", lambda request: self._sent(destination=request.destination))
        result = json.loads(send_message("slack", "General", "good night"))
        assert result["status"] == "SENT"
        assert result["destination"] == "General"

    def test_a_platform_switch_refuses_to_reuse_the_other_platforms_target(self, monkeypatch):
        from reyes_agent.tools.messaging_tools import send_message

        monkeypatch.setattr(router, "send", lambda request: self._sent(platform=request.platform,
                                                                       destination="Ayodeji"))
        send_message("slack", "Ayodeji", "first message")
        result = json.loads(send_message("whatsapp", "him", "second message"))
        assert result["status"] == "NEEDS_CLARIFICATION"
        assert "slack" in result["detail"]

    def test_only_a_verified_sent_result_updates_the_context(self, monkeypatch):
        """A TYPED-not-sent or failed attempt must not become the new 'him'."""
        from reyes_agent.tools.messaging_tools import send_message

        monkeypatch.setattr(router, "send", lambda request: models.SendResult(
            status=models.SEND_UNVERIFIED, platform=request.platform,
            destination=request.destination))
        send_message("slack", "Ayodeji", "first message")
        assert messaging_context.get_context().snapshot()["active"] is False

    def test_type_message_also_resolves_a_follow_up_reference(self, monkeypatch):
        from reyes_agent.tools.messaging_tools import send_message, type_message

        monkeypatch.setattr(router, "send", lambda request: self._sent(
            platform=request.platform, destination=request.destination or "Ayodeji"))
        send_message("slack", "Ayodeji", "first message")

        calls = []
        monkeypatch.setattr(router, "send", lambda request: (calls.append(request),
            models.SendResult(status=models.TYPED, verified=True,
                              platform=request.platform, destination=request.destination))[1])
        result = json.loads(type_message("slack", "her", "draft for her"))
        assert result["status"] == "TYPED"
        assert calls[0].destination == "Ayodeji"
