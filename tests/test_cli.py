from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from failure_kata.cli import main
from support import temporary_directory, write_jsonl


class CLITests(unittest.TestCase):
    def test_adapters_json_lists_two_adapters_and_eight_detectors(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["adapters", "--format", "json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual({item["name"] for item in payload["adapters"]}, {"generic", "claude-code"})
        self.assertEqual(len(payload["detectors"]), 8)

    def test_analyze_writes_json_to_stdout(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"id": "a", "role": "assistant", "content": "Done"},
                {"id": "b", "role": "user", "content": "Still broken"},
            )
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["analyze", str(path), "--format", "json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertGreaterEqual(payload["summary"]["finding_count"], 1)

    def test_analyze_can_write_markdown_file(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"id": "a", "role": "assistant", "content": "Done"},
                {"id": "b", "role": "user", "content": "Still broken"},
            )
            report_path = root / "reports" / "analysis.md"
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["analyze", str(path), "--format", "markdown", "-o", str(report_path)])
            rendered = report_path.read_text(encoding="utf-8")
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("# FailureKata analysis", rendered)

    def test_analyze_refuses_to_overwrite_input_transcript(self):
        with temporary_directory() as root:
            path = write_jsonl(root / "input.jsonl", {"role": "user", "content": "hello"})
            original = path.read_bytes()
            error = io.StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit):
                main(["analyze", str(path), "-o", str(path)])
            self.assertEqual(path.read_bytes(), original)
        self.assertIn("must not overwrite", error.getvalue())

    def test_generate_creates_selected_pattern(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"id": "u", "role": "user", "content": "Fix parser.py"},
                {"id": "e", "type": "tool_call", "role": "assistant", "name": "edit_file", "content": {"path": "parser.py"}},
            )
            output_root = root / "generated"
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "generate",
                        str(path),
                        "-o",
                        str(output_root),
                        "--finding",
                        "missing-source-lookup",
                        "--format",
                        "json",
                    ]
                )
            payload = json.loads(output.getvalue())
            folder = output_root / payload["generated"][0].split("/")[-1]
            metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(metadata["pattern"], "missing-source-lookup")

    def test_generate_without_finding_reports_safe_error(self):
        with temporary_directory() as root:
            path = write_jsonl(root / "input.jsonl", {"role": "user", "content": "hello"})
            error = io.StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                main(["generate", str(path), "-o", str(root / "out")])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("no supported failure pattern", error.getvalue())

    def test_ledger_add_and_list_json(self):
        with temporary_directory() as root:
            kata = root / "kata"
            kata.mkdir()
            (kata / "metadata.json").write_text(
                json.dumps({"kata_id": "kata", "finding_id": "finding", "pattern": "skipped-verification"}),
                encoding="utf-8",
            )
            ledger = root / "ledger.json"
            with redirect_stdout(io.StringIO()):
                add_result = main(["ledger", "--file", str(ledger), "add", str(kata)])
            output = io.StringIO()
            with redirect_stdout(output):
                list_result = main(["ledger", "--file", str(ledger), "list", "--format", "json"])
        payload = json.loads(output.getvalue())
        self.assertEqual((add_result, list_result), (0, 0))
        self.assertEqual(payload["entries"][0]["kata_id"], "kata")

    def test_invalid_json_exits_without_traceback(self):
        with temporary_directory() as root:
            path = root / "bad.jsonl"
            path.write_text("not json\n", encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                main(["analyze", str(path)])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn("Traceback", error.getvalue())
        self.assertIn("invalid JSON", error.getvalue())


if __name__ == "__main__":
    unittest.main()
