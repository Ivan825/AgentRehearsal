"""Persistence: users, projects (an agent spec + its scenarios), run records and contact messages.

Two backends behind one interface:
  FileStore   JSON files under backend/data/ (default; zero setup, used by tests and local dev)
  DynamoStore one DynamoDB table with pk/sk keys, when AGENTREHEARSAL_DDB_TABLE is set

Run records can be large, so they are stored gzip-compressed.
"""
from __future__ import annotations

import base64
import gzip
import json
import threading
import time
from pathlib import Path
from typing import Any

from . import config

_lock = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _pack(obj: Any) -> str:
    return base64.b64encode(gzip.compress(json.dumps(obj, default=str).encode("utf-8"))).decode("ascii")


def _unpack(s: str) -> Any:
    return json.loads(gzip.decompress(base64.b64decode(s)).decode("utf-8"))


class FileStore:
    def __init__(self, root: Path | None = None):
        self.root = root or (Path(__file__).resolve().parent.parent / "data")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str) -> Path:
        return self.root / f"{kind}.json"

    def _read(self, kind: str) -> dict[str, Any]:
        p = self._path(kind)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _write(self, kind: str, data: dict[str, Any]) -> None:
        self._path(kind).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")

    # users
    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self._read("users").get(email.lower())

    def put_user(self, user: dict[str, Any]) -> None:
        with _lock:
            d = self._read("users"); d[user["email"].lower()] = user; self._write("users", d)

    # projects
    def get_project(self, user_id: str) -> dict[str, Any] | None:
        return self._read("projects").get(user_id)

    def put_project(self, user_id: str, project: dict[str, Any]) -> None:
        with _lock:
            d = self._read("projects"); d[user_id] = {**project, "updated_at": _now()}; self._write("projects", d)

    # runs
    def put_run(self, user_id: str, record: dict[str, Any]) -> None:
        with _lock:
            d = self._read("runs")
            d[record["run_id"]] = {"user_id": user_id, "run_id": record["run_id"], "mode": record["mode"], "model": record["model"], "agent": record["agent"],
                                   "started_at": record["started_at"], "base_run_id": record.get("base_run_id"), "summary": record["summary"], "packed": _pack(record)}
            self._write("runs", d)

    def list_runs(self, user_id: str) -> list[dict[str, Any]]:
        rows = [{k: v for k, v in r.items() if k != "packed"} for r in self._read("runs").values() if r["user_id"] == user_id]
        return sorted(rows, key=lambda r: r["started_at"], reverse=True)

    def get_run(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        r = self._read("runs").get(run_id)
        return _unpack(r["packed"]) if r and r["user_id"] == user_id else None

    # contact
    def put_message(self, msg: dict[str, Any]) -> None:
        with _lock:
            d = self._read("messages"); d[str(time.time())] = {**msg, "received_at": _now()}; self._write("messages", d)


class DynamoStore:
    """Single table, keys pk (S) and sk (S). Create it with scripts/create_tables.py."""

    def __init__(self, table_name: str):
        import boto3

        self.table = boto3.resource("dynamodb", region_name=config.AWS_REGION).Table(table_name)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"pk": f"USER#{email.lower()}", "sk": "PROFILE"}).get("Item")
        return item.get("data") if item else None

    def put_user(self, user: dict[str, Any]) -> None:
        self.table.put_item(Item={"pk": f"USER#{user['email'].lower()}", "sk": "PROFILE", "data": user})

    def get_project(self, user_id: str) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"pk": f"ACCOUNT#{user_id}", "sk": "PROJECT#default"}).get("Item")
        return _unpack(item["packed"]) if item else None

    def put_project(self, user_id: str, project: dict[str, Any]) -> None:
        self.table.put_item(Item={"pk": f"ACCOUNT#{user_id}", "sk": "PROJECT#default", "updated_at": _now(), "packed": _pack(project)})

    def put_run(self, user_id: str, record: dict[str, Any]) -> None:
        self.table.put_item(Item={
            "pk": f"ACCOUNT#{user_id}", "sk": f"RUN#{record['run_id']}", "run_id": record["run_id"], "mode": record["mode"], "model": record["model"],
            "agent": record["agent"], "started_at": record["started_at"], "base_run_id": record.get("base_run_id") or "",
            "summary": json.loads(json.dumps(record["summary"]), parse_float=str), "packed": _pack(record),
        })

    def list_runs(self, user_id: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        resp = self.table.query(KeyConditionExpression=Key("pk").eq(f"ACCOUNT#{user_id}") & Key("sk").begins_with("RUN#"),
                                ProjectionExpression="run_id, #m, #mo, #ag, started_at, base_run_id, summary", ExpressionAttributeNames={"#m": "mode", "#mo": "model", "#ag": "agent"})
        rows = resp.get("Items", [])
        for r in rows:
            r["summary"] = json.loads(json.dumps(r["summary"], default=float))
            r["base_run_id"] = r.get("base_run_id") or None
        return sorted(rows, key=lambda r: r["started_at"], reverse=True)

    def get_run(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"pk": f"ACCOUNT#{user_id}", "sk": f"RUN#{run_id}"}).get("Item")
        return _unpack(item["packed"]) if item else None

    def put_message(self, msg: dict[str, Any]) -> None:
        self.table.put_item(Item={"pk": "CONTACT", "sk": f"MSG#{_now()}#{int(time.time()*1000)}", "data": msg})


_store: FileStore | DynamoStore | None = None


def get_store() -> FileStore | DynamoStore:
    global _store
    if _store is None:
        _store = DynamoStore(config.DDB_TABLE) if config.DDB_TABLE else FileStore()
    return _store


def put_run(record: dict[str, Any], user_id: str = "cli") -> None:
    """Used by the CLI and runner: keep the run in the store under the given owner."""
    get_store().put_run(user_id, record)
