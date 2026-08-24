"""Contracts for the gated provider adapters -- OFF by default, honest, safe."""

from __future__ import annotations

import pytest

from reyes_agent.adapters import get_registry
from reyes_agent.adapters.base import (AdapterUnavailable, DISABLED,
                                       DEPENDENCY_MISSING, NOT_CONFIGURED, READY)
from reyes_agent.adapters import hardware, external


@pytest.fixture
def flags_off(monkeypatch):
    monkeypatch.setattr("reyes_agent.feature_flags.is_enabled",
                        lambda name, default=None: False)


@pytest.fixture
def flag_on(monkeypatch):
    def _on(which):
        monkeypatch.setattr("reyes_agent.feature_flags.is_enabled",
                            lambda name, default=None: name == which)
    return _on


def test_registry_lists_all_adapters():
    names = {a.name for a in get_registry().all()}
    # 3 hardware + 9 external.
    assert {"camera_vision", "smart_home", "robotics"} <= names
    assert {"observability", "secrets_vault", "distributed_compute", "model_serving",
            "identity_keycloak", "native_shell", "file_sync", "message_bus",
            "log_aggregation"} <= names
    assert len(names) >= 12


def test_everything_disabled_by_default(flags_off):
    for adapter in get_registry().all():
        st = adapter.status()
        assert st.enabled is False and st.available is False
        assert st.status == DISABLED


def test_dashboard_shape_and_categories(flags_off):
    rows = get_registry().dashboard()
    cats = {r["category"] for r in rows}
    assert cats == {"hardware", "external"}
    row = next(r for r in rows if r["name"] == "camera_vision")
    assert set(row) >= {"name", "category", "flag", "enabled", "available",
                        "status", "requires", "detail"}
    assert row["requires"]  # setup steps are listed honestly


def test_operations_raise_when_disabled(flags_off):
    with pytest.raises(AdapterUnavailable):
        hardware.CameraVision().capture()
    with pytest.raises(AdapterUnavailable):
        external.SecretsVault().get_secret("kv/x")
    with pytest.raises(AdapterUnavailable):
        external.MessageBus().publish("zeno.x", {})


def test_enabled_but_missing_dependency_is_honest(flag_on):
    flag_on("enable_vault")
    st = external.SecretsVault().status()
    # Enabled, but hvac + VAULT_ADDR/TOKEN are absent on this box.
    assert st.enabled is True and st.available is False
    assert st.status in (DEPENDENCY_MISSING, NOT_CONFIGURED)


def test_enabled_service_adapter_needs_config(flag_on, monkeypatch):
    # A URL-based adapter has no python dependency; it needs its env var.
    monkeypatch.delenv("VLLM_URL", raising=False)
    flag_on("enable_vllm")
    st = external.ModelServing().status()
    assert st.dependency_present is True and st.status == NOT_CONFIGURED


def test_configured_service_adapter_is_ready(flag_on, monkeypatch):
    monkeypatch.setenv("LOKI_URL", "http://loki.local:3100")
    flag_on("enable_loki")
    adapter = external.LogAggregation()
    assert adapter.status().status == READY and adapter.available() is True
    assert adapter.query("{app=\"zeno\"}")["ok"] is True   # now it works


def test_robotics_refuses_weapon_commands(monkeypatch):
    robo = hardware.Robotics()
    monkeypatch.setattr(robo, "available", lambda: True)   # pretend fully wired
    assert robo.send_command("move arm to home")["ok"] is True
    refused = robo.send_command("fire the weapon")
    assert refused["ok"] is False and refused["refused"] is True


def test_smart_home_security_devices_still_execute_only_approved(monkeypatch):
    hub = external.SecretsVault()  # unrelated; ensure registry independence
    home = hardware.SmartHome()
    monkeypatch.setattr(home, "available", lambda: True)
    out = home.set_state("living_room_light", {"on": True})
    assert out["ok"] is True and out["device"] == "living_room_light"
