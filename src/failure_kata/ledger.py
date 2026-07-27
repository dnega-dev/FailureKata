"""Local growth ledger with supersession links and spaced review dates."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


LEDGER_SCHEMA_VERSION = "1.0"
INTERVALS = (1, 3, 7, 14, 30, 60, 120)


class LedgerError(ValueError):
    pass


def _today(value: Optional[date] = None) -> date:
    return value or date.today()


class GrowthLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": LEDGER_SCHEMA_VERSION, "entries": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError("cannot read ledger %s: %s" % (self.path, exc)) from exc
        if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
            raise LedgerError("ledger must be an object with an entries list")
        if value.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise LedgerError("unsupported ledger schema version: %r" % value.get("schema_version"))
        if any(not isinstance(entry, dict) for entry in value["entries"]):
            raise LedgerError("every ledger entry must be a JSON object")
        return value

    @property
    def entries(self) -> List[Dict[str, Any]]:
        return self.data["entries"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def get(self, entry_id: str) -> Dict[str, Any]:
        for entry in self.entries:
            if entry.get("entry_id") == entry_id:
                return entry
        raise LedgerError("unknown ledger entry: %s" % entry_id)

    def add_kata(
        self,
        kata_path: Path,
        supersedes: Optional[str] = None,
        on_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        metadata_path = kata_path / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError("cannot read kata metadata %s: %s" % (metadata_path, exc)) from exc
        if not isinstance(metadata, Mapping):
            raise LedgerError("kata metadata must be a JSON object: %s" % metadata_path)
        if not metadata.get("finding_id") or not metadata.get("pattern"):
            raise LedgerError("kata metadata requires finding_id and pattern: %s" % metadata_path)
        kata_id = str(metadata.get("kata_id") or kata_path.name)
        if any(entry.get("kata_id") == kata_id for entry in self.entries):
            raise LedgerError("kata already exists in ledger: %s" % kata_id)
        if supersedes is not None:
            previous = self.get(supersedes)
            if previous.get("superseded_by"):
                raise LedgerError("entry is already superseded: %s" % supersedes)
        day = _today(on_date)
        entry_id = "entry-%04d-%s" % (len(self.entries) + 1, kata_id)
        entry: Dict[str, Any] = {
            "entry_id": entry_id,
            "kata_id": kata_id,
            "kata_path": str(kata_path),
            "finding_id": metadata.get("finding_id"),
            "pattern": metadata.get("pattern"),
            "created_on": day.isoformat(),
            "review_count": 0,
            "review_stage": 0,
            "interval_days": INTERVALS[0],
            "next_review_on": (day + timedelta(days=INTERVALS[0])).isoformat(),
            "reviews": [],
            "supersedes": supersedes,
            "superseded_by": None,
        }
        self.entries.append(entry)
        if supersedes is not None:
            self.get(supersedes)["superseded_by"] = entry_id
        self.save()
        return entry

    def list_entries(self, due_only: bool = False, on_date: Optional[date] = None) -> List[Dict[str, Any]]:
        day = _today(on_date)
        result = []
        for entry in self.entries:
            if due_only and (
                entry.get("superseded_by") is not None
                or date.fromisoformat(entry["next_review_on"]) > day
            ):
                continue
            result.append(dict(entry))
        return result

    def review(self, entry_id: str, outcome: str, on_date: Optional[date] = None) -> Dict[str, Any]:
        if outcome not in {"again", "hard", "good", "easy"}:
            raise LedgerError("outcome must be one of: again, hard, good, easy")
        entry = self.get(entry_id)
        if entry.get("superseded_by"):
            raise LedgerError("cannot review superseded entry: %s" % entry_id)
        day = _today(on_date)
        current = int(entry.get("interval_days", 1))
        review_count = int(entry.get("review_count", 0))
        stage = int(entry.get("review_stage", min(review_count, len(INTERVALS) - 1)))
        if outcome == "again":
            stage = 0
            interval = INTERVALS[stage]
        elif outcome == "hard":
            interval = max(1, round(current * 1.5))
        elif outcome == "good":
            stage = min(stage + 1, len(INTERVALS) - 1)
            interval = INTERVALS[stage]
        else:
            stage = min(stage + 2, len(INTERVALS) - 1)
            interval = max(INTERVALS[stage], current * 2)
        entry["review_count"] = review_count + 1
        entry["review_stage"] = stage
        entry["interval_days"] = int(interval)
        entry["last_review_on"] = day.isoformat()
        entry["next_review_on"] = (day + timedelta(days=int(interval))).isoformat()
        entry["reviews"].append(
            {
                "reviewed_on": day.isoformat(),
                "outcome": outcome,
                "review_stage": stage,
                "interval_days": int(interval),
                "next_review_on": entry["next_review_on"],
            }
        )
        self.save()
        return dict(entry)
