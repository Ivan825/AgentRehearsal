"""Accounts, per-user workspaces and run ownership through the HTTP API (file store, auth on)."""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def client(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("AGENTREHEARSAL_AUTH", "on")
    monkeypatch.setenv("AGENTREHEARSAL_JWT_SECRET", "test-secret")
    import importlib

    from agentrehearsal import auth as auth_mod, store as store_mod
    importlib.reload(auth_mod)
    store_mod._store = store_mod.FileStore(tmp)
    from agentrehearsal import api as api_mod
    importlib.reload(api_mod)
    api_mod._projects.clear()
    from fastapi.testclient import TestClient

    return TestClient(api_mod.app)


def _signup(client, email="a@x.io"):
    r = client.post("/api/auth/signup", json={"email": email, "password": "password123", "name": "A"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_requires_login(client):
    assert client.get("/api/spec").status_code == 401


def test_signup_login_and_isolated_workspaces(client):
    h1 = _signup(client, "one@x.io")
    h2 = _signup(client, "two@x.io")
    assert client.post("/api/auth/signup", json={"email": "one@x.io", "password": "password123"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "one@x.io", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "One@X.io", "password": "password123"}).status_code == 200
    spec = client.get("/api/spec", headers=h1).json()
    spec["name"] = "Renamed by one"
    assert client.put("/api/spec", json=spec, headers=h1).status_code == 200
    assert client.get("/api/spec", headers=h1).json()["name"] == "Renamed by one"
    assert client.get("/api/spec", headers=h2).json()["name"] == "SupportBot"


def test_run_is_private_to_owner(client):
    h1 = _signup(client, "one@x.io")
    h2 = _signup(client, "two@x.io")
    job = client.post("/api/runs", json={"mode": "rehearse", "model": "scripted", "attack_runs": 1, "workers": 2}, headers=h1).json()
    import time
    for _ in range(60):
        j = client.get(f"/api/jobs/{job['job_id']}", headers=h1).json()
        if j["status"] != "running":
            break
        time.sleep(0.3)
    assert j["status"] == "done", j
    assert client.get(f"/api/runs/{j['run_id']}", headers=h1).status_code == 200
    assert client.get(f"/api/runs/{j['run_id']}", headers=h2).status_code == 404
    assert client.get(f"/api/jobs/{job['job_id']}", headers=h2).status_code == 404
    mine = [r["run_id"] for r in client.get("/api/runs", headers=h1).json()["runs"] if not r["example"]]
    assert j["run_id"] in mine


def test_contact(client):
    assert client.post("/api/contact", json={"name": "N", "email": "n@x.io", "message": "hello"}).status_code == 200
    assert client.post("/api/contact", json={"name": "N", "email": "bad", "message": ""}).status_code == 400
