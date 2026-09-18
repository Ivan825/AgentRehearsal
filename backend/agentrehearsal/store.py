"""Optional DynamoDB run history. Active only when AGENTREHEARSAL_DDB_TABLE is set.

Table: partition key run_id (S). One item per run: the summary and metadata inline, the full record as JSON.
"""
from __future__ import annotations

import json
from typing import Any

from . import config


def put_run(record: dict[str, Any]) -> None:
    if not config.DDB_TABLE:
        return
    import boto3

    table = boto3.resource("dynamodb", region_name=config.AWS_REGION).Table(config.DDB_TABLE)
    table.put_item(Item={
        "run_id": record["run_id"],
        "mode": record["mode"],
        "agent": record["agent"],
        "model": record["model"],
        "started_at": record["started_at"],
        "base_run_id": record.get("base_run_id") or "",
        "summary": json.loads(json.dumps(record["summary"]), parse_float=str),
        "record_json": json.dumps(record, default=str),
    })


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    if not config.DDB_TABLE:
        return []
    import boto3

    table = boto3.resource("dynamodb", region_name=config.AWS_REGION).Table(config.DDB_TABLE)
    items = table.scan(Limit=limit).get("Items", [])
    return sorted(items, key=lambda x: x.get("started_at", ""), reverse=True)


def get_run(run_id: str) -> dict[str, Any] | None:
    if not config.DDB_TABLE:
        return None
    import boto3

    table = boto3.resource("dynamodb", region_name=config.AWS_REGION).Table(config.DDB_TABLE)
    item = table.get_item(Key={"run_id": run_id}).get("Item")
    return json.loads(item["record_json"]) if item else None
