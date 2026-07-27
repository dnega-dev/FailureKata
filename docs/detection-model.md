# Detection model

FailureKata uses deterministic, inspectable heuristics. A finding means “these events match a practice-worthy pattern,” not “the agent intended to fail” or “the work is objectively bad.” The analyzer does not execute messages, consult a model, access source files mentioned in a transcript, or use the network.

## Normalized evidence

Adapters produce ordered `TranscriptEvent` records with:

- a stable `event_id` (source ID or `line-N` fallback);
- zero-based normalized `index`;
- one-based JSONL `source_line`;
- `type`, `role`, optional tool `name`, optional `status`, and scrubbed `content`;
- scrubbed source metadata.

Every evidence record repeats the event ID, index, line, field (`content` in this version), a bounded excerpt, SHA-256 of the complete scrubbed content, and a detector-specific rationale. Thus an excerpt can be checked against the exact normalized event without embedding an entire transcript in a report.

Confidence is a deterministic heuristic in `[0, 1]`; it is not a calibrated probability. Severity estimates learning risk, not security impact.

## Detectors

### `repeated-failed-attempts`

**Trigger:** at least two failed tool-result events occur within eight normalized events of one another, with no successful verification between adjacent failures. Linked tool calls are included where available.

**Why it matters:** a run of failures often signals that the working hypothesis was not revised.

**Limits:** distinct, well-reasoned experiments can still form a cluster. Conversely, a transcript that omits tool results cannot trigger it.

### `skipped-verification`

**Trigger:** a file/code mutation is followed by an assistant completion phrase before any recognized test, build, lint, typecheck, or explicit verification event.

**Why it matters:** a successful write operation proves only that bytes changed, not that behavior is correct.

**Limits:** verification performed outside the transcript is invisible. Prose mentioning “test” can be interpreted as verification, favoring fewer false positives over recall.

### `premature-completion`

**Trigger:** an assistant completion phrase has an unresolved preceding failure since the last successful verification, or is contradicted within five events by a user correction or failed tool result.

**Why it matters:** done criteria should be evidence-gated.

**Limits:** a user message containing generic correction language can be unrelated. The short look-ahead window deliberately avoids distant causal claims.

### `weak-decomposition`

**Trigger:** a user request scores as complex from length, requirement vocabulary, bullets, and connectors; a tool action begins before an observable plan, checklist, or ordered steps.

**Why it matters:** decomposition makes broad tasks trackable and independently verifiable.

**Limits:** an agent may maintain a private plan, or a concise request may still be conceptually hard. This detector evaluates visible process only.

### `context-loss-reasking`

**Trigger:** two assistant questions have Jaccard similarity of at least 0.66 after lowercasing, tokenization, and stop-word removal.

**Why it matters:** asking for already supplied information wastes a turn and can indicate lost state.

**Limits:** repeated confirmation can be appropriate, and paraphrases with little lexical overlap can be missed. The detector does not claim that the user answered the first question.

### `retrying-same-failing-action`

**Trigger:** after a failed result, the exact normalized tool name and input occur again. JSON inputs are serialized with sorted keys; text inputs collapse whitespace.

**Why it matters:** an unchanged retry rarely gains information unless external state changed.

**Limits:** external state, timing, or nondeterminism can justify the same input. The finding invites that justification rather than forbidding every retry.

### `missing-source-lookup`

**Trigger:** after a code/file-oriented user request, the first mutation precedes any recognized read, list, search, grep, glob, or inspect action.

**Why it matters:** inspecting existing code and tests reduces assumption-driven edits.

**Limits:** source context may have been loaded before the captured transcript. Custom lookup tools with opaque names may not be recognized.

### `tests-only-assert-status`

**Trigger:** a test-writing event contains assertion lines, and every observed assertion references only a status, status code, return code, or exit code.

**Why it matters:** status-only tests can pass while output, state, or side effects are wrong.

**Limits:** assertions split over events or hidden behind helper functions may be missed. A status-only test can be valid when status is the complete contract.

## Failure and verification vocabulary

Tool results with normalized failed statuses or common failure terms count as failures. Explicit passed/success statuses and phrases such as “N passed,” “all tests passed,” or exit status 0 count as successful verification when the event is verification-like. Vocabulary is intentionally finite and covered by tests.

## Privacy behavior

Records are parsed as JSON, then recursively scrubbed before adapter extraction. Reports contain only bounded evidence excerpts rather than all events. Generated kata fixtures contain only events referenced by the selected finding. The original file SHA-256 in a report supports provenance but is not redaction. Paths, project names, and unrecognized personal data can remain; review before sharing.

## Extending the model

New detectors should be deterministic, provide positive and negative tests, document false positives and false negatives, and use exact event evidence. Prefer a missed finding to a vague claim without inspectable support.
