"""External service connections, workflow-engine routing, dynamic specialists.

The security tests are the important ones: connecting a mailbox to
summarise it must not also authorise sending as the owner, and a temporary
specialist must not become a way to acquire authority.

Run: `.venv/Scripts/python.exe tests/test_integrations_and_specialists.py`
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _isolated_connections():
    from reyes_agent.connectors import connections

    temp = Path(tempfile.mkdtemp(prefix="zeno_conn_"))
    connections._path = lambda: temp / "connections.json"      # noqa: SLF001
    connections.reset_cache()
    return temp


# --- least privilege ----------------------------------------------------

def test_reading_a_mailbox_does_not_authorise_sending() -> None:
    """The failure this exists to prevent."""
    from reyes_agent.connectors import catalog

    gmail = catalog.get("gmail")
    read_scopes = gmail.scopes_up_to(catalog.READ)
    send_scopes = gmail.scopes_up_to(catalog.SEND)

    assert "gmail.send" not in read_scopes, read_scopes
    assert "gmail.send" in send_scopes
    assert set(read_scopes) < set(send_scopes), "tiers must be cumulative"


def test_an_unrecognised_intent_gets_the_least_access() -> None:
    from reyes_agent.connectors import catalog

    assert catalog.minimum_for("do something vague") == catalog.READ
    assert catalog.minimum_for("summarise my inbox") == catalog.READ
    assert catalog.minimum_for("draft a reply") == catalog.WRITE
    assert catalog.minimum_for("send the reply") == catalog.SEND


def test_connecting_asks_only_for_what_the_task_needs() -> None:
    from reyes_agent.connectors import catalog, connections

    _isolated_connections()
    request = connections.begin("gmail", intent="summarise my unread mail")
    assert request["ok"] is True
    assert request["tier"] == catalog.READ
    assert "gmail.send" not in request["scopes"]
    assert request["consequential"] is False
    assert request["state"] == connections.AWAITING_OWNER


def test_zeno_cannot_complete_the_consent_itself() -> None:
    from reyes_agent.connectors import connections

    _isolated_connections()
    request = connections.begin("gmail", intent="read my mail")
    assert "can't click through a consent screen" in request["say"]
    # And nothing is connected merely by asking.
    assert connections.connected("gmail") is False


def test_a_connection_is_not_recorded_without_a_real_credential() -> None:
    from reyes_agent.connectors import connections

    _isolated_connections()
    connections.begin("gmail", intent="read my mail")
    ok, why = connections.confirm("gmail")
    assert ok is False
    assert "will not record a connection I cannot see" in why
    assert connections.connected("gmail") is False


def test_using_more_access_than_was_granted_is_refused() -> None:
    from reyes_agent.connectors import catalog, connections

    _isolated_connections()
    # Simulate a read-only connection having been completed.
    connections._load()["gmail"] = {                    # noqa: SLF001
        "service": "gmail", "state": connections.CONNECTED,
        "tier": catalog.READ, "scopes": ["gmail.readonly"],
        "connected_at": time.time()}

    allowed, why = connections.may("gmail", "summarise my inbox")
    assert allowed is True, why

    allowed, why = connections.may("gmail", "send the reply now")
    assert allowed is False
    assert "connected at 'read' level" in why
    assert "will not quietly use more access" in why


def test_an_unconnected_service_says_so() -> None:
    from reyes_agent.connectors import connections

    _isolated_connections()
    allowed, why = connections.may("slack", "post a message")
    assert allowed is False and "not connected" in why


def test_the_catalogue_knows_what_would_unblock_a_capability() -> None:
    from reyes_agent.connectors import catalog, connections

    _isolated_connections()
    options = catalog.for_capability("email_provider")
    assert {s.key for s in options} >= {"gmail", "outlook", "imap"}

    answer = connections.for_capability("email_provider")
    assert answer["connected"] is False
    assert answer["options"]


def test_no_token_is_ever_stored_in_the_connection_record() -> None:
    from reyes_agent.connectors import connections

    _isolated_connections()
    connections.begin("github", intent="read my repositories")
    record = connections.get("github")
    blob = str(record).lower()
    for forbidden in ("token=", "secret", "ghp_", "bearer "):
        assert forbidden not in blob, record
    assert connections.secret_key("github") == "INTEGRATION_GITHUB_TOKEN"


# --- workflow engine routing --------------------------------------------

def test_a_simple_task_is_not_routed_through_a_workflow_engine() -> None:
    """'Do not replace simple direct tool calls with huge workflows.'"""
    from reyes_agent.connectors import routing

    for simple in ("what time is it", "open chrome", "lock the screen"):
        assert routing.decide(simple).engine == routing.DIRECT, simple


def test_only_an_external_trigger_earns_a_workflow_engine() -> None:
    from reyes_agent.connectors import routing

    route = routing.decide("when a new email arrives, create a CRM lead and notify Slack")
    assert route.engine == routing.WORKFLOW_ENGINE
    assert route.external_trigger is True
    # n8n is not enabled here, so it must say so rather than pretend.
    if not route.available:
        assert route.fallback


def test_multi_day_work_is_a_mission_not_a_workflow() -> None:
    from reyes_agent.connectors import routing

    route = routing.decide("research these companies over the next few days")
    assert route.engine == routing.MISSION
    assert route.external_trigger is False


def test_a_reusable_sequence_is_a_skill() -> None:
    from reyes_agent.connectors import routing

    for reusable in ("open the project then build it then read the errors",
                     "every time I ask, run the health check"):
        assert routing.decide(reusable).engine == routing.SKILL, reusable
    assert routing.decide("anything", steps=5).engine == routing.SKILL


def test_a_short_recurring_task_does_not_need_a_second_runtime() -> None:
    from reyes_agent.connectors import routing

    route = routing.decide("every morning give me a summary")
    assert route.engine == routing.SKILL
    assert "no second runtime" in route.reason


# --- dynamic specialists ------------------------------------------------

def test_a_permanent_agent_is_always_preferred() -> None:
    from reyes_agent.agents import dynamic, registry

    dynamic.reset()
    existing = registry.names()
    if not existing:
        return
    specialist, say = dynamic.create(existing[0], "do something")
    assert specialist is None
    assert "already covers" in say


def test_a_specialist_is_temporary_and_says_so() -> None:
    from reyes_agent.agents import dynamic

    dynamic.reset()
    specialist, say = dynamic.create("shopify automation", "migrate the product feed")
    assert specialist is not None, say
    assert "temporary" in say.lower()
    brief = specialist.brief()
    assert "temporary" in brief.lower()
    assert "no additional authority" in brief.lower()
    assert "not a separate assistant" in brief.lower()


def test_a_specialist_borrows_reach_and_grants_none() -> None:
    from reyes_agent.agents import dynamic
    from reyes_agent.capabilities import registry as capability_registry

    dynamic.reset()
    capability_registry.status()
    specialist, _ = dynamic.create("shopify automation", "migrate the feed")
    usable = set(capability_registry.usable_names())
    assert set(specialist.capabilities) <= usable, (
        "a specialist must not list a capability ZENO cannot already use")
    assert "and no others" in specialist.brief()


def test_specialists_expire() -> None:
    from reyes_agent.agents import dynamic

    dynamic.reset()
    specialist, _ = dynamic.create("brief domain", "quick task", ttl_s=60)
    assert specialist.alive is True
    specialist.created_at -= 10_000            # pretend time passed
    assert specialist.expired is True
    assert dynamic.active() == []


def test_finishing_keeps_what_was_learned_and_drops_the_persona() -> None:
    from reyes_agent.agents import dynamic

    dynamic.reset()
    specialist, _ = dynamic.create("shopify automation", "migrate the feed")
    specialist.note("Shopify bulk operations use GraphQL, not REST",
                    source="https://shopify.dev")
    specialist.note("scratch: tried the wrong endpoint first")

    outcome = dynamic.finish(specialist.specialist_id,
                             retain_note="Shopify bulk ops use GraphQL")
    assert outcome["ok"] is True
    assert outcome["discarded_notes"] == 2, "runtime context must not survive"
    assert any(k.startswith("note:") for k in outcome["retained"])
    assert specialist.notes == []
    assert specialist.state == dynamic.FINISHED


def test_specialists_cannot_be_spawned_in_a_loop() -> None:
    from reyes_agent.agents import dynamic

    dynamic.reset()
    created = 0
    for index in range(dynamic.MAX_ACTIVE + 4):
        specialist, say = dynamic.create(f"unique domain {index}", "task")
        if specialist is None:
            assert "spawning them in a loop" in say
            break
        created += 1
    assert created <= dynamic.MAX_ACTIVE


def test_nothing_raises() -> None:
    from reyes_agent import connectors as integrations
    from reyes_agent.agents import dynamic

    for call in (integrations.status, integrations.catalog.status,
                 integrations.connections.status, integrations.routing.status,
                 dynamic.status):
        assert call() is not None


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
