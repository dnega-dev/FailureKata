"""FailureKata: turn coding-agent failures into local practice exercises."""

from .models import Evidence, Finding, Transcript, TranscriptEvent
from .pipeline import analyze_file

__all__ = [
    "Evidence",
    "Finding",
    "Transcript",
    "TranscriptEvent",
    "analyze_file",
]

__version__ = "0.1.0"
