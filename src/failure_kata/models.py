"""Typed, serializable records used throughout FailureKata."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


def _json_safe(value: Any) -> Any:
    """Return JSON-compatible data without retaining mutable custom objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


@dataclass(frozen=True)
class TranscriptEvent:
    """One normalized transcript event.

    ``source_line`` is one-based and always points back to the input JSONL line.
    An adapter may emit several events for one line (for example, Claude content
    blocks); in that case each event still has a distinct ``event_id``.
    """

    event_id: str
    index: int
    source_line: int
    type: str
    role: str
    content: str
    name: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def content_sha256(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "event_id": self.event_id,
            "index": self.index,
            "source_line": self.source_line,
            "type": self.type,
            "role": self.role,
            "content": self.content,
            "content_sha256": self.content_sha256,
        }
        if self.name is not None:
            data["name"] = self.name
        if self.status is not None:
            data["status"] = self.status
        if self.timestamp is not None:
            data["timestamp"] = self.timestamp
        if self.metadata:
            data["metadata"] = _json_safe(self.metadata)
        return data


@dataclass(frozen=True)
class Transcript:
    source: str
    adapter: str
    events: Sequence[TranscriptEvent]

    def event_by_id(self, event_id: str) -> Optional[TranscriptEvent]:
        return next((event for event in self.events if event.event_id == event_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "adapter": self.adapter,
            "event_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
        }


@dataclass(frozen=True)
class Evidence:
    """A stable pointer from a finding to an exact normalized event."""

    event_id: str
    event_index: int
    source_line: int
    field: str
    excerpt: str
    content_sha256: str
    rationale: str

    @classmethod
    def from_event(
        cls,
        event: TranscriptEvent,
        rationale: str,
        field: str = "content",
        max_excerpt: int = 240,
    ) -> "Evidence":
        excerpt = event.content
        if len(excerpt) > max_excerpt:
            excerpt = excerpt[: max_excerpt - 1] + "…"
        return cls(
            event_id=event.event_id,
            event_index=event.index,
            source_line=event.source_line,
            field=field,
            excerpt=excerpt,
            content_sha256=event.content_sha256,
            rationale=rationale,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_index": self.event_index,
            "source_line": self.source_line,
            "field": self.field,
            "excerpt": self.excerpt,
            "content_sha256": self.content_sha256,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class Finding:
    finding_id: str
    pattern: str
    title: str
    severity: str
    confidence: float
    summary: str
    remediation: str
    evidence: Sequence[Evidence]
    detector_version: str = "1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "pattern": self.pattern,
            "title": self.title,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "summary": self.summary,
            "remediation": self.remediation,
            "detector_version": self.detector_version,
            "evidence": [item.to_dict() for item in self.evidence],
        }


def make_finding_id(pattern: str, evidence: Iterable[Evidence]) -> str:
    refs = "|".join(
        "%s:%s:%s" % (item.event_id, item.source_line, item.content_sha256)
        for item in evidence
    )
    return "%s-%s" % (pattern, sha256((pattern + "|" + refs).encode("utf-8")).hexdigest()[:12])


def finding(
    pattern: str,
    title: str,
    severity: str,
    confidence: float,
    summary: str,
    remediation: str,
    evidence: Iterable[Evidence],
) -> Finding:
    evidence_list: List[Evidence] = list(evidence)
    return Finding(
        finding_id=make_finding_id(pattern, evidence_list),
        pattern=pattern,
        title=title,
        severity=severity,
        confidence=confidence,
        summary=summary,
        remediation=remediation,
        evidence=evidence_list,
    )
