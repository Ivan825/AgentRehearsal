from pathlib import Path

from agentrehearsal.policy.cedar import CedarPolicy, constraints_to_cedar, validate_cedar
from agentrehearsal.spec import AgentSpec

SPEC = AgentSpec.load(Path(__file__).parent.parent / "examples" / "supportbot.spec.json")
SESSION = {"customer_id": "c_1001", "customer_email": "priya.nair@example.com"}


def test_policy_parses():
    assert validate_cedar(constraints_to_cedar(SPEC)) == []


def test_refund_limit_boundary():
    p = CedarPolicy.from_spec(SPEC)
    assert p.evaluate("refund_customer", {"customer_id": "c_1001", "amount": 2000, "reason": "x"}, SESSION).allowed
    assert p.evaluate("refund_customer", {"customer_id": "c_1001", "amount": 5000, "reason": "x"}, SESSION).allowed
    d = p.evaluate("refund_customer", {"customer_id": "c_1001", "amount": 5001, "reason": "x"}, SESSION)
    assert not d.allowed and d.violated == ["refund-limit"]


def test_email_only_verified_customer():
    p = CedarPolicy.from_spec(SPEC)
    assert p.evaluate("send_email", {"to": "priya.nair@example.com", "subject": "s", "body": "b"}, SESSION).allowed
    d = p.evaluate("send_email", {"to": "attacker@example.com", "subject": "s", "body": "b"}, SESSION)
    assert not d.allowed and d.violated == ["email-verified-customer-only"]


def test_delete_forbidden_and_default_deny():
    p = CedarPolicy.from_spec(SPEC)
    assert not p.evaluate("delete_customer", {"customer_id": "c_1001"}, SESSION).allowed
    d = p.evaluate("some_new_tool", {}, SESSION)
    assert not d.allowed and d.violated == ["no-permit:some_new_tool"]


def test_reads_always_allowed():
    p = CedarPolicy.from_spec(SPEC)
    assert p.evaluate("get_customer", {"customer_id": "c_1001"}, SESSION).allowed
    assert p.evaluate("read_attachment", {"attachment_id": "inv_2202"}, SESSION).allowed


def test_path_patterns_and_normalisation():
    from agentrehearsal.policy.cedar import CedarPolicy, constraints_to_cedar, normalise_path
    from agentrehearsal.spec import AgentSpec, Constraint, ToolDef, ToolParam

    spec = AgentSpec(name="FS", purpose="p", system_prompt="s", tools=[
        ToolDef(name="write_file", description="w", params=[ToolParam(name="path"), ToolParam(name="content")]),
        ToolDef(name="read_multiple_files", description="r", params=[ToolParam(name="paths")]),
    ], constraints=[
        Constraint(id="write-root", tool="write_file", kind="param_like", param="path", values=["*/acme-app/docs/triage/*"]),
        Constraint(id="no-secret-content", tool="write_file", kind="param_not_like", param="content", values=["*BEGIN * PRIVATE KEY*", "*://*:*@*"]),
        Constraint(id="read-repo", tool="read_multiple_files", kind="param_like", param="paths", values=["*/acme-app/*"]),
        Constraint(id="no-secrets", tool="read_multiple_files", kind="param_not_like", param="paths", values=["*/.env"]),
    ])
    assert 'like "*/acme-app/docs/triage/*"' in constraints_to_cedar(spec)
    pol = CedarPolicy.from_spec(spec)
    assert normalise_path("/w/acme-app/docs/triage/../triage/x.md") == "/w/acme-app/docs/triage/x.md"
    assert pol.evaluate("write_file", {"path": "/w/acme-app/docs/triage/../triage/x.md", "content": "ok"}, {}).allowed
    assert pol.evaluate("write_file", {"path": "/w/acme-app/docs/triage/../../README.md", "content": "ok"}, {}).violated == ["write-root"]
    # content is matched as written (not path-normalised), so a DB URL is still caught
    assert pol.evaluate("write_file", {"path": "/w/acme-app/docs/triage/x.md", "content": "DB=postgres://u:p@h/db"}, {}).violated == ["no-secret-content"]
    assert pol.evaluate("read_multiple_files", {"paths": ["/w/acme-app/a.py", "/w/acme-app/b.py"]}, {}).allowed
    d = pol.evaluate("read_multiple_files", {"paths": ["/w/acme-app/a.py", "/w/acme-app/../.env"]}, {})
    assert not d.allowed and "no-secrets" in d.violated
