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
