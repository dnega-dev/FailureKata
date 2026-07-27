"""Adapters for generic and simplified Claude Code JSONL transcripts."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .models import Transcript, TranscriptEvent
from .scrub import SecretScrubber


class AdapterError(ValueError):
    """Raised for malformed or unsupported transcript input."""


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _status(value: Any, is_error: Any = None) -> Optional[str]:
    if is_error is True:
        return "failed"
    if value is None:
        return None
    text = str(value).lower()
    if text in {"error", "failed", "failure", "nonzero", "timeout"}:
        return "failed"
    if text in {"ok", "success", "succeeded", "passed", "pass", "complete"}:
        return "success"
    return str(value)


def _unique_event_id(candidate: str, events: Sequence[TranscriptEvent]) -> str:
    """Return a stable unique ID even when a source repeats its own IDs."""
    used = {event.event_id for event in events}
    if candidate not in used:
        return candidate
    suffix = 2
    while "%s-%d" % (candidate, suffix) in used:
        suffix += 1
    return "%s-%d" % (candidate, suffix)


class TranscriptAdapter(ABC):
    name = "base"
    description = ""

    @abstractmethod
    def parse_records(self, records: Sequence[Tuple[int, Mapping[str, Any]]], source: str) -> Transcript:
        raise NotImplementedError

    def parse_file(self, path: Path, scrubber: Optional[SecretScrubber] = None) -> Transcript:
        scrubber = scrubber or SecretScrubber()
        records: List[Tuple[int, Mapping[str, Any]]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, 1):
                    if not raw_line.strip():
                        continue
                    try:
                        value = json.loads(raw_line)
                    except json.JSONDecodeError as exc:
                        raise AdapterError(
                            "%s:%d: invalid JSON: %s" % (path, line_number, exc.msg)
                        ) from exc
                    if not isinstance(value, Mapping):
                        raise AdapterError(
                            "%s:%d: each JSONL line must be an object" % (path, line_number)
                        )
                    records.append((line_number, scrubber.scrub_value(value)))
        except OSError as exc:
            raise AdapterError("cannot read transcript %s: %s" % (path, exc)) from exc
        if not records:
            raise AdapterError("transcript is empty: %s" % path)
        return self.parse_records(records, str(path))


class GenericJSONLAdapter(TranscriptAdapter):
    name = "generic"
    description = "One normalized message or event object per JSONL line."

    def parse_records(self, records: Sequence[Tuple[int, Mapping[str, Any]]], source: str) -> Transcript:
        events: List[TranscriptEvent] = []
        for index, (line_number, record) in enumerate(records):
            event_type = str(record.get("type") or record.get("event_type") or "message").lower()
            role = str(record.get("role") or record.get("actor") or record.get("speaker") or "unknown").lower()
            content_value = record.get("content")
            if content_value is None:
                content_value = record.get("message", record.get("text", record.get("output", record.get("input", ""))))
            name_value = record.get("name", record.get("tool_name"))
            source_event_id = str(record.get("event_id") or record.get("id") or "line-%d" % line_number)
            event_id = _unique_event_id(source_event_id, events)
            reserved = {
                "type", "event_type", "role", "actor", "speaker", "content", "message", "text",
                "output", "input", "name", "tool_name", "status", "timestamp", "id", "event_id",
            }
            metadata = {
                str(key): value for key, value in record.items() if key not in reserved
            }
            if event_id != source_event_id:
                metadata["source_event_id"] = source_event_id
            events.append(
                TranscriptEvent(
                    event_id=event_id,
                    index=index,
                    source_line=line_number,
                    type=event_type,
                    role=role,
                    content=_stringify(content_value),
                    name=str(name_value) if name_value is not None else None,
                    status=_status(record.get("status"), record.get("is_error")),
                    timestamp=str(record["timestamp"]) if record.get("timestamp") is not None else None,
                    metadata=metadata,
                )
            )
        return Transcript(source=source, adapter=self.name, events=events)


class ClaudeCodeJSONLAdapter(TranscriptAdapter):
    """Parse a useful, deliberately simplified subset of Claude Code JSONL.

    Supported lines have ``type`` user/assistant/system and a nested ``message``
    with string or content-block-list ``content``. Top-level ``tool_result``
    events are also accepted. Unknown lines remain visible as normalized events.
    """

    name = "claude-code"
    description = "Simplified Claude Code JSONL with nested message content blocks."

    def parse_records(self, records: Sequence[Tuple[int, Mapping[str, Any]]], source: str) -> Transcript:
        events: List[TranscriptEvent] = []

        def emit(
            line_number: int,
            event_id: str,
            event_type: str,
            role: str,
            content: Any,
            name: Any = None,
            status: Any = None,
            timestamp: Any = None,
            metadata: Optional[Mapping[str, Any]] = None,
        ) -> None:
            resolved_id = _unique_event_id(event_id, events)
            event_metadata = dict(metadata or {})
            if resolved_id != event_id:
                event_metadata["source_event_id"] = event_id
            events.append(
                TranscriptEvent(
                    event_id=resolved_id,
                    index=len(events),
                    source_line=line_number,
                    type=event_type.lower(),
                    role=role.lower(),
                    content=_stringify(content),
                    name=str(name) if name is not None else None,
                    status=_status(status, event_metadata.get("is_error")),
                    timestamp=str(timestamp) if timestamp is not None else None,
                    metadata=event_metadata,
                )
            )

        for line_number, record in records:
            top_type = str(record.get("type") or "event").lower()
            timestamp = record.get("timestamp")
            if top_type in {"user", "assistant", "system"} and isinstance(record.get("message"), Mapping):
                message = record["message"]
                role = str(message.get("role") or top_type)
                message_id = str(message.get("id") or record.get("uuid") or "line-%d" % line_number)
                content = message.get("content", "")
                if isinstance(content, list):
                    text_number = 0
                    for block_number, block in enumerate(content):
                        if not isinstance(block, Mapping):
                            emit(line_number, "%s-block-%d" % (message_id, block_number), "message", role, block, timestamp=timestamp)
                            continue
                        block_type = str(block.get("type") or "text").lower()
                        if block_type == "text":
                            event_id = message_id if text_number == 0 else "%s-text-%d" % (message_id, text_number)
                            text_number += 1
                            emit(line_number, event_id, "message", role, block.get("text", ""), timestamp=timestamp)
                        elif block_type == "tool_use":
                            tool_id = str(block.get("id") or "%s-tool-%d" % (message_id, block_number))
                            emit(
                                line_number,
                                tool_id,
                                "tool_call",
                                role,
                                block.get("input", {}),
                                name=block.get("name"),
                                timestamp=timestamp,
                                metadata={"message_id": message_id, "tool_call_id": tool_id},
                            )
                        elif block_type == "tool_result":
                            result_id = "%s-result-%d" % (message_id, block_number)
                            emit(
                                line_number,
                                result_id,
                                "tool_result",
                                role,
                                block.get("content", ""),
                                status="failed" if block.get("is_error") else block.get("status"),
                                timestamp=timestamp,
                                metadata={
                                    "message_id": message_id,
                                    "tool_call_id": block.get("tool_use_id"),
                                    "is_error": bool(block.get("is_error")),
                                },
                            )
                        else:
                            emit(
                                line_number,
                                "%s-block-%d" % (message_id, block_number),
                                block_type,
                                role,
                                block,
                                timestamp=timestamp,
                                metadata={"message_id": message_id},
                            )
                else:
                    emit(line_number, message_id, "message", role, content, timestamp=timestamp)
                continue

            if top_type in {"tool_result", "tool-result"}:
                result_id = str(record.get("id") or "line-%d-result" % line_number)
                emit(
                    line_number,
                    result_id,
                    "tool_result",
                    str(record.get("role") or "tool"),
                    record.get("content", record.get("output", "")),
                    name=record.get("name"),
                    status=record.get("status"),
                    timestamp=timestamp,
                    metadata={
                        "tool_call_id": record.get("tool_use_id") or record.get("tool_call_id"),
                        "is_error": bool(record.get("is_error")),
                    },
                )
                continue

            generic_id = str(record.get("id") or record.get("uuid") or "line-%d" % line_number)
            emit(
                line_number,
                generic_id,
                top_type,
                str(record.get("role") or "unknown"),
                record.get("content", record.get("message", record)),
                name=record.get("name"),
                status=record.get("status"),
                timestamp=timestamp,
            )
        return Transcript(source=source, adapter=self.name, events=events)


_ADAPTERS = {
    GenericJSONLAdapter.name: GenericJSONLAdapter,
    ClaudeCodeJSONLAdapter.name: ClaudeCodeJSONLAdapter,
}


def adapter_descriptions() -> List[Dict[str, str]]:
    return [
        {"name": name, "description": adapter.description}
        for name, adapter in sorted(_ADAPTERS.items())
    ]


def get_adapter(name: str) -> TranscriptAdapter:
    try:
        return _ADAPTERS[name]()
    except KeyError as exc:
        raise AdapterError(
            "unknown adapter %r (choose from: %s)" % (name, ", ".join(sorted(_ADAPTERS)))
        ) from exc


def detect_adapter(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, 1):
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise AdapterError("%s:%d: invalid JSON: %s" % (path, line_number, exc.msg)) from exc
                if isinstance(record, Mapping):
                    record_type = str(record.get("type") or "").lower()
                    if (
                        record_type in {"user", "assistant", "system"}
                        and isinstance(record.get("message"), Mapping)
                    ) or (
                        record_type in {"tool_result", "tool-result"}
                        and ("tool_use_id" in record or "tool_call_id" in record)
                    ):
                        return "claude-code"
                    return "generic"
                raise AdapterError("%s:%d: each JSONL line must be an object" % (path, line_number))
    except OSError as exc:
        raise AdapterError("cannot read transcript %s: %s" % (path, exc)) from exc
    raise AdapterError("transcript is empty: %s" % path)


def load_transcript(path: Path, adapter: str = "auto", scrubber: Optional[SecretScrubber] = None) -> Transcript:
    selected = detect_adapter(path) if adapter == "auto" else adapter
    return get_adapter(selected).parse_file(path, scrubber=scrubber)
