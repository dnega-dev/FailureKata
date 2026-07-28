from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from failure_kata.kata import KataGenerationError, generate_kata
from failure_kata.models import Evidence, finding
from support import event, temporary_directory, transcript


def make_case(pattern: str = "missing-source-lookup"):
    request = event(0, role="user", content="Fix parser.py", event_id="request")
    action = event(1, "tool_call", content='{"path":"parser.py"}', name="edit_file", event_id="action")
    unrelated = event(2, role="user", content="unrelated text must not be copied", event_id="unrelated")
    value = transcript(request, action, unrelated)
    evidence = [Evidence.from_event(request, "request"), Evidence.from_event(action, "mutation")]
    item = finding(
        pattern,
        "Practice title",
        "high",
        0.9,
        "Observed summary.",
        "Practice remediation.",
        evidence,
    )
    return value, item


class KataGenerationTests(unittest.TestCase):
    def test_generated_kata_has_required_files(self):
        value, item = make_case()
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            relative = {
                path.relative_to(folder).as_posix()
                for path in folder.rglob("*")
                if path.is_file()
            }
        self.assertEqual(
            relative,
            {
                "HINTS.md",
                "README.md",
                "SOLUTION_CONTRACT.md",
                "fixtures/events.json",
                "fixtures/scenario.json",
                "metadata.json",
                "tests/test_kata.py",
            },
        )

    def test_generator_does_not_include_solution(self):
        value, item = make_case()
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            self.assertFalse((folder / "solution.py").exists())
            self.assertIn("no solution included", (folder / "SOLUTION_CONTRACT.md").read_text(encoding="utf-8"))

    def test_fixtures_include_only_referenced_events(self):
        value, item = make_case()
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            events = json.loads((folder / "fixtures" / "events.json").read_text(encoding="utf-8"))["events"]
        self.assertEqual([entry["event_id"] for entry in events], ["request", "action"])
        self.assertNotIn("unrelated text", json.dumps(events))

    def test_scenario_records_observed_action_signatures(self):
        value, item = make_case("retrying-same-failing-action")
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            scenario = json.loads((folder / "fixtures" / "scenario.json").read_text(encoding="utf-8"))
        self.assertEqual(
            scenario["observed_actions"],
            [{"event_id": "action", "kind": "edit_file", "input": '{"path":"parser.py"}'}],
        )

    def test_metadata_does_not_copy_transcript_path(self):
        value, item = make_case()
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["source"]["transcript_not_copied"])
        self.assertNotIn(value.source, json.dumps(metadata))

    def test_existing_nonempty_kata_requires_force(self):
        value, item = make_case()
        with temporary_directory() as root:
            generate_kata(root, item, value)
            with self.assertRaisesRegex(KataGenerationError, "already exists"):
                generate_kata(root, item, value)

    def test_force_regenerates_kata_files(self):
        value, item = make_case()
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            (folder / "README.md").write_text("corrupt", encoding="utf-8")
            generate_kata(root, item, value, force=True)
            content = (folder / "README.md").read_text(encoding="utf-8")
        self.assertIn("Practice title", content)

    def test_generated_suite_fails_clearly_before_solution(self):
        value, item = make_case()
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=str(folder),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Create solution.py", result.stdout)

    def test_conforming_solution_passes_generated_suite(self):
        value, item = make_case()
        solution = '''def respond(scenario):
    ref = scenario["evidence_event_ids"][0]
    return {
        "plan": ["inspect the target", "make a bounded change"],
        "actions": [{"kind": "lookup", "input": "parser.py", "hypothesis": "the source shows the contract", "evidence_ref": ref}],
        "verification": {"command": "python -m unittest", "evidence": "all selected behavior tests pass"},
        "claims": [{"claim": "source was inspected", "evidence_ref": ref}],
    }
'''
        with temporary_directory() as root:
            folder = generate_kata(root, item, value)
            (folder / "solution.py").write_text(solution, encoding="utf-8")
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=str(folder),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Ran 7 tests", result.stdout)

    def test_generation_is_deterministic(self):
        value, item = make_case("weak-decomposition")
        with temporary_directory() as root:
            left = generate_kata(root / "left", item, value)
            right = generate_kata(root / "right", item, value)
            left_files = {
                str(path.relative_to(left)): path.read_bytes()
                for path in left.rglob("*")
                if path.is_file()
            }
            right_files = {
                str(path.relative_to(right)): path.read_bytes()
                for path in right.rglob("*")
                if path.is_file()
            }
        self.assertEqual(left_files, right_files)


if __name__ == "__main__":
    unittest.main()
