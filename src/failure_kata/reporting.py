"""JSON and Markdown analysis reports."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Sequence

from .models import Finding, Transcript


REPORT_SCHEMA_VERSION = "1.0"


def report_dict(
    transcript: Transcript,
    findings: Sequence[Finding],
    redaction_count: int,
    input_sha256: str,
) -> Dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": {"name": "failure-kata", "version": "0.1.0"},
        "input": {
            "source": transcript.source,
            "sha256": input_sha256,
            "adapter": transcript.adapter,
            "event_count": len(transcript.events),
            "redaction_count": redaction_count,
        },
        "summary": {
            "finding_count": len(findings),
            "patterns": sorted({item.pattern for item in findings}),
        },
        "findings": [item.to_dict() for item in findings],
    }


def render_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Mapping[str, Any]) -> str:
    input_info = report["input"]
    lines = [
        "# FailureKata analysis",
        "",
        "- **Source:** `%s`" % input_info["source"],
        "- **Adapter:** `%s`" % input_info["adapter"],
        "- **Input SHA-256:** `%s`" % input_info["sha256"],
        "- **Normalized events:** %s" % input_info["event_count"],
        "- **Secret redactions:** %s" % input_info["redaction_count"],
        "- **Findings:** %s" % report["summary"]["finding_count"],
        "",
    ]
    findings = report["findings"]
    if not findings:
        lines.extend(
            [
                "No supported patterns were detected. This does not prove the transcript is failure-free.",
                "",
            ]
        )
        return "\n".join(lines)

    for number, finding in enumerate(findings, 1):
        lines.extend(
            [
                "## %d. %s" % (number, finding["title"]),
                "",
                "| Field | Value |",
                "| --- | --- |",
                "| ID | `%s` |" % _escape_cell(finding["finding_id"]),
                "| Pattern | `%s` |" % _escape_cell(finding["pattern"]),
                "| Severity | %s |" % _escape_cell(finding["severity"]),
                "| Confidence | %.3f |" % finding["confidence"],
                "",
                finding["summary"],
                "",
                "**Practice focus:** %s" % finding["remediation"],
                "",
                "### Evidence",
                "",
            ]
        )
        for evidence in finding["evidence"]:
            lines.extend(
                [
                    "- `%s` — event %s, source line %s, field `%s`, SHA-256 `%s`",
                    "  - Why: %s",
                    "  - Excerpt: `%s`",
                ]
            )
            lines[-3] = lines[-3] % (
                evidence["event_id"],
                evidence["event_index"],
                evidence["source_line"],
                evidence["field"],
                evidence["content_sha256"],
            )
            lines[-2] = lines[-2] % evidence["rationale"]
            lines[-1] = lines[-1] % _escape_cell(evidence["excerpt"].replace("`", "\\`"))
        lines.append("")
    return "\n".join(lines)
