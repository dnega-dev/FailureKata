from __future__ import annotations

import json
import unittest

from failure_kata.detectors import detect_premature_completion
from failure_kata.models import Evidence, finding
from failure_kata.pipeline import analyze_file
from failure_kata.reporting import render_json, render_markdown, report_dict
from support import event, temporary_directory, transcript, write_jsonl


class ReportingTests(unittest.TestCase):
    def test_finding_id_is_deterministic(self):
        item = event(0, content="Done")
        evidence = [Evidence.from_event(item, "claim")]
        first = finding("pattern", "Title", "low", 0.5, "summary", "fix", evidence)
        second = finding("pattern", "Title", "low", 0.5, "summary", "fix", evidence)
        self.assertEqual(first.finding_id, second.finding_id)

    def test_finding_id_changes_with_evidence(self):
        first_evidence = [Evidence.from_event(event(0, content="Done"), "claim")]
        second_evidence = [Evidence.from_event(event(0, content="Finished"), "claim")]
        first = finding("pattern", "Title", "low", 0.5, "summary", "fix", first_evidence)
        second = finding("pattern", "Title", "low", 0.5, "summary", "fix", second_evidence)
        self.assertNotEqual(first.finding_id, second.finding_id)

    def test_evidence_excerpt_is_bounded_but_hash_is_full_content(self):
        item = event(0, content="x" * 400)
        evidence = Evidence.from_event(item, "long", max_excerpt=20)
        self.assertEqual(len(evidence.excerpt), 20)
        self.assertTrue(evidence.excerpt.endswith("…"))
        self.assertEqual(evidence.content_sha256, item.content_sha256)

    def test_json_report_round_trip(self):
        value = transcript(event(0, content="Done"), event(1, role="user", content="Still broken"))
        findings = detect_premature_completion(value)
        report = report_dict(value, findings, redaction_count=2, input_sha256="abc")
        decoded = json.loads(render_json(report))
        self.assertEqual(decoded["schema_version"], "1.0")
        self.assertEqual(decoded["summary"]["finding_count"], 1)
        self.assertEqual(decoded["input"]["redaction_count"], 2)

    def test_markdown_report_contains_exact_reference(self):
        value = transcript(event(0, content="Done"), event(1, role="user", content="Still broken"))
        findings = detect_premature_completion(value)
        report = report_dict(value, findings, redaction_count=0, input_sha256="abc")
        rendered = render_markdown(report)
        self.assertIn("source line 1", rendered)
        self.assertIn("`e0`", rendered)
        self.assertIn(value.events[0].content_sha256, rendered)

    def test_markdown_empty_report_explains_limits(self):
        value = transcript(event(0, role="user", content="Hello"))
        report = report_dict(value, [], redaction_count=0, input_sha256="abc")
        self.assertIn("does not prove", render_markdown(report))

    def test_pipeline_scrubs_report_evidence(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"id": "m1", "role": "assistant", "content": "Done with password=synthetic-password"},
                {"id": "m2", "role": "user", "content": "Still broken"},
            )
            _, findings, report = analyze_file(path)
        serialized = render_json(report)
        self.assertTrue(findings)
        self.assertNotIn("synthetic-password", serialized)
        self.assertGreaterEqual(report["input"]["redaction_count"], 1)

    def test_pipeline_rejects_invalid_confidence(self):
        with temporary_directory() as root:
            path = write_jsonl(root / "input.jsonl", {"role": "user", "content": "hello"})
            with self.assertRaisesRegex(ValueError, "between 0 and 1"):
                analyze_file(path, min_confidence=2.0)

    def test_report_does_not_embed_all_normalized_events(self):
        value = transcript(
            event(0, role="user", content="unrelated private narrative"),
            event(1, content="Done"),
            event(2, role="user", content="Still broken"),
        )
        findings = detect_premature_completion(value)
        rendered = render_json(report_dict(value, findings, 0, "abc"))
        self.assertNotIn("unrelated private narrative", rendered)


if __name__ == "__main__":
    unittest.main()
