"""Contracts for the feature-flag safety valve."""

from __future__ import annotations

import pytest

from reyes_agent.feature_flags import FeatureFlags, register


@pytest.fixture
def ff(tmp_path, monkeypatch):
    # Isolate: no env flags leaking in, a private store per test.
    for k in list(__import__("os").environ):
        if k.startswith("ZENO_FF_"):
            monkeypatch.delenv(k, raising=False)
    return FeatureFlags(store=tmp_path / "flags.json")


def test_registered_default_off(ff):
    assert ff.is_enabled("enable_meilisearch") is False


def test_explicit_default_when_unknown(ff):
    assert ff.is_enabled("totally_unknown_flag") is False
    assert ff.is_enabled("totally_unknown_flag", True) is True


def test_env_overrides_default(ff, monkeypatch):
    monkeypatch.setenv("ZENO_FF_ENABLE_TEMPORAL", "on")
    assert ff.is_enabled("enable_temporal") is True
    monkeypatch.setenv("ZENO_FF_ENABLE_TEMPORAL", "off")
    assert ff.is_enabled("enable_temporal") is False


def test_runtime_override_beats_env(ff, monkeypatch):
    monkeypatch.setenv("ZENO_FF_ENABLE_TEMPORAL", "off")
    ff.enable("enable_temporal")
    assert ff.is_enabled("enable_temporal") is True   # owner intent wins


def test_persistence_across_instances(ff, tmp_path):
    ff.enable("enable_omniparser")
    reloaded = FeatureFlags(store=ff._store)
    assert reloaded.is_enabled("enable_omniparser") is True


def test_disable_and_clear_override(ff, monkeypatch):
    monkeypatch.setenv("ZENO_FF_ENABLE_TEMPORAL", "on")
    ff.disable("enable_temporal")
    assert ff.is_enabled("enable_temporal") is False
    ff.clear_override("enable_temporal")
    assert ff.is_enabled("enable_temporal") is True   # env re-surfaces


def test_rollout_is_deterministic_per_key(ff):
    ff.enable("enable_new_memory", rollout=50)
    a = ff.in_rollout("enable_new_memory", "device-123")
    b = ff.in_rollout("enable_new_memory", "device-123")
    assert a == b  # stable, never flickers


def test_rollout_zero_and_hundred(ff):
    ff.enable("enable_new_memory", rollout=0)
    assert ff.in_rollout("enable_new_memory", "anything") is False
    ff.enable("enable_new_memory", rollout=100)
    assert ff.in_rollout("enable_new_memory", "anything") is True


def test_rollout_disabled_flag_never_in_rollout(ff):
    ff.disable("enable_new_memory")
    assert ff.in_rollout("enable_new_memory", "x") is False


def test_rollout_slice_roughly_matches_percent(ff):
    ff.enable("enable_new_memory", rollout=30)
    hits = sum(ff.in_rollout("enable_new_memory", f"key-{i}") for i in range(1000))
    assert 220 <= hits <= 380  # ~30% with hash noise


def test_register_new_flag(ff):
    register("enable_my_adapter", default=True, description="x")
    assert ff.is_enabled("enable_my_adapter") is True


def test_all_flags_shape(ff):
    ff.enable("enable_meilisearch", rollout=5)
    rows = {r["name"]: r for r in ff.all_flags()}
    row = rows["enable_meilisearch"]
    assert row["enabled"] is True and row["rollout_percent"] == 5
    assert row["overridden"] is True and set(row) >= {
        "name", "enabled", "rollout_percent", "default", "description", "overridden"}


def test_name_normalisation(ff):
    ff.enable("  Enable_Meilisearch ")
    assert ff.is_enabled("enable_meilisearch") is True
