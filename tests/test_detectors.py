from __future__ import annotations

import json
import unittest

from failure_kata.detectors import (
    detect_context_loss_reasking,
    detect_missing_source_lookup,
    detect_premature_completion,
    detect_repeated_failed_attempts,
    detect_retrying_same_failing_action,
    detect_skipped_verification,
    detect_tests_only_assert_status,
    detect_weak_decomposition,
    run_detectors,
)
from support import event, transcript


class DetectorTests(unittest.TestCase):
    def test_repeated_failed_attempts_links_calls_and_results(self):
        value = transcript(
            event(0, "tool_call", content='{"command":"test one"}', name="execute"),
            event(1, "tool_result", role="tool", content="FAILED one", status="failed"),
            event(2, "message", content="trying another thing"),
            event(3, "tool_call", content='{"command":"test two"}', name="execute"),
            event(4, "tool_result", role="tool", content="FAILED two", status="failed"),
        )
        findings = detect_repeated_failed_attempts(value)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].pattern, "repeated-failed-attempts")
        self.assertEqual([item.event_id for item in findings[0].evidence], ["e0", "e1", "e3", "e4"])

    def test_nonzero_returncode_metadata_counts_as_failure(self):
        value = transcript(
            event(0, "tool_result", role="tool", content="command output", metadata={"returncode": 1}),
            event(1, "tool_result", role="tool", content="command output", metadata={"exit_code": 2}),
        )
        self.assertEqual(len(detect_repeated_failed_attempts(value)), 1)

    def test_successful_verification_breaks_failure_cluster(self):
        value = transcript(
            event(0, "tool_result", role="tool", content="FAILED", status="failed"),
            event(1, "tool_result", role="tool", content="12 passed", status="success", name="unittest"),
            event(2, "tool_result", role="tool", content="FAILED again", status="failed"),
        )
        self.assertEqual(detect_repeated_failed_attempts(value), [])

    def test_skipped_verification(self):
        value = transcript(
            event(0, "message", role="user", content="Fix the file"),
            event(1, "tool_call", content='{"path":"a.py"}', name="edit_file"),
            event(2, "message", content="Done, implemented and ready."),
        )
        finding = detect_skipped_verification(value)[0]
        self.assertEqual(finding.severity, "high")
        self.assertEqual([item.source_line for item in finding.evidence], [2, 3])

    def test_claude_user_role_tool_result_is_not_a_request_boundary(self):
        value = transcript(
            event(0, "message", role="user", content="Fix the file"),
            event(1, "tool_call", content='{"path":"a.py"}', name="edit_file"),
            event(2, "tool_result", role="user", content="file updated", status="success"),
            event(3, "message", content="Done, implemented and ready."),
        )
        self.assertEqual(len(detect_skipped_verification(value)), 1)

    def test_verification_prevents_skipped_verification(self):
        value = transcript(
            event(0, "message", role="user", content="Fix the file"),
            event(1, "tool_call", content='{"path":"a.py"}', name="edit_file"),
            event(2, "tool_call", content='{"command":"python -m unittest"}', name="execute"),
            event(3, "tool_result", role="tool", content="3 passed", status="success"),
            event(4, "message", content="Done, tests passed."),
        )
        self.assertEqual(detect_skipped_verification(value), [])

    def test_negated_or_question_completion_phrase_is_not_a_claim(self):
        negated = transcript(
            event(0, "tool_call", content='{"path":"a.py"}', name="edit_file"),
            event(1, "message", content="This is not done yet."),
        )
        question = transcript(
            event(0, "tool_call", content='{"path":"a.py"}', name="edit_file"),
            event(1, "message", content="Are we done?"),
        )
        self.assertEqual(detect_skipped_verification(negated), [])
        self.assertEqual(detect_skipped_verification(question), [])

    def test_premature_completion_with_user_correction(self):
        value = transcript(
            event(0, "message", content="Done and everything is working."),
            event(1, "message", role="user", content="But it is still failing."),
        )
        finding = detect_premature_completion(value)[0]
        self.assertEqual(finding.confidence, 0.96)
        self.assertEqual(finding.evidence[-1].event_id, "e1")

    def test_premature_completion_with_unresolved_failure(self):
        value = transcript(
            event(0, "tool_result", role="tool", content="ERROR", status="failed"),
            event(1, "message", content="Finished and ready."),
        )
        finding = detect_premature_completion(value)[0]
        self.assertEqual([item.event_id for item in finding.evidence], ["e0", "e1"])

    def test_successful_verification_resolves_prior_failure_for_completion(self):
        value = transcript(
            event(0, "tool_result", role="tool", content="ERROR", status="failed"),
            event(1, "tool_result", role="tool", content="4 passed", status="success", name="pytest"),
            event(2, "message", content="Done and ready."),
        )
        self.assertEqual(detect_premature_completion(value), [])

    def test_weak_decomposition(self):
        request = "Implement the parser, add an adapter, include tests and docs, create a report, update the README, and verify the build."
        value = transcript(
            event(0, "message", role="user", content=request),
            event(1, "tool_call", content='{"path":"parser.py"}', name="write_file"),
        )
        finding = detect_weak_decomposition(value)[0]
        self.assertEqual(finding.pattern, "weak-decomposition")
        self.assertEqual(finding.evidence[1].event_id, "e1")

    def test_visible_plan_prevents_weak_decomposition(self):
        request = "Implement the parser, add an adapter, include tests and docs, create a report, update the README, and verify the build."
        value = transcript(
            event(0, "message", role="user", content=request),
            event(1, "message", content="Plan:\n1. inspect\n2. implement\n3. test"),
            event(2, "tool_call", content="{}", name="read_file"),
        )
        self.assertEqual(detect_weak_decomposition(value), [])

    def test_context_loss_reasking(self):
        value = transcript(
            event(0, "message", content="Which parser file should I update?"),
            event(1, "message", role="user", content="src/parser.py"),
            event(2, "message", content="Which parser file should I update?"),
        )
        finding = detect_context_loss_reasking(value)[0]
        self.assertEqual([item.event_id for item in finding.evidence], ["e0", "e2"])

    def test_distinct_questions_do_not_trigger_context_loss(self):
        value = transcript(
            event(0, "message", content="Which parser file should I update?"),
            event(1, "message", content="What Python version is required?"),
        )
        self.assertEqual(detect_context_loss_reasking(value), [])

    def test_retrying_same_failing_action(self):
        metadata = {"tool_call_id": "call-1"}
        value = transcript(
            event(0, "tool_call", content='{"b":2,"a":1}', name="execute", event_id="call-1"),
            event(1, "tool_result", role="tool", content="FAILED", status="failed", metadata=metadata),
            event(2, "tool_call", content='{"a":1,"b":2}', name="execute", event_id="call-2"),
        )
        finding = detect_retrying_same_failing_action(value)[0]
        self.assertEqual(finding.confidence, 0.98)
        self.assertEqual([item.event_id for item in finding.evidence], ["call-1", "e1", "call-2"])

    def test_changed_action_does_not_trigger_identical_retry(self):
        value = transcript(
            event(0, "tool_call", content='{"command":"test a"}', name="execute"),
            event(1, "tool_result", role="tool", content="FAILED", status="failed"),
            event(2, "tool_call", content='{"command":"test b"}', name="execute"),
        )
        self.assertEqual(detect_retrying_same_failing_action(value), [])

    def test_missing_source_lookup(self):
        value = transcript(
            event(0, "message", role="user", content="Fix the parser.py function"),
            event(1, "tool_call", content='{"path":"parser.py"}', name="edit_file"),
        )
        finding = detect_missing_source_lookup(value)[0]
        self.assertEqual(finding.pattern, "missing-source-lookup")
        self.assertEqual(finding.evidence[0].source_line, 1)

    def test_source_lookup_prevents_missing_lookup(self):
        value = transcript(
            event(0, "message", role="user", content="Fix the parser.py function"),
            event(1, "tool_call", content='{"path":"parser.py"}', name="read_file"),
            event(2, "tool_call", content='{"path":"parser.py"}', name="edit_file"),
        )
        self.assertEqual(detect_missing_source_lookup(value), [])

    def test_tests_only_assert_status(self):
        value = transcript(
            event(
                0,
                "message",
                content="tests/test_api.py\nself.assertEqual(response.status_code, 200)\nself.assertEqual(process.returncode, 0)",
            )
        )
        finding = detect_tests_only_assert_status(value)[0]
        self.assertEqual(finding.pattern, "tests-only-assert-status")
        self.assertIn("2 observed assertion", finding.evidence[0].rationale)

    def test_status_assertions_inside_json_tool_input_are_detected(self):
        tool_input = json.dumps(
            {
                "path": "tests/test_api.py",
                "content": "self.assertEqual(response.status_code, 200)\nself.assertEqual(process.returncode, 0)",
            },
            sort_keys=True,
        )
        value = transcript(event(0, "tool_call", content=tool_input, name="write_file"))
        finding = detect_tests_only_assert_status(value)[0]
        self.assertIn("2 observed assertion", finding.evidence[0].rationale)

    def test_behavior_assertion_inside_json_input_prevents_false_positive(self):
        tool_input = json.dumps(
            {
                "path": "tests/test_api.py",
                "content": "self.assertEqual(response.status_code, 200)\nself.assertEqual(response.json(), {\"ok\": True})",
            },
            sort_keys=True,
        )
        value = transcript(event(0, "tool_call", content=tool_input, name="write_file"))
        self.assertEqual(detect_tests_only_assert_status(value), [])

    def test_behavior_assertion_prevents_status_only_finding(self):
        value = transcript(
            event(
                0,
                "message",
                content="tests/test_api.py\nself.assertEqual(response.status_code, 200)\nself.assertEqual(response.json()[\"name\"], \"Ada\")",
            )
        )
        self.assertEqual(detect_tests_only_assert_status(value), [])

    def test_findings_have_exact_hash_backed_event_references(self):
        source_event = event(0, "message", content="Done")
        correction = event(1, "message", role="user", content="Still broken")
        finding = detect_premature_completion(transcript(source_event, correction))[0]
        evidence = finding.evidence[0]
        self.assertEqual(evidence.event_index, source_event.index)
        self.assertEqual(evidence.source_line, source_event.source_line)
        self.assertEqual(evidence.content_sha256, source_event.content_sha256)

    def test_min_confidence_filters_results(self):
        value = transcript(
            event(0, "message", content="Done"),
            event(1, "message", role="user", content="Still broken"),
        )
        self.assertTrue(run_detectors(value, min_confidence=0.95))
        self.assertEqual(run_detectors(value, min_confidence=0.99), [])


if __name__ == "__main__":
    unittest.main()
