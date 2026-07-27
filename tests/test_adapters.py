from __future__ import annotations

import unittest

from failure_kata.adapters import AdapterError, detect_adapter, load_transcript
from support import temporary_directory, write_jsonl


class AdapterTests(unittest.TestCase):
    def test_generic_adapter_normalizes_aliases(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"id": "one", "event_type": "note", "actor": "agent", "text": "hello"},
                {"type": "tool_result", "role": "tool", "output": {"ok": True}, "status": "ok"},
            )
            result = load_transcript(path, "generic")
        self.assertEqual(result.adapter, "generic")
        self.assertEqual(result.events[0].event_id, "one")
        self.assertEqual(result.events[0].role, "agent")
        self.assertEqual(result.events[1].content, '{"ok":true}')
        self.assertEqual(result.events[1].status, "success")

    def test_generic_fallback_id_and_source_line(self):
        with temporary_directory() as root:
            path = root / "input.jsonl"
            path.write_text("\n" + '{"role":"user","content":"hi"}\n', encoding="utf-8")
            result = load_transcript(path, "generic")
        self.assertEqual(result.events[0].event_id, "line-2")
        self.assertEqual(result.events[0].source_line, 2)

    def test_duplicate_source_ids_receive_stable_unique_ids(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"id": "same", "role": "user", "content": "one"},
                {"id": "same", "role": "assistant", "content": "two"},
                {"id": "same", "role": "assistant", "content": "three"},
            )
            result = load_transcript(path, "generic")
        self.assertEqual([item.event_id for item in result.events], ["same", "same-2", "same-3"])
        self.assertEqual(result.events[1].metadata["source_event_id"], "same")

    def test_invalid_json_reports_line_without_echoing_content(self):
        with temporary_directory() as root:
            path = root / "broken.jsonl"
            path.write_text('{"ok": true}\nnot-a-secret-json\n', encoding="utf-8")
            with self.assertRaises(AdapterError) as caught:
                load_transcript(path, "generic")
        self.assertIn(":2: invalid JSON", str(caught.exception))
        self.assertNotIn("not-a-secret-json", str(caught.exception))

    def test_non_object_json_is_rejected(self):
        with temporary_directory() as root:
            path = root / "array.jsonl"
            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(AdapterError, "must be an object"):
                load_transcript(path, "generic")

    def test_auto_detects_generic(self):
        with temporary_directory() as root:
            path = write_jsonl(root / "input.jsonl", {"role": "user", "content": "hi"})
            self.assertEqual(detect_adapter(path), "generic")

    def test_generic_nested_message_without_claude_role_stays_generic(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"type": "audit", "message": {"result": "ok"}},
            )
            self.assertEqual(detect_adapter(path), "generic")

    def test_auto_detects_claude_code(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "input.jsonl",
                {"type": "user", "message": {"id": "m1", "role": "user", "content": "hi"}},
            )
            self.assertEqual(detect_adapter(path), "claude-code")

    def test_claude_content_blocks_become_distinct_events(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "claude.jsonl",
                {
                    "type": "assistant",
                    "message": {
                        "id": "m1",
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "checking"},
                            {"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": "false"}},
                        ],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "id": "m2",
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "call-1", "is_error": True, "content": "failed"}
                        ],
                    },
                },
            )
            result = load_transcript(path, "claude-code")
        self.assertEqual([item.event_id for item in result.events], ["m1", "call-1", "m2-result-0"])
        self.assertEqual(result.events[1].type, "tool_call")
        self.assertEqual(result.events[2].status, "failed")
        self.assertEqual(result.events[2].metadata["tool_call_id"], "call-1")

    def test_adapter_scrubs_before_normalizing_metadata(self):
        with temporary_directory() as root:
            path = write_jsonl(
                root / "secret.jsonl",
                {"role": "user", "content": "hello", "api_key": "synthetic-sensitive-value"},
            )
            result = load_transcript(path, "generic")
        self.assertNotIn("synthetic-sensitive-value", result.events[0].metadata["api_key"])

    def test_empty_input_is_rejected(self):
        with temporary_directory() as root:
            path = root / "empty.jsonl"
            path.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(AdapterError, "empty"):
                load_transcript(path)


if __name__ == "__main__":
    unittest.main()
