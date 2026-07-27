"""Deterministic, local-only secret scrubbing."""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Match, Pattern, Tuple


class SecretScrubber:
    """Redact common credentials while preserving equality across occurrences.

    Replacements include a short one-way digest. This lets detectors recognize
    that two already-scrubbed actions are equal without retaining the secret.
    """

    _SENSITIVE_KEY = re.compile(
        r"(?:^|[-_])(api[-_]?key|tokens?|passwords?|passwd|secrets?|authorization|cookies?|credentials?|private[-_]?key)(?:$|[-_])",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._patterns: List[Tuple[str, Pattern[str]]] = [
            (
                "private-key",
                re.compile(
                    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
                    re.DOTALL,
                ),
            ),
            ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{12,}\b")),
            ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b")),
            ("github-token", re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b")),
            ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
            (
                "jwt",
                re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
            ),
            (
                "bearer-token",
                re.compile(r"(?i)(?<=\bBearer )[A-Za-z0-9._~+/=-]{12,}"),
            ),
            (
                "basic-auth",
                re.compile(r"(?i)(?<=\bBasic )[A-Za-z0-9+/=]{12,}"),
            ),
        ]
        self._assignment = re.compile(
            r"(?i)\b(api[-_]?key|access[-_]?token|auth[-_]?token|password|passwd|secret)"
            r"(\s*[:=]\s*)([\"']?)([^\s,;\"']{6,})([\"']?)"
        )
        self.redaction_count = 0

    @staticmethod
    def _replacement(kind: str, value: str) -> str:
        digest = sha256(value.encode("utf-8")).hexdigest()[:10]
        return "[REDACTED:%s:%s]" % (kind, digest)

    def _replace_match(self, kind: str, match: Match[str]) -> str:
        self.redaction_count += 1
        return self._replacement(kind, match.group(0))

    def scrub_text(self, text: str) -> str:
        result = text
        for kind, pattern in self._patterns:
            result = pattern.sub(lambda match, label=kind: self._replace_match(label, match), result)

        def assignment_replacement(match: Match[str]) -> str:
            self.redaction_count += 1
            return "%s%s%s%s%s" % (
                match.group(1),
                match.group(2),
                match.group(3),
                self._replacement("assigned-secret", match.group(4)),
                match.group(5),
            )

        return self._assignment.sub(assignment_replacement, result)

    def _scrub_sensitive_subtree(self, value: Any) -> Any:
        if value in (None, ""):
            return value
        if isinstance(value, Mapping):
            return {
                str(item_key): self._scrub_sensitive_subtree(item_value)
                for item_key, item_value in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._scrub_sensitive_subtree(item) for item in value]
        raw = str(value)
        self.redaction_count += 1
        return self._replacement("sensitive-field", raw)

    def scrub_value(self, value: Any, key: str = "") -> Any:
        if self._SENSITIVE_KEY.search(key) and value not in (None, ""):
            return self._scrub_sensitive_subtree(value)
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, Mapping):
            return {
                str(item_key): self.scrub_value(item_value, str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self.scrub_value(item, key) for item in value]
        if isinstance(value, tuple):
            return [self.scrub_value(item, key) for item in value]
        return value
