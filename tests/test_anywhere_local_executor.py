from __future__ import annotations

import json

import pytest

from reyes_agent.remote_access import device_link, local_executor
from reyes_agent.security.secrets import manager as secrets


def _isolated(monkeypatch, tmp_path):
    link = device_link.DeviceLink(tmp_path / "device-link.db")
    home = tmp_path / "anywhere"
    monkeypatch.setattr(local_executor, "_HOME", home)
    monkeypatch.setattr(local_executor, "_CREDS", home / "executor.json")
    monkeypatch.setattr(device_link, "get_link", lambda: link)
    values: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get", lambda key, default="": values.get(key, default))

    def put(key: str, value: str):
        values[key] = value
        return True, "stored"

    monkeypatch.setattr(secrets, "put", put)
    return link, values


def test_executor_token_uses_os_store_and_metadata_is_not_secret(monkeypatch, tmp_path):
    link, values = _isolated(monkeypatch, tmp_path)

    creds = local_executor.ensure_device()

    assert link.authenticate(creds["device_id"], creds["token"])
    assert values[local_executor._TOKEN_KEY] == creds["token"]  # noqa: SLF001
    metadata = json.loads(local_executor._CREDS.read_text(encoding="utf-8"))  # noqa: SLF001
    assert metadata == {"device_id": creds["device_id"]}
    assert len(link.devices()) == 1


def test_legacy_plaintext_token_is_migrated_once(monkeypatch, tmp_path):
    link, values = _isolated(monkeypatch, tmp_path)
    registered = link.register(
        label="legacy", platform="windows", device_id="dev_legacy_local",
        approved=True,
    )
    local_executor._HOME.mkdir(parents=True)  # noqa: SLF001
    local_executor._CREDS.write_text(json.dumps(registered), encoding="utf-8")  # noqa: SLF001

    loaded = local_executor._load_creds()  # noqa: SLF001

    assert loaded == {"device_id": registered["device_id"], "token": registered["token"]}
    assert values[local_executor._TOKEN_KEY] == registered["token"]  # noqa: SLF001
    assert json.loads(local_executor._CREDS.read_text(encoding="utf-8")) == {  # noqa: SLF001
        "device_id": registered["device_id"],
    }


def test_legacy_plaintext_is_scrubbed_when_keyring_already_has_token(monkeypatch, tmp_path):
    _link, values = _isolated(monkeypatch, tmp_path)
    values[local_executor._TOKEN_KEY] = "secured-token"  # noqa: SLF001
    local_executor._HOME.mkdir(parents=True)  # noqa: SLF001
    local_executor._CREDS.write_text(  # noqa: SLF001
        json.dumps({"device_id": "dev_existing", "token": "stale-plaintext"}),
        encoding="utf-8",
    )

    loaded = local_executor._load_creds()  # noqa: SLF001

    assert loaded == {"device_id": "dev_existing", "token": "secured-token"}
    assert json.loads(local_executor._CREDS.read_text(encoding="utf-8")) == {  # noqa: SLF001
        "device_id": "dev_existing",
    }


def test_invalid_token_rotates_same_device_instead_of_adding_ghost(monkeypatch, tmp_path):
    link, values = _isolated(monkeypatch, tmp_path)
    first = link.register(
        label="local", platform="windows", device_id="dev_stable_local",
        approved=True,
    )
    local_executor._HOME.mkdir(parents=True)  # noqa: SLF001
    local_executor._CREDS.write_text(  # noqa: SLF001
        json.dumps({"device_id": first["device_id"]}), encoding="utf-8",
    )
    values[local_executor._TOKEN_KEY] = "invalid-old-token"  # noqa: SLF001

    rotated = local_executor.ensure_device()

    assert rotated["device_id"] == first["device_id"]
    assert rotated["token"] != "invalid-old-token"
    assert link.authenticate(rotated["device_id"], rotated["token"])
    assert len(link.devices()) == 1


def test_enable_preserves_owner_remote_control_kill_switch(monkeypatch, tmp_path):
    link, _values = _isolated(monkeypatch, tmp_path)
    creds = local_executor.ensure_device()
    link.set_remote_control(False, requesting_device=creds["device_id"])

    info = local_executor.enable()

    assert info["remote_control"] is False
    assert link.remote_control_enabled() is False
    assert local_executor.os.environ["ZENO_DEVICE_ID"] == creds["device_id"]


def test_executor_refuses_plaintext_fallback_when_os_store_is_unavailable(monkeypatch, tmp_path):
    link, _values = _isolated(monkeypatch, tmp_path)
    monkeypatch.setattr(secrets, "put", lambda _key, _value: (False, "no secure store"))

    with pytest.raises(RuntimeError, match="credential store unavailable"):
        local_executor.ensure_device()

    state = link.device_state(local_executor._DEFAULT_DEVICE_ID)  # noqa: SLF001
    assert state["approval_state"] == device_link.REVOKED_DEVICE
    assert not local_executor._CREDS.exists()  # noqa: SLF001
