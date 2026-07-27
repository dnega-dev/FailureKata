from __future__ import annotations

import unittest

from failure_kata.scrub import SecretScrubber


class SecretScrubberTests(unittest.TestCase):
    def test_openai_style_key_is_redacted(self):
        scrubber = SecretScrubber()
        result = scrubber.scrub_text("key sk-proj-abcdefghijklmnopqrstuvwxyz123456")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", result)
        self.assertIn("[REDACTED:openai-key:", result)

    def test_repeated_value_has_stable_redaction(self):
        scrubber = SecretScrubber()
        token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        result = scrubber.scrub_text("%s then %s" % (token, token))
        redactions = [word for word in result.split() if word.startswith("[REDACTED")]
        self.assertEqual(redactions[0], redactions[1])
        self.assertEqual(scrubber.redaction_count, 2)

    def test_sensitive_mapping_field_is_redacted(self):
        scrubber = SecretScrubber()
        value = scrubber.scrub_value({"nested": {"api_key": "low-entropy-value"}})
        self.assertTrue(value["nested"]["api_key"].startswith("[REDACTED:sensitive-field:"))

    def test_sensitive_container_redacts_all_leaf_values(self):
        scrubber = SecretScrubber()
        result = scrubber.scrub_value(
            {"credentials": {"username": "synthetic-user", "password": "synthetic-pass", "scopes": ["admin"]}}
        )
        serialized = str(result)
        self.assertNotIn("synthetic-user", serialized)
        self.assertNotIn("synthetic-pass", serialized)
        self.assertNotIn("admin", serialized)
        self.assertEqual(scrubber.redaction_count, 3)

    def test_bearer_token_is_redacted(self):
        scrubber = SecretScrubber()
        result = scrubber.scrub_text("Authorization: Bearer ABCDEFGHIJKLMNOPQRST")
        self.assertNotIn("ABCDEFGHIJKLMNOP", result)
        self.assertIn("[REDACTED:bearer-token:", result)

    def test_assignment_secret_is_redacted(self):
        scrubber = SecretScrubber()
        result = scrubber.scrub_text("password='synthetic-password-value'")
        self.assertNotIn("synthetic-password-value", result)
        self.assertIn("assigned-secret", result)

    def test_private_key_block_is_redacted(self):
        scrubber = SecretScrubber()
        value = "-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n-----END PRIVATE KEY-----"
        result = scrubber.scrub_text(value)
        self.assertEqual(result.count("[REDACTED:private-key:"), 1)
        self.assertNotIn("SYNTHETIC", result)

    def test_innocent_text_is_unchanged(self):
        scrubber = SecretScrubber()
        text = "Run python -m unittest and inspect parser.py"
        self.assertEqual(scrubber.scrub_text(text), text)
        self.assertEqual(scrubber.redaction_count, 0)

    def test_list_values_are_scrubbed_recursively(self):
        scrubber = SecretScrubber()
        result = scrubber.scrub_value([{"auth_token": "a-secret-token-value"}])
        self.assertNotIn("a-secret-token-value", result[0]["auth_token"])


if __name__ == "__main__":
    unittest.main()
