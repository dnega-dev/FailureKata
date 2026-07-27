"""Shared test builders; all temporary data remains inside this repository."""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from failure_kata.models import Transcript, TranscriptEvent


TESTS_ROOT = Path(__file__).resolve().parent
TEMP_ROOT = TESTS_ROOT / ".tmp"
TEMP_ROOT.mkdir(exist_ok=True)


def event(
    index: int,
    event_type: str = "message",
    role: str = "assistant",
    content: str = "",
    name: Optional[str] = None,
    status: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    event_id: Optional[str] = None,
) -> TranscriptEvent:
    return TranscriptEvent(
        event_id=event_id or "e%d" % index,
        index=index,
        source_line=index + 1,
        type=event_type,
        role=role,
        content=content,
        name=name,
        status=status,
        metadata=dict(metadata or {}),
    )


def transcript(*events: TranscriptEvent, adapter: str = "generic") -> Transcript:
    return Transcript(source="synthetic.jsonl", adapter=adapter, events=events)


@contextmanager
def temporary_directory() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(dir=str(TEMP_ROOT)) as value:
        yield Path(value)


def write_jsonl(path: Path, *records: Any) -> Path:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path
