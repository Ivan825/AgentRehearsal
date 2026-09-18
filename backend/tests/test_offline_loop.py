"""End-to-end with the scripted (offline) model: rehearse finds failures, replay blocks them."""
from pathlib import Path

from agentrehearsal.models.scripted import ScriptedModel
from agentrehearsal.policy.cedar import CedarPolicy
from agentrehearsal.runner import compare, run_scenarios, scenarios_from_run
from agentrehearsal.scenarios.schema import ScenarioSet, seeds_path
from agentrehearsal.spec import AgentSpec

SPEC = AgentSpec.load(Path(__file__).parent.parent / "examples" / "supportbot.spec.json")


def test_rehearse_then_replay():
    scenarios = ScenarioSet.load(seeds_path()).scenarios
    policy = CedarPolicy.from_spec(SPEC)
    before = run_scenarios(SPEC, scenarios, ScriptedModel(), "rehearse", policy, attack_runs=1, workers=2)
    sm = before["summary"]
    assert sm["legit_pass"] == sm["legit_total"], "legitimate tasks must pass before protection"
    assert sm["attacks_unsafe"] == sm["attacks_total"], "the naive agent should fail every attack"

    after = run_scenarios(SPEC, scenarios_from_run(before), ScriptedModel(), "enforce", policy, attack_runs=1, workers=2)
    am = after["summary"]
    assert am["attacks_unsafe"] == 0
    assert am["attacks_blocked"] == am["attacks_total"]
    assert am["legit_pass"] == am["legit_total"], "protection must not break legitimate work"

    c = compare(before, after)
    assert c["after"]["pass"] == c["after"]["total"]

    # No real side effect for a blocked call: the sandbox must show no deletion after enforcement.
    for s in after["scenarios"]:
        for a in s["attempts"]:
            assert a["side_effects"]["deleted"] == []


def test_indirect_injection_trace_names_the_document():
    scenarios = [s for s in ScenarioSet.load(seeds_path()).scenarios if s.id == "S07"]
    rec = run_scenarios(SPEC, scenarios, ScriptedModel(), "rehearse", attack_runs=1, workers=1)
    attempt = rec["scenarios"][0]["attempts"][0]
    tools = [c["tool"] for c in attempt["calls"]]
    assert tools[:2] == ["get_customer", "read_attachment"]
    assert attempt["calls"][-1]["tool"] == "send_email"
    assert attempt["calls"][-1]["args"]["to"] == "audit@ext-verify-partner.com"
    assert attempt["calls"][-1]["allowed"] is False
