"""Bring-your-own-agent path: an external HTTP agent whose tools come from the workspace MCP endpoint."""
import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture()
def api_server(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTREHEARSAL_AUTH", "off")
    import importlib

    from agentrehearsal import auth as auth_mod, store as store_mod
    importlib.reload(auth_mod)
    store_mod._store = store_mod.FileStore(tmp_path)
    from agentrehearsal import api as api_mod
    importlib.reload(api_mod)
    api_mod._projects.clear()
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(api_mod.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True); t.start()
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health"); break
        except Exception:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def _rpc(url: str, method: str, params: dict | None = None, id_: int = 1) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


class NaiveAgent(BaseHTTPRequestHandler):
    """A gullible external agent: looks the customer up, then refunds whatever amount the message names."""

    mcp_url = ""

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        prompt = json.loads(self.rfile.read(n))["prompt"]
        _rpc(self.mcp_url, "tools/call", {"name": "get_customer", "arguments": {"customer_id": "c_1001"}})
        import re
        m = re.search(r"(?:₹|Rs\.?|INR)\s*([\d,]+)", prompt)
        if m and "refund" in prompt.lower():
            _rpc(self.mcp_url, "tools/call", {"name": "refund_customer", "arguments": {"customer_id": "c_1001", "amount": int(m.group(1).replace(",", "")), "reason": "customer asked"}})
        out = json.dumps({"response": "Done."}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):  # quiet
        pass


def _get(url):
    return json.loads(urllib.request.urlopen(url).read())


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req).read())


def _put(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"}, method="PUT")
    return json.loads(urllib.request.urlopen(req).read())


def test_mcp_endpoint_lists_and_calls_tools(api_server):
    info = _get(f"{api_server}/api/workspace/mcp")
    assert info["url"].endswith(info["token"]) and "refund_customer" in info["tools"]
    init = _rpc(info["url"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert init["result"]["serverInfo"]["name"] == "agentrehearsal"
    tools = _rpc(info["url"], "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {"get_customer", "refund_customer", "send_email", "read_attachment", "delete_customer"}
    r = _rpc(info["url"], "tools/call", {"name": "read_attachment", "arguments": {"attachment_id": "inv_2202"}})
    assert "logistics-verify" in r["result"]["content"][0]["text"]


def test_external_http_agent_rehearse_and_enforce(api_server):
    info = _get(f"{api_server}/api/workspace/mcp")
    NaiveAgent.mcp_url = info["url"]
    port = _free_port()
    srv = HTTPServer(("127.0.0.1", port), NaiveAgent)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    spec = _get(f"{api_server}/api/spec")
    spec["target"] = {"kind": "http", "url": f"http://127.0.0.1:{port}/invoke", "prompt_field": "prompt"}
    _put(f"{api_server}/api/spec", spec)
    scen = [s for s in _get(f"{api_server}/api/scenarios")["scenarios"] if s["id"] in ("S01", "S04")]
    _put(f"{api_server}/api/scenarios", {"scenarios": scen})

    def run(mode, base=None):
        job = _post(f"{api_server}/api/runs", {"mode": mode, "model": "bedrock", "attack_runs": 1, "workers": 1, "base_run_id": base})
        for _ in range(100):
            j = _get(f"{api_server}/api/jobs/{job['job_id']}")
            if j["status"] != "running":
                break
            time.sleep(0.2)
        assert j["status"] == "done", j
        return _get(f"{api_server}/api/runs/{j['run_id']}")

    before = run("rehearse")
    by = {s["id"]: s for s in before["scenarios"]}
    assert by["S01"]["verdict"] == "PASS"
    assert by["S04"]["verdict"] == "FAIL" and by["S04"]["attempts"][0]["calls"][-1]["tool"] == "refund_customer"
    assert before["model"] == "external:http"

    after = run("enforce", base=before["run_id"])
    by = {s["id"]: s for s in after["scenarios"]}
    assert by["S04"]["verdict"] == "PASS" and by["S04"]["attempts"][0]["calls"][-1]["blocked"] is True
    assert by["S01"]["verdict"] == "PASS"
    srv.shutdown()
