from pathlib import Path

from agentrehearsal.hooks import RecordedCall
from agentrehearsal.scenarios.schema import Scenario
from agentrehearsal.spec import AgentSpec
from agentrehearsal.verdict import combine, judge_attempt

SPEC = AgentSpec.load(Path(__file__).parent.parent / "examples" / "supportbot.spec.json")


def call(tool, args, allowed, blocked=False, violated=None):
    return RecordedCall(1, tool, args, allowed, blocked, violated or [], [], 0.0)


def test_rehearse_denied_call_is_fail():
    s = Scenario(id="x", category="parameter_violation", title="t", prompt="p", expected="deny")
    v = judge_attempt(SPEC, s, [call("refund_customer", {"amount": 50000}, False, violated=["refund-limit"])], "rehearse")
    assert v.verdict == "FAIL" and "refund_customer" in v.reason and v.attempted_denied


def test_enforce_blocked_call_is_pass():
    s = Scenario(id="x", category="parameter_violation", title="t", prompt="p", expected="deny")
    v = judge_attempt(SPEC, s, [call("refund_customer", {"amount": 50000}, False, blocked=True, violated=["refund-limit"])], "enforce")
    assert v.verdict == "PASS" and v.blocked


def test_over_blocking_is_fail():
    s = Scenario(id="x", category="allowed", title="t", prompt="p", expected="allow", must_call="refund_customer")
    v = judge_attempt(SPEC, s, [call("refund_customer", {"amount": 2000}, False, blocked=True, violated=["refund-limit"])], "enforce")
    assert v.verdict == "FAIL" and "too strict" in v.reason


def test_missing_required_call_is_fail():
    s = Scenario(id="x", category="allowed", title="t", prompt="p", expected="allow", must_call="refund_customer")
    v = judge_attempt(SPEC, s, [call("get_customer", {"customer_id": "c_1001"}, True)], "rehearse")
    assert v.verdict == "FAIL"


def test_error_attempt():
    s = Scenario(id="x", category="allowed", title="t", prompt="p", expected="allow")
    assert judge_attempt(SPEC, s, [], "rehearse", error="boom").verdict == "ERROR"


def test_combine():
    assert combine(["PASS", "PASS"]) == "PASS"
    assert combine(["FAIL", "FAIL"]) == "FAIL"
    assert combine(["PASS", "FAIL", "PASS"]) == "INTERMITTENT"
    assert combine(["ERROR"]) == "ERROR"
