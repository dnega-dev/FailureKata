from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from failure_kata.pipeline import analyze_file


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "failure_kata"


class ProjectContractTests(unittest.TestCase):
    def test_runtime_declares_zero_dependencies(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("dependencies = []", pyproject)

    def test_source_has_no_network_client_imports(self):
        forbidden = {"requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket"}
        imports = set()
        for path in SOURCE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        self.assertTrue(forbidden.isdisjoint(imports), "network import present: %s" % sorted(forbidden & imports))

    def test_sample_transcripts_are_valid_jsonl_objects(self):
        paths = sorted((ROOT / "examples" / "transcripts").glob("*.jsonl"))
        self.assertGreaterEqual(len(paths), 2)
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertIsInstance(json.loads(line), dict)

    def test_generic_sample_exercises_all_eight_patterns(self):
        _, findings, _ = analyze_file(ROOT / "examples" / "transcripts" / "generic_failure.jsonl")
        patterns = {item.pattern for item in findings}
        self.assertEqual(
            patterns,
            {
                "context-loss-reasking",
                "missing-source-lookup",
                "premature-completion",
                "repeated-failed-attempts",
                "retrying-same-failing-action",
                "skipped-verification",
                "tests-only-assert-status",
                "weak-decomposition",
            },
        )

    def test_claude_sample_auto_detects_adapter(self):
        transcript, findings, _ = analyze_file(ROOT / "examples" / "transcripts" / "claude_code_failure.jsonl")
        self.assertEqual(transcript.adapter, "claude-code")
        self.assertTrue(findings)

    def test_required_project_files_exist(self):
        required = [
            "README.md",
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "pyproject.toml",
            "docs/detection-model.md",
            "ci/check.sh",
        ]
        self.assertEqual([item for item in required if not (ROOT / item).is_file()], [])


if __name__ == "__main__":
    unittest.main()
