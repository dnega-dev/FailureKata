"""Generate self-contained, deterministic unittest practice katas."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from .models import Finding, Transcript


class KataGenerationError(ValueError):
    pass


_OBJECTIVES: Mapping[str, str] = {
    "repeated-failed-attempts": "Respond to each failure with a changed, evidence-backed hypothesis instead of accumulating blind attempts.",
    "skipped-verification": "Pair the final change with an explicit verification and cite its outcome before claiming completion.",
    "premature-completion": "Gate completion claims on fresh evidence and explicitly account for unresolved failures.",
    "weak-decomposition": "Turn the request into small, ordered work units with independent verification points.",
    "context-loss-reasking": "Retain supplied facts and consult them before asking a duplicate question.",
    "retrying-same-failing-action": "Do not repeat an identical failed action; record what changed and why the retry is justified.",
    "missing-source-lookup": "Make source inspection the first action before proposing or applying a mutation.",
    "tests-only-assert-status": "Design assertions for behavior and state, not only process or HTTP status.",
}

_HINTS: Mapping[str, Sequence[str]] = {
    "repeated-failed-attempts": (
        "Name the hypothesis invalidated by each failure.",
        "Reduce the next action to the smallest check that distinguishes two explanations.",
        "Reference the failure event that justifies every next action.",
    ),
    "skipped-verification": (
        "Choose a command that would fail if the final behavior were wrong.",
        "Record both the command and the observed evidence.",
        "Make each completion claim point to verification evidence.",
    ),
    "premature-completion": (
        "Keep unresolved failures in a checklist.",
        "A completion claim needs a fresh evidence reference.",
        "Do not treat a mutation result as behavioral verification.",
    ),
    "weak-decomposition": (
        "Each plan item should produce one inspectable outcome.",
        "Put discovery before mutation and verification after it.",
        "Make at least three ordered steps for a multi-part request.",
    ),
    "context-loss-reasking": (
        "Build retained_facts from facts already present in the fixture.",
        "Questions should only request genuinely absent information.",
        "Use event IDs to show where retained facts came from.",
    ),
    "retrying-same-failing-action": (
        "Compare normalized tool name and input, not just prose descriptions.",
        "State the changed assumption in the action hypothesis.",
        "A cosmetic explanation does not make identical input different.",
    ),
    "missing-source-lookup": (
        "The first action kind should be lookup.",
        "Reference a fixture event or target when describing what to inspect.",
        "Only propose mutation after the lookup has an expected observation.",
    ),
    "tests-only-assert-status": (
        "A behavior assertion mentions output, content, state, side effect, or error details.",
        "Keep a status assertion if useful, but add a semantic oracle.",
        "Describe why the assertion would catch an incorrect implementation.",
    ),
}


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result[:80] or "failure-kata"


def _json_dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _scenario(finding: Finding, transcript: Transcript) -> Dict[str, Any]:
    evidence = [item.to_dict() for item in finding.evidence]
    observed_actions = []
    seen_actions = set()
    for item in finding.evidence:
        event = transcript.event_by_id(item.event_id)
        if event is None or event.type not in {"tool_call", "tool_use", "action", "command"}:
            continue
        signature = ((event.name or event.type).lower(), event.content.strip())
        if signature in seen_actions:
            continue
        seen_actions.add(signature)
        observed_actions.append(
            {
                "event_id": event.event_id,
                "kind": event.name or event.type,
                "input": event.content,
            }
        )
    return {
        "finding_id": finding.finding_id,
        "pattern": finding.pattern,
        "objective": _OBJECTIVES[finding.pattern],
        "evidence_event_ids": [item.event_id for item in finding.evidence],
        "evidence": evidence,
        "observed_actions": observed_actions,
        "minimum_plan_steps": 3 if finding.pattern == "weak-decomposition" else 2,
        "contract": {
            "entrypoint": "solution.py:respond(scenario)",
            "return_type": "dict",
            "required_keys": ["plan", "actions", "verification", "claims"],
        },
    }


def _brief(finding: Finding) -> str:
    return "\n".join(
        [
            "# %s" % finding.title,
            "",
            "## Objective",
            "",
            _OBJECTIVES[finding.pattern],
            "",
            "## Observed pattern",
            "",
            finding.summary,
            "",
            "The fixture contains sanitized excerpts and stable event references. Treat the detector result as a hypothesis; inspect the evidence rather than assuming it is correct.",
            "",
            "## Work",
            "",
            "Create `solution.py` and implement `respond(scenario)`. Run:",
            "",
            "```console",
            "python -m unittest discover -s tests -v",
            "```",
            "",
            "Do not edit the fixture or tests to make them pass.",
            "",
        ]
    )


def _contract(finding: Finding) -> str:
    return "\n".join(
        [
            "# Solution contract (no solution included)",
            "",
            "Create `solution.py` next to this file with:",
            "",
            "```python",
            "def respond(scenario: dict) -> dict:",
            "    ...",
            "```",
            "",
            "Return a JSON-serializable mapping with:",
            "",
            "- `plan`: ordered non-empty strings (at least the fixture's `minimum_plan_steps`).",
            "- `actions`: ordered mappings with non-empty `kind`, `input`, `hypothesis`, and `evidence_ref`.",
            "- `verification`: a mapping with non-empty `command` and `evidence`.",
            "- `claims`: a list of mappings with non-empty `claim` and `evidence_ref`.",
            "",
            "`evidence_ref` values must be event IDs in `fixtures/scenario.json`.",
            "The pattern-specific tests document the additional contract for `%s`." % finding.pattern,
            "",
        ]
    )


_TEST_TEMPLATE = '''"""Executable contract for this FailureKata exercise."""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / "fixtures" / "scenario.json").read_text(encoding="utf-8"))


def load_respond():
    path = ROOT / "solution.py"
    if not path.exists():
        raise AssertionError("Create solution.py; see SOLUTION_CONTRACT.md")
    spec = importlib.util.spec_from_file_location("kata_solution", str(path))
    if spec is None or spec.loader is None:
        raise AssertionError("solution.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "respond", None)):
        raise AssertionError("solution.py must define callable respond(scenario)")
    return module.respond


class SolutionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = load_respond()(SCENARIO)

    def test_result_is_json_serializable_mapping(self):
        self.assertIsInstance(self.result, dict)
        json.dumps(self.result, sort_keys=True)

    def test_required_top_level_keys(self):
        self.assertTrue({"plan", "actions", "verification", "claims"}.issubset(self.result))

    def test_plan_is_decomposed(self):
        plan = self.result["plan"]
        self.assertIsInstance(plan, list)
        self.assertGreaterEqual(len(plan), SCENARIO["minimum_plan_steps"])
        self.assertTrue(all(isinstance(item, str) and item.strip() for item in plan))

    def test_actions_are_evidence_linked(self):
        refs = set(SCENARIO["evidence_event_ids"])
        actions = self.result["actions"]
        self.assertIsInstance(actions, list)
        self.assertTrue(actions)
        for action in actions:
            self.assertIsInstance(action, dict)
            self.assertTrue({"kind", "input", "hypothesis", "evidence_ref"}.issubset(action))
            self.assertTrue(str(action["kind"]).strip())
            self.assertTrue(str(action["input"]).strip())
            self.assertTrue(str(action["hypothesis"]).strip())
            self.assertIn(action["evidence_ref"], refs)

    def test_verification_has_command_and_evidence(self):
        verification = self.result["verification"]
        self.assertIsInstance(verification, dict)
        self.assertTrue(str(verification.get("command", "")).strip())
        self.assertTrue(str(verification.get("evidence", "")).strip())

    def test_completion_claims_are_evidence_linked(self):
        refs = set(SCENARIO["evidence_event_ids"])
        claims = self.result["claims"]
        self.assertIsInstance(claims, list)
        for claim in claims:
            self.assertTrue(str(claim.get("claim", "")).strip())
            self.assertIn(claim.get("evidence_ref"), refs)

    def test_pattern_specific_contract(self):
        pattern = SCENARIO["pattern"]
        actions = self.result["actions"]
        if pattern == "missing-source-lookup":
            self.assertEqual(str(actions[0]["kind"]).lower(), "lookup")
        elif pattern == "retrying-same-failing-action":
            signatures = [(str(a["kind"]).strip().lower(), str(a["input"]).strip()) for a in actions]
            prohibited = {
                (str(a["kind"]).strip().lower(), str(a["input"]).strip())
                for a in SCENARIO["observed_actions"]
            }
            self.assertEqual(len(signatures), len(set(signatures)), "do not retry identical actions")
            self.assertTrue(set(signatures).isdisjoint(prohibited), "change the observed failed action")
        elif pattern == "tests-only-assert-status":
            assertions = self.result.get("behavior_assertions", [])
            self.assertTrue(assertions, "include behavior_assertions")
            status_terms = ("status", "status_code", "returncode", "exit code")
            self.assertTrue(any(not any(term in str(item).lower() for term in status_terms) for item in assertions))
        elif pattern == "context-loss-reasking":
            facts = self.result.get("retained_facts", [])
            self.assertTrue(facts, "include retained_facts")
            self.assertTrue(all(str(item).strip() for item in facts))
        elif pattern in {"skipped-verification", "premature-completion"}:
            self.assertTrue(self.result["claims"], "include at least one evidence-gated claim")
        elif pattern == "weak-decomposition":
            self.assertGreaterEqual(len(self.result["plan"]), 3)
        elif pattern == "repeated-failed-attempts":
            hypotheses = [str(item["hypothesis"]).strip().lower() for item in actions]
            self.assertEqual(len(hypotheses), len(set(hypotheses)), "each attempt needs a changed hypothesis")


if __name__ == "__main__":
    unittest.main()
'''


def generate_kata(
    output_root: Path,
    finding: Finding,
    transcript: Transcript,
    force: bool = False,
) -> Path:
    if finding.pattern not in _OBJECTIVES:
        raise KataGenerationError("unsupported pattern: %s" % finding.pattern)
    folder = output_root / ("%s-%s" % (_slug(finding.pattern), finding.finding_id[-8:]))
    if folder.exists() and any(folder.iterdir()) and not force:
        raise KataGenerationError("kata folder already exists and is not empty: %s" % folder)
    fixtures = folder / "fixtures"
    tests = folder / "tests"
    fixtures.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    scenario = _scenario(finding, transcript)
    referenced_events = []
    seen = set()
    for evidence in finding.evidence:
        if evidence.event_id in seen:
            continue
        seen.add(evidence.event_id)
        event = transcript.event_by_id(evidence.event_id)
        if event is not None:
            referenced_events.append(event.to_dict())

    metadata = {
        "schema_version": "1.0",
        "kata_id": folder.name,
        "finding_id": finding.finding_id,
        "pattern": finding.pattern,
        "title": finding.title,
        "created_by": "failure-kata 0.1.0",
        "source": {
            "adapter": transcript.adapter,
            "event_references": [item.event_id for item in finding.evidence],
            "transcript_not_copied": True,
        },
        "review": {"recommended_first_review_days": 1},
    }

    (folder / "README.md").write_text(_brief(finding), encoding="utf-8")
    (folder / "SOLUTION_CONTRACT.md").write_text(_contract(finding), encoding="utf-8")
    (folder / "HINTS.md").write_text(
        "# Hints\n\n" + "\n".join("%d. %s" % (index, hint) for index, hint in enumerate(_HINTS[finding.pattern], 1)) + "\n",
        encoding="utf-8",
    )
    (folder / "metadata.json").write_text(_json_dump(metadata), encoding="utf-8")
    (fixtures / "scenario.json").write_text(_json_dump(scenario), encoding="utf-8")
    (fixtures / "events.json").write_text(_json_dump({"events": referenced_events}), encoding="utf-8")
    (tests / "test_kata.py").write_text(_TEST_TEMPLATE, encoding="utf-8")
    return folder
