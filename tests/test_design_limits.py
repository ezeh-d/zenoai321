"""The named execution limits, enforced rather than documented.

The ROADMAP listed these as prose: "native Figma, Canva, Photoshop,
Illustrator, printer and vector-editor control is not claimed unless a real
tool is connected". Prose cannot stop a claim. These tests hold the gate that
can.
"""

from __future__ import annotations

import json

import pytest

from reyes_agent.creative import limits


class TestUnconnectedToolsAreRefused:
    """The exact list the ROADMAP named."""

    @pytest.mark.parametrize("capability", [
        "FIGMA", "CANVA", "PHOTOSHOP", "ILLUSTRATOR", "VECTOR_EDITOR", "PRINTER",
    ])
    def test_never_claimed(self, capability):
        allowed, refusal = limits.require(capability)
        assert not allowed
        assert refusal, "a refusal must say something, not be empty"

    @pytest.mark.parametrize("capability", ["FIGMA", "PHOTOSHOP", "PRINTER"])
    def test_the_refusal_names_the_actual_reason(self, capability):
        """"I can't do that" teaches nobody. "There is no connector" does."""
        refusal = limits.check(capability).refusal().lower()
        assert "no connector" in refusal
        assert capability.split("_")[0].lower() in refusal

    def test_an_unknown_capability_is_refused_not_assumed(self):
        capability = limits.check("QUARKXPRESS")
        assert not capability.usable
        assert "do not have that" in capability.detail.lower()


class TestAvailabilityIsMeasuredNotAsserted:
    def test_being_listed_grants_nothing(self):
        """Every name in PROBES must earn its state from a probe."""
        for name in limits.PROBES:
            assert name in limits.capabilities()

    def test_a_broken_probe_fails_closed(self, monkeypatch):
        """A capability must never be granted because a check errored.

        Failing open here would mean an exception in a Blender lookup gets
        read as "Blender is available", which is the worst possible direction
        for the mistake to go.
        """
        monkeypatch.setitem(limits.PROBES, "3D_DESIGN",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        found = limits.capabilities(refresh=True)
        assert found["3D_DESIGN"].state == limits.UNAVAILABLE
        assert not found["3D_DESIGN"].usable

    def test_blender_state_follows_the_real_probe(self, monkeypatch):
        """Installed means AVAILABLE; absent means UNAVAILABLE. Not a string."""
        from reyes_agent.creative.blender import backend

        monkeypatch.setattr(backend, "available", lambda: False)
        assert limits.capabilities(refresh=True)["3D_DESIGN"].state == limits.UNAVAILABLE

        monkeypatch.setattr(backend, "available", lambda: True)
        monkeypatch.setattr(backend, "executable", lambda: r"C:\fake\blender.exe")
        monkeypatch.setattr(backend, "version", lambda: "Blender 5.2.0 LTS")
        found = limits.capabilities(refresh=True)
        assert found["3D_DESIGN"].state == limits.AVAILABLE
        assert "5.2.0" in found["3D_DESIGN"].evidence


class TestCritiqueNeedsRealVision:
    def test_no_vision_provider_means_no_critique(self, monkeypatch):
        """Without a provider ZENO must report the limit, not invent pixels."""
        from reyes_agent import config

        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.setattr(config, key, "", raising=False)
        capability = limits.capabilities(refresh=True)["DESIGN_CRITIQUE"]
        assert capability.state == limits.UNAVAILABLE
        assert "guessing" in capability.detail.lower()

    def test_a_configured_provider_enables_it(self, monkeypatch):
        from reyes_agent import config

        monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-test", raising=False)
        assert limits.capabilities(refresh=True)["DESIGN_CRITIQUE"].state == limits.AVAILABLE


class TestRegisteredIsNotConnected:
    """Magic MCP is the live example: in the registry, unable to start."""

    def test_missing_credential_keeps_it_unavailable(self, monkeypatch):
        monkeypatch.delenv("TWENTY_FIRST_API_KEY", raising=False)
        monkeypatch.setenv("ZENO_MCP_ALLOWLIST", "21st-magic")
        capability = limits.capabilities(refresh=True)["UI_COMPONENTS"]
        assert capability.state == limits.UNAVAILABLE
        assert "TWENTY_FIRST_API_KEY" in capability.detail

    def test_missing_allowlist_keeps_it_unavailable(self, monkeypatch):
        monkeypatch.setenv("TWENTY_FIRST_API_KEY", "key-test")
        monkeypatch.setenv("ZENO_MCP_ALLOWLIST", "")
        capability = limits.capabilities(refresh=True)["UI_COMPONENTS"]
        assert capability.state == limits.UNAVAILABLE
        assert "ZENO_MCP_ALLOWLIST" in capability.detail

    def test_both_gates_satisfied_makes_it_available(self, monkeypatch):
        monkeypatch.setenv("TWENTY_FIRST_API_KEY", "key-test")
        monkeypatch.setenv("ZENO_MCP_ALLOWLIST", "21st-magic")
        assert limits.capabilities(refresh=True)["UI_COMPONENTS"].state == limits.AVAILABLE

    def test_revoking_a_gate_is_noticed_immediately(self, monkeypatch):
        """A gate must not answer from memory after what it guards is gone.

        Caching every capability for two minutes was wrong in exactly one
        direction: a revoked credential kept reading AVAILABLE for the rest of
        the window. Credentials are free to check, so they are never cached.
        """
        monkeypatch.setenv("TWENTY_FIRST_API_KEY", "key-test")
        monkeypatch.setenv("ZENO_MCP_ALLOWLIST", "21st-magic")
        assert limits.check("UI_COMPONENTS").state == limits.AVAILABLE

        monkeypatch.setenv("ZENO_MCP_ALLOWLIST", "")
        # No refresh flag: the next question must already know.
        assert limits.check("UI_COMPONENTS").state == limits.UNAVAILABLE
        assert not limits.require("UI_COMPONENTS")[0]


class TestReportedCapabilitiesComeFromTheProbe:
    def test_design_capabilities_reports_measured_state(self):
        from reyes_agent.tools.design import design_capabilities

        text = design_capabilities()
        assert "MEASURED ON THIS COMPUTER" in text
        for name, capability in limits.capabilities().items():
            assert f"{name}: {capability.state}" in text

    def test_guidance_is_labelled_as_guidance_not_as_software(self):
        """Advice about typography must not read like a connected tool."""
        from reyes_agent.tools.design import design_capabilities

        text = design_capabilities()
        if "DESIGN GUIDANCE" in text:
            guidance = text.split("DESIGN GUIDANCE", 1)[1]
            assert "advice, not connected software" in text
            assert "TYPOGRAPHY" in guidance or "COLOUR_THEORY" in guidance

    def test_the_check_tool_hands_back_a_usable_refusal(self):
        from reyes_agent.tools.design import design_tool_check

        answer = json.loads(design_tool_check("figma"))
        assert answer["allowed"] is False
        assert "no connector" in answer["say_instead"].lower()
        assert isinstance(answer["connected_now"], list)
