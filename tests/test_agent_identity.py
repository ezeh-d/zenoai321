"""ZENO must never again fail to recognise a member of his own team."""

from __future__ import annotations

import pytest

from reyes_agent.agents import identity


def test_every_registered_agent_is_answerable():
    """The regression that started this: "I don't know Apex"."""
    team = identity.roster()
    assert len(team) >= 14
    unknown = [a["name"] for a in team if not identity.identity(a["name"])["found"]]
    assert unknown == [], f"ZENO cannot identify his own agents: {unknown}"


def test_every_agent_has_a_real_role_from_configuration():
    assert all(a["role"] for a in identity.roster())


@pytest.mark.parametrize("said,expected", [
    ("Apex", "apex"), ("APEX", "apex"), ("apex", "apex"),
    ("hermes", "hermes_comm"),          # the id differs from the spoken name
    ("HERMES", "hermes_comm"),
    ("the gaming agent", "apex"),
    ("who is stark", "stark"),
    ("security", "stark"),
    ("mission control", "atlas"),
])
def test_aliases_resolve(said, expected):
    assert identity.canonical(said) == expected


def test_divine_is_the_owner_not_an_agent():
    """The hierarchy in agent_teams reads DIVINE -> ZENO -> PRIMARY -> WORKER.

    Inventing a DIVINE specialist would fabricate a role the project never
    defined, so naming Divine must produce a correction, not a lookup.
    """
    answer = identity.identity("Divine")
    assert answer["found"] is False
    assert answer["is_agent"] is False
    assert "owner" in answer["spoken"].lower()
    assert "divine" not in {a["id"] for a in identity.roster()}


def test_unknown_names_are_refused_not_invented():
    answer = identity.identity("Gandalf")
    assert answer["found"] is False
    assert "no agent called" in answer["spoken"]
    # It must still name the real roster rather than shrugging.
    assert "APEX" in answer["spoken"]


def test_identity_never_loads_a_runtime():
    """Metadata is not runtime -- an agent that is asleep is still a member."""
    assert identity.status()["loads_runtime"] is False


def test_role_call_lists_every_main_agent():
    call = identity.role_call()
    assert call["count"] == len(identity.roster())
    for agent in identity.roster():
        assert agent["name"] in call["display"]


def test_workers_are_reported_not_invented():
    apex = identity.workers_of("apex")
    assert apex["found"] and apex["workers"]
    from reyes_agent import agent_teams
    real = {getattr(w, "name", str(w)) for w in agent_teams.teams().get("apex", [])}
    assert {w["name"] for w in apex["workers"]} == real


def test_a_registry_outage_does_not_erase_the_roster(monkeypatch):
    """Unknown health must not become an unknown agent.

    That distinction is the whole bug: "APEX is asleep" is fine, "I don't
    know Apex" is not.
    """
    import reyes_agent.agents.registry as registry

    monkeypatch.setattr(registry, "agents",
                        lambda: (_ for _ in ()).throw(RuntimeError("down")))
    team = identity.roster()
    assert len(team) >= 14
    assert identity.identity("Apex")["found"]
