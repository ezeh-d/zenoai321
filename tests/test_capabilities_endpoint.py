"""The phone's capabilities endpoint returns REAL registry data over authed HTTP."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reyes_agent.auth.owner import OwnerAuthService
from reyes_agent.remote_access import cloud_api, device_link, policy
from reyes_agent.remote_access.device_link import DeviceLink


@pytest.fixture
def owner(tmp_path: Path) -> OwnerAuthService:
    service = OwnerAuthService(tmp_path / "owner.sqlite")
    ok, _ = service.provision("owner@example.com", "correct horse battery staple")
    assert ok
    return service


@pytest.fixture
def link(tmp_path: Path) -> DeviceLink:
    return DeviceLink(tmp_path / "devices.sqlite")


def _trusted_client(owner, link, monkeypatch) -> tuple[TestClient, str]:
    policy.reset_rates()
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: owner)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    app = FastAPI()
    cloud_api.register(app)
    client = TestClient(app, base_url="https://testserver")
    body = client.post("/api/owner/auth/login", json={
        "email": "owner@example.com", "password": "correct horse battery staple",
        "nonce": "cap-endpoint-nonce-xxxxxxxx", "device": "Phone",
        "device_id": "browser_cap_endpoint_0001",
    }).json()
    assert owner.approve_browser_device(body["device_id"])   # make it trusted
    return client, body["csrf"]


def test_capabilities_truth_requires_auth(owner, link, monkeypatch):
    policy.reset_rates()
    monkeypatch.setattr(cloud_api, "get_owner_auth", lambda: owner)
    monkeypatch.setattr(cloud_api.device_link, "get_link", lambda: link)
    app = FastAPI(); cloud_api.register(app)
    with TestClient(app, base_url="https://testserver") as client:
        # No session -> refused (this is why the live probe returned 401).
        assert client.get("/api/owner/capabilities/truth").status_code == 401


def test_capabilities_truth_returns_real_registry_data(owner, link, monkeypatch):
    client, _csrf = _trusted_client(owner, link, monkeypatch)
    with client:
        resp = client.get("/api/owner/capabilities/truth")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # Real tool registry -- ZENO has hundreds of tools, not a hard-coded list.
        assert data["inventory"]["tool_count"] > 50
        assert data["system"]["tools"] > 50
        assert data["system"]["areas_connected"] >= 5

        # Connected areas name real capabilities the phone can reach.
        labels = {a["label"] for a in data["inventory"]["connected_areas"]}
        assert "Browser control" in labels or "Desktop control" in labels

        # The no-fake rule: proven-active capabilities are a real, short list.
        assert "open_app" in data["system"]["proven_active"]

        # Per-capability truth dashboard + resource admission are present.
        assert isinstance(data["capabilities"], list) and data["capabilities"]
        assert isinstance(data["resources"], list)
