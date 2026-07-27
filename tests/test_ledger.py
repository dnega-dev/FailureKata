from __future__ import annotations

import json
import unittest
from datetime import date

from failure_kata.ledger import GrowthLedger, LedgerError
from support import temporary_directory


def make_kata(root, name, pattern="skipped-verification"):
    folder = root / name
    folder.mkdir()
    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "kata_id": name,
                "finding_id": "finding-" + name,
                "pattern": pattern,
            }
        ),
        encoding="utf-8",
    )
    return folder


class GrowthLedgerTests(unittest.TestCase):
    def test_add_schedules_first_review_next_day(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            entry = ledger.add_kata(kata, on_date=date(2025, 1, 1))
        self.assertEqual(entry["next_review_on"], "2025-01-02")
        self.assertEqual(entry["interval_days"], 1)
        self.assertEqual(entry["review_count"], 0)

    def test_ledger_persists_and_reloads(self):
        with temporary_directory() as root:
            path = root / "ledger.json"
            kata = make_kata(root, "kata-one")
            GrowthLedger(path).add_kata(kata, on_date=date(2025, 1, 1))
            entries = GrowthLedger(path).entries
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kata_id"], "kata-one")

    def test_good_review_uses_spaced_interval(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            entry = ledger.add_kata(kata, on_date=date(2025, 1, 1))
            reviewed = ledger.review(entry["entry_id"], "good", on_date=date(2025, 1, 2))
        self.assertEqual(reviewed["interval_days"], 3)
        self.assertEqual(reviewed["next_review_on"], "2025-01-05")
        self.assertEqual(reviewed["review_count"], 1)

    def test_again_resets_interval_to_one_day(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            entry = ledger.add_kata(kata, on_date=date(2025, 1, 1))
            ledger.review(entry["entry_id"], "good", on_date=date(2025, 1, 2))
            reviewed = ledger.review(entry["entry_id"], "again", on_date=date(2025, 1, 5))
        self.assertEqual(reviewed["interval_days"], 1)
        self.assertEqual(reviewed["next_review_on"], "2025-01-06")

    def test_good_after_again_restarts_progression(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            entry = ledger.add_kata(kata, on_date=date(2025, 1, 1))
            ledger.review(entry["entry_id"], "good", on_date=date(2025, 1, 2))
            ledger.review(entry["entry_id"], "again", on_date=date(2025, 1, 5))
            reviewed = ledger.review(entry["entry_id"], "good", on_date=date(2025, 1, 6))
        self.assertEqual(reviewed["review_stage"], 1)
        self.assertEqual(reviewed["interval_days"], 3)

    def test_easy_review_expands_interval(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            entry = ledger.add_kata(kata, on_date=date(2025, 1, 1))
            reviewed = ledger.review(entry["entry_id"], "easy", on_date=date(2025, 1, 2))
        self.assertEqual(reviewed["interval_days"], 7)

    def test_due_filter_excludes_future_entries(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            ledger.add_kata(kata, on_date=date(2025, 1, 1))
            before = ledger.list_entries(due_only=True, on_date=date(2025, 1, 1))
            due = ledger.list_entries(due_only=True, on_date=date(2025, 1, 2))
        self.assertEqual(before, [])
        self.assertEqual(len(due), 1)

    def test_supersession_is_bidirectionally_linked(self):
        with temporary_directory() as root:
            old_kata = make_kata(root, "old-kata")
            new_kata = make_kata(root, "new-kata")
            ledger = GrowthLedger(root / "ledger.json")
            old = ledger.add_kata(old_kata, on_date=date(2025, 1, 1))
            new = ledger.add_kata(new_kata, supersedes=old["entry_id"], on_date=date(2025, 1, 2))
            old_after = ledger.get(old["entry_id"])
        self.assertEqual(new["supersedes"], old["entry_id"])
        self.assertEqual(old_after["superseded_by"], new["entry_id"])

    def test_due_filter_excludes_superseded_entries(self):
        with temporary_directory() as root:
            old_kata = make_kata(root, "old-kata")
            new_kata = make_kata(root, "new-kata")
            ledger = GrowthLedger(root / "ledger.json")
            old = ledger.add_kata(old_kata, on_date=date(2025, 1, 1))
            new = ledger.add_kata(new_kata, supersedes=old["entry_id"], on_date=date(2025, 1, 2))
            due = ledger.list_entries(due_only=True, on_date=date(2025, 1, 10))
        self.assertEqual([item["entry_id"] for item in due], [new["entry_id"]])

    def test_superseded_entry_cannot_be_reviewed(self):
        with temporary_directory() as root:
            old_kata = make_kata(root, "old-kata")
            new_kata = make_kata(root, "new-kata")
            ledger = GrowthLedger(root / "ledger.json")
            old = ledger.add_kata(old_kata, on_date=date(2025, 1, 1))
            ledger.add_kata(new_kata, supersedes=old["entry_id"], on_date=date(2025, 1, 2))
            with self.assertRaisesRegex(LedgerError, "superseded"):
                ledger.review(old["entry_id"], "good", on_date=date(2025, 1, 3))

    def test_duplicate_kata_is_rejected(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            ledger.add_kata(kata)
            with self.assertRaisesRegex(LedgerError, "already exists"):
                ledger.add_kata(kata)

    def test_invalid_kata_metadata_shape_is_rejected(self):
        with temporary_directory() as root:
            kata = root / "invalid-kata"
            kata.mkdir()
            (kata / "metadata.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(LedgerError, "JSON object"):
                GrowthLedger(root / "ledger.json").add_kata(kata)

    def test_unknown_superseded_entry_is_rejected(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            with self.assertRaisesRegex(LedgerError, "unknown ledger entry"):
                ledger.add_kata(kata, supersedes="missing")

    def test_invalid_outcome_is_rejected(self):
        with temporary_directory() as root:
            kata = make_kata(root, "kata-one")
            ledger = GrowthLedger(root / "ledger.json")
            entry = ledger.add_kata(kata)
            with self.assertRaisesRegex(LedgerError, "outcome"):
                ledger.review(entry["entry_id"], "perfect")

    def test_unsupported_schema_is_rejected(self):
        with temporary_directory() as root:
            path = root / "ledger.json"
            path.write_text('{"schema_version":"99","entries":[]}', encoding="utf-8")
            with self.assertRaisesRegex(LedgerError, "unsupported"):
                GrowthLedger(path)


if __name__ == "__main__":
    unittest.main()
