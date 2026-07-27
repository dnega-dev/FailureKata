"""High-level local analysis pipeline."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .adapters import load_transcript
from .detectors import run_detectors
from .models import Finding, Transcript
from .reporting import report_dict
from .scrub import SecretScrubber


def _file_sha256(path: Path) -> str:
    digest = sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError("cannot hash transcript %s: %s" % (path, exc)) from exc
    return digest.hexdigest()


def analyze_file(
    path: Path,
    adapter: str = "auto",
    min_confidence: float = 0.0,
) -> Tuple[Transcript, List[Finding], Dict[str, Any]]:
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    scrubber = SecretScrubber()
    transcript = load_transcript(path, adapter=adapter, scrubber=scrubber)
    findings = run_detectors(transcript, min_confidence=min_confidence)
    report = report_dict(
        transcript,
        findings,
        redaction_count=scrubber.redaction_count,
        input_sha256=_file_sha256(path),
    )
    return transcript, findings, report
