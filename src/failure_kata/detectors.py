"""Evidence-linked, deterministic transcript failure detectors.

The detectors are intentionally conservative heuristics, not claims about agent
intent. Every result includes the exact normalized events that caused it so a
human can accept, reject, or refine the generated exercise.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .models import Evidence, Finding, Transcript, TranscriptEvent, finding


Detector = Callable[[Transcript], List[Finding]]

_FAILURE_RE = re.compile(
    r"\b(traceback|exception|fatal|failed|failure|error|timed out|timeout|non[- ]zero|exit (?:code|status) [1-9]\d*)\b",
    re.IGNORECASE,
)
_SUCCESS_RE = re.compile(
    r"\b(\d+ passed|all tests pass(?:ed)?|success(?:ful(?:ly)?)?|succeeded|exit (?:code|status) 0|status: ok)\b",
    re.IGNORECASE,
)
_COMPLETION_RE = re.compile(
    r"\b(done|completed|finished|implemented|fixed|ready|all set|everything (?:is )?working|tests? pass(?:ed|ing)?)\b",
    re.IGNORECASE,
)
_NEGATED_COMPLETION_RE = re.compile(
    r"\b(?:not|isn't|wasn't|aren't|never)\s+(?:actually\s+|yet\s+)?(?:done|complete(?:d)?|finished|implemented|fixed|ready|working|pass(?:ed|ing)?)\b",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(
    r"\b(but|still|missing|forgot|incorrect|wrong|broken|fail(?:ed|ing|s)?|error|does(?:n't| not)|did(?:n't| not)|not (?:done|fixed|working))\b",
    re.IGNORECASE,
)
_VERIFY_RE = re.compile(
    r"\b(test(?:s|ing)?|pytest|unittest|compileall|typecheck|mypy|lint|ruff|flake8|build|verify|check\.sh|npm test|cargo test|go test)\b",
    re.IGNORECASE,
)
_LOOKUP_RE = re.compile(
    r"\b(read|inspect|list|search|lookup|look up|grep|glob|find|view|open|ls|cat|head|tail|sed|rg)\b",
    re.IGNORECASE,
)
_MUTATION_RE = re.compile(
    r"\b(write|edit|patch|replace|create|delete|remove|move|rename|mkdir|apply_patch|save)\b",
    re.IGNORECASE,
)


def _event_label(event: TranscriptEvent) -> str:
    return " ".join(
        part for part in (event.type, event.role, event.name or "", event.content) if part
    )


def _is_assistant(event: TranscriptEvent) -> bool:
    return event.role.lower() in {"assistant", "agent", "model"}


def _is_completion_claim(event: TranscriptEvent) -> bool:
    if not _is_assistant(event) or _is_tool_call(event) or _is_tool_result(event):
        return False
    if "?" in event.content or _NEGATED_COMPLETION_RE.search(event.content):
        return False
    return bool(_COMPLETION_RE.search(event.content))


def _is_user(event: TranscriptEvent) -> bool:
    return event.role.lower() in {"user", "human"}


def _is_user_message(event: TranscriptEvent) -> bool:
    """Claude-style tool results can carry role=user without being a new request."""
    return _is_user(event) and event.type.lower() not in {
        "tool_result", "tool-response", "result", "observation"
    }


def _is_tool_call(event: TranscriptEvent) -> bool:
    return event.type.lower() in {"tool_call", "tool_use", "action", "command"} or (
        event.name is not None and event.type.lower() not in {"tool_result", "result", "observation"}
    )


def _is_tool_result(event: TranscriptEvent) -> bool:
    return event.type.lower() in {"tool_result", "tool-response", "result", "observation"} or event.role.lower() == "tool"


def _exit_code(event: TranscriptEvent) -> Optional[int]:
    values = dict(event.metadata or {})
    try:
        decoded = json.loads(event.content)
    except (json.JSONDecodeError, TypeError):
        decoded = None
    if isinstance(decoded, dict):
        values.update(decoded)
    for key in ("returncode", "return_code", "exit_code", "exitCode"):
        if key not in values or isinstance(values[key], bool):
            continue
        try:
            return int(values[key])
        except (TypeError, ValueError):
            continue
    return None


def _is_failure(event: TranscriptEvent) -> bool:
    if event.status and event.status.lower() in {"failed", "failure", "error", "timeout", "nonzero"}:
        return True
    exit_code = _exit_code(event)
    if exit_code is not None:
        return exit_code != 0
    if _SUCCESS_RE.search(event.content) and not _FAILURE_RE.search(event.content):
        return False
    return bool(_FAILURE_RE.search(event.content))


def _is_verification(event: TranscriptEvent) -> bool:
    label = _event_label(event)
    if _VERIFY_RE.search(label):
        return True
    if _is_tool_result(event) and (
        _SUCCESS_RE.search(event.content)
        or _FAILURE_RE.search(event.content)
        or _exit_code(event) is not None
    ):
        return True
    return False


def _is_successful_verification(event: TranscriptEvent) -> bool:
    if not _is_verification(event):
        return False
    if _is_failure(event):
        return False
    if event.status and event.status.lower() in {"success", "succeeded", "passed", "ok"}:
        return True
    if _exit_code(event) == 0:
        return True
    return bool(_SUCCESS_RE.search(event.content))


def _is_lookup(event: TranscriptEvent) -> bool:
    if not _is_tool_call(event):
        return False
    name = (event.name or "").lower()
    explicit = {
        "read", "read_file", "ls", "list", "list_files", "glob", "grep", "search",
        "search_files", "view", "open_file", "inspect", "find_files",
    }
    if name in explicit or any(token in name for token in ("read", "search", "grep", "glob", "list", "inspect")):
        return True
    return bool(_LOOKUP_RE.search(event.content)) and not _is_mutation(event)


def _is_mutation(event: TranscriptEvent) -> bool:
    if not _is_tool_call(event):
        return False
    name = (event.name or "").lower()
    explicit = {
        "write", "write_file", "edit", "edit_file", "patch", "apply_patch", "save_file",
        "delete_file", "move_file", "mkdir",
    }
    if name in explicit or any(token in name for token in ("write", "edit", "patch", "delete", "save")):
        return True
    return bool(_MUTATION_RE.search(event.content))


def _canonical_action(event: TranscriptEvent) -> str:
    content = event.content.strip()
    try:
        decoded = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        normalized = re.sub(r"\s+", " ", content).strip()
    else:
        normalized = json.dumps(decoded, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "%s|%s" % ((event.name or event.type).lower(), normalized)


def _linked_call(events: Sequence[TranscriptEvent], result_index: int) -> Optional[TranscriptEvent]:
    result = events[result_index]
    tool_call_id = result.metadata.get("tool_call_id") if result.metadata else None
    if tool_call_id:
        for candidate in reversed(events[:result_index]):
            if candidate.event_id == str(tool_call_id):
                return candidate
    for candidate in reversed(events[:result_index]):
        if _is_tool_call(candidate):
            return candidate
    return None


def _ev(event: TranscriptEvent, rationale: str) -> Evidence:
    return Evidence.from_event(event, rationale)


def detect_repeated_failed_attempts(transcript: Transcript) -> List[Finding]:
    events = transcript.events
    failed_indices = [index for index, event in enumerate(events) if _is_tool_result(event) and _is_failure(event)]
    findings: List[Finding] = []
    consumed: Set[int] = set()
    for position, first_index in enumerate(failed_indices):
        if first_index in consumed:
            continue
        cluster = [first_index]
        last_index = first_index
        for candidate in failed_indices[position + 1 :]:
            if candidate - last_index > 8:
                break
            if any(_is_successful_verification(event) for event in events[last_index + 1 : candidate]):
                break
            cluster.append(candidate)
            last_index = candidate
        if len(cluster) < 2:
            continue
        consumed.update(cluster)
        evidence: List[Evidence] = []
        for number, result_index in enumerate(cluster[:4], 1):
            call = _linked_call(events, result_index)
            if call is not None:
                evidence.append(_ev(call, "attempt %d action" % number))
            evidence.append(_ev(events[result_index], "attempt %d failed" % number))
        findings.append(
            finding(
                "repeated-failed-attempts",
                "Repeated failed attempts without a verified recovery",
                "medium",
                min(0.97, 0.72 + 0.06 * len(cluster)),
                "%d failed tool attempts occurred close together without an intervening successful verification." % len(cluster),
                "Pause after a failure, form a new hypothesis from the error evidence, and verify the smallest changed assumption.",
                evidence,
            )
        )
    return findings


def detect_skipped_verification(transcript: Transcript) -> List[Finding]:
    events = transcript.events
    findings: List[Finding] = []
    for completion_index, completion in enumerate(events):
        if not _is_completion_claim(completion):
            continue
        mutation_index: Optional[int] = None
        for index in range(completion_index - 1, -1, -1):
            if _is_mutation(events[index]):
                mutation_index = index
                break
            if _is_user_message(events[index]):
                break
        if mutation_index is None:
            continue
        if any(_is_verification(event) for event in events[mutation_index + 1 : completion_index]):
            continue
        evidence = [
            _ev(events[mutation_index], "last observed code-changing action before completion"),
            _ev(completion, "completion claim made without a verification event after the change"),
        ]
        findings.append(
            finding(
                "skipped-verification",
                "Completion claimed after a change without verification",
                "high",
                0.92,
                "A mutation was followed by a completion claim with no test, build, lint, or other verification event between them.",
                "Run a relevant verification command after the final change and cite its outcome before declaring completion.",
                evidence,
            )
        )
    return findings


def detect_premature_completion(transcript: Transcript) -> List[Finding]:
    events = transcript.events
    findings: List[Finding] = []
    for completion_index, completion in enumerate(events):
        if not _is_completion_claim(completion):
            continue
        correction: Optional[TranscriptEvent] = None
        for later in events[completion_index + 1 : completion_index + 6]:
            if (_is_user_message(later) and _CORRECTION_RE.search(later.content)) or (
                _is_tool_result(later) and _is_failure(later)
            ):
                correction = later
                break
        unresolved: Optional[TranscriptEvent] = None
        for prior in reversed(events[:completion_index]):
            if _is_successful_verification(prior):
                break
            if _is_failure(prior):
                unresolved = prior
                break
        if correction is None and unresolved is None:
            continue
        evidence: List[Evidence] = []
        if unresolved is not None:
            evidence.append(_ev(unresolved, "failure remained unresolved before the completion claim"))
        evidence.append(_ev(completion, "completion claim"))
        if correction is not None:
            evidence.append(_ev(correction, "subsequent correction or failure contradicts completion"))
        findings.append(
            finding(
                "premature-completion",
                "Completion claim contradicted by nearby evidence",
                "high",
                0.96 if correction is not None else 0.82,
                "The completion claim was made while a failure was unresolved or was contradicted shortly afterward.",
                "Use an explicit done checklist and require fresh, successful evidence for every claimed outcome.",
                evidence,
            )
        )
    return findings


def _complex_request_score(text: str) -> int:
    bullet_count = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", text))
    requirement_terms = {
        "implement", "create", "add", "include", "adapter", "detector", "cli", "test",
        "tests", "docs", "readme", "license", "report", "generate", "security", "ledger",
    }
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    term_count = len(requirement_terms & tokens)
    connector_count = len(re.findall(r"[,;]|\band\b", text, re.IGNORECASE))
    return bullet_count * 2 + term_count + min(connector_count, 4) + (2 if len(text) >= 240 else 0)


def _looks_like_plan(text: str) -> bool:
    return bool(
        re.search(r"\b(plan|steps?|first.+then|break (?:this|it) down|todo|checklist)\b", text, re.IGNORECASE)
        or re.search(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", text)
    )


def detect_weak_decomposition(transcript: Transcript) -> List[Finding]:
    events = transcript.events
    findings: List[Finding] = []
    for request_index, request in enumerate(events):
        if not _is_user_message(request) or _complex_request_score(request.content) < 7:
            continue
        first_action: Optional[TranscriptEvent] = None
        has_plan = False
        for event in events[request_index + 1 :]:
            if _is_user_message(event):
                break
            if _is_assistant(event) and event.type in {"message", "assistant", "text"} and _looks_like_plan(event.content):
                has_plan = True
            if _is_tool_call(event):
                first_action = event
                break
        if first_action is None or has_plan:
            continue
        evidence = [
            _ev(request, "multi-part request with several independently verifiable requirements"),
            _ev(first_action, "execution began before an observable decomposition or checklist"),
        ]
        findings.append(
            finding(
                "weak-decomposition",
                "Complex request entered execution without visible decomposition",
                "medium",
                0.78,
                "A high-complexity request was followed by a tool action before any observable plan, checklist, or task breakdown.",
                "Convert the request into small deliverables with a verification step for each before editing.",
                evidence,
            )
        )
    return findings


def _question_tokens(text: str) -> Set[str]:
    stop = {
        "a", "an", "and", "are", "can", "could", "do", "for", "i", "in", "is", "it",
        "me", "of", "please", "the", "this", "to", "we", "what", "which", "would", "you", "your",
    }
    return {token for token in re.findall(r"[a-z0-9_./-]+", text.lower()) if token not in stop}


def _question_similarity(left: str, right: str) -> float:
    left_tokens = _question_tokens(left)
    right_tokens = _question_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / float(len(left_tokens | right_tokens))


def detect_context_loss_reasking(transcript: Transcript) -> List[Finding]:
    questions: List[TranscriptEvent] = []
    findings: List[Finding] = []
    matched: Set[str] = set()
    for event in transcript.events:
        if not _is_assistant(event) or "?" not in event.content:
            continue
        for previous in reversed(questions):
            similarity = _question_similarity(previous.content, event.content)
            if similarity >= 0.66:
                key = previous.event_id + "|" + event.event_id
                if key in matched:
                    break
                matched.add(key)
                evidence = [
                    _ev(previous, "earlier request for the same information"),
                    _ev(event, "semantically repeated request"),
                ]
                findings.append(
                    finding(
                        "context-loss-reasking",
                        "Previously asked question was repeated",
                        "medium",
                        min(0.95, 0.65 + 0.35 * similarity),
                        "Two assistant questions have strongly overlapping content, suggesting lost or unused context.",
                        "Maintain a compact fact log and consult it before asking the user to repeat information.",
                        evidence,
                    )
                )
                break
        questions.append(event)
    return findings


def detect_retrying_same_failing_action(transcript: Transcript) -> List[Finding]:
    events = transcript.events
    failed_actions: Dict[str, Tuple[TranscriptEvent, TranscriptEvent]] = {}
    findings: List[Finding] = []
    emitted: Set[str] = set()
    for index, event in enumerate(events):
        if _is_tool_result(event) and _is_failure(event):
            call = _linked_call(events, index)
            if call is not None:
                failed_actions[_canonical_action(call)] = (call, event)
            continue
        if not _is_tool_call(event):
            continue
        canonical = _canonical_action(event)
        if canonical not in failed_actions or canonical in emitted:
            continue
        original_call, failure_result = failed_actions[canonical]
        if original_call.index >= event.index:
            continue
        emitted.add(canonical)
        evidence = [
            _ev(original_call, "original action"),
            _ev(failure_result, "failure caused by the original action"),
            _ev(event, "same action retried without a visible change"),
        ]
        findings.append(
            finding(
                "retrying-same-failing-action",
                "Identical failed action was retried",
                "high",
                0.98,
                "The same normalized tool name and input were submitted again after that action failed.",
                "Change an assumption, input, environment, or strategy before retrying; state what new evidence justifies the retry.",
                evidence,
            )
        )
    return findings


def detect_missing_source_lookup(transcript: Transcript) -> List[Finding]:
    events = transcript.events
    findings: List[Finding] = []
    last_user_index = -1
    observed_lookup = False
    emitted_for_request = False
    for index, event in enumerate(events):
        if _is_user_message(event):
            last_user_index = index
            observed_lookup = False
            emitted_for_request = False
            continue
        if last_user_index < 0:
            continue
        if _is_lookup(event):
            observed_lookup = True
            continue
        if not _is_mutation(event) or observed_lookup or emitted_for_request:
            continue
        request = events[last_user_index]
        if not re.search(
            r"\b(code|repo(?:sitory)?|project|file|function|class|test|implement|fix|change|modify|add|remove|refactor)\b",
            request.content,
            re.IGNORECASE,
        ):
            continue
        emitted_for_request = True
        evidence = [
            _ev(request, "request concerns an existing code or file context"),
            _ev(event, "first observed file mutation occurred before any source lookup action"),
        ]
        findings.append(
            finding(
                "missing-source-lookup",
                "Source was modified before it was inspected",
                "high",
                0.9,
                "The first file-changing action after the request occurred before a read, list, search, or inspect action.",
                "Inspect the target and nearby tests or callers before editing; cite the inspected source in the plan.",
                evidence,
            )
        )
    return findings


def _text_fragments(content: str) -> List[str]:
    """Decode JSON tool inputs so embedded test source is inspected as source."""
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return [content]
    fragments: List[str] = []

    def collect(item: object) -> None:
        if isinstance(item, str):
            fragments.append(item)
        elif isinstance(item, dict):
            for key, nested in item.items():
                fragments.append(str(key))
                collect(nested)
        elif isinstance(item, list):
            for nested in item:
                collect(nested)

    collect(value)
    return fragments or [content]


def _assertion_lines(content: str) -> List[str]:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if re.search(r"\bassert(?:Equal|True|False|Is|In|Not|Raises)?\b", stripped):
            lines.append(stripped)
    return lines


def detect_tests_only_assert_status(transcript: Transcript) -> List[Finding]:
    findings: List[Finding] = []
    for event in transcript.events:
        fragments = _text_fragments(event.content)
        if not any(re.search(r"\b(test_|unittest|pytest|tests?[/\\]|Test[A-Z])", fragment) for fragment in fragments):
            continue
        assertions = [line for fragment in fragments for line in _assertion_lines(fragment)]
        if not assertions:
            continue
        if not all(re.search(r"\b(status(?:_code)?|http_status|returncode|exit_code)\b", line, re.IGNORECASE) for line in assertions):
            continue
        evidence = [_ev(event, "all %d observed assertion(s) check only status or exit code" % len(assertions))]
        findings.append(
            finding(
                "tests-only-assert-status",
                "Test assertions check status but not behavior",
                "medium",
                0.94,
                "Every assertion visible in the test-writing event targets an HTTP status, process status, or exit code.",
                "Assert a meaningful output, state transition, side effect, or error contract in addition to status.",
                evidence,
            )
        )
    return findings


DETECTORS: Sequence[Tuple[str, str, Detector]] = (
    ("repeated-failed-attempts", "Repeated failed attempts without recovery", detect_repeated_failed_attempts),
    ("skipped-verification", "Completion after a change without verification", detect_skipped_verification),
    ("premature-completion", "Completion contradicted by failure evidence", detect_premature_completion),
    ("weak-decomposition", "Complex task executed without decomposition", detect_weak_decomposition),
    ("context-loss-reasking", "Repeated request for the same information", detect_context_loss_reasking),
    ("retrying-same-failing-action", "Identical failed action retried", detect_retrying_same_failing_action),
    ("missing-source-lookup", "Mutation before source inspection", detect_missing_source_lookup),
    ("tests-only-assert-status", "Tests assert status rather than behavior", detect_tests_only_assert_status),
)


def detector_descriptions() -> List[Dict[str, str]]:
    return [{"pattern": pattern, "description": description} for pattern, description, _ in DETECTORS]


def run_detectors(transcript: Transcript, min_confidence: float = 0.0) -> List[Finding]:
    findings: List[Finding] = []
    for _, _, detector in DETECTORS:
        findings.extend(item for item in detector(transcript) if item.confidence >= min_confidence)
    findings.sort(key=lambda item: (-item.confidence, item.pattern, item.finding_id))
    return findings
