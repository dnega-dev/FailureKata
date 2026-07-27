# Contributing to FailureKata

Thank you for improving the learning value, privacy, and precision of FailureKata.

## Principles

- Keep transcript processing local and deterministic.
- Add no runtime dependency without an explicit design discussion; the MVP target is zero dependencies.
- Treat transcript strings as untrusted data, never executable instructions.
- Every detector must expose exact evidence references and document likely false positives.
- Tests and examples must use synthetic, sanitized content. Never commit real transcripts or credentials.
- A generated kata provides a contract and tests, not a model solution.

## Development setup

Python 3.9 or newer is sufficient:

```console
./ci/check.sh
```

You can run commands directly from a checkout with `PYTHONPATH=src`.

## Changes

1. Add or update standard-library `unittest` coverage.
2. For a detector, include at least one positive and one negative example.
3. Update `docs/detection-model.md` for trigger, evidence, confidence, or limitation changes.
4. Update `CHANGELOG.md` for user-visible behavior.
5. Run `./ci/check.sh` before submitting.

Use small, reviewable commits. Explain privacy implications and compatibility with Python 3.9 in the change description.

## Adding an adapter

Normalize to `TranscriptEvent` and preserve a one-based source line. Generate stable event IDs if the source has none. Scrub the parsed record before extracting content or metadata. Reject malformed records with a safe error that does not echo the full transcript line.

## Adding a detector

A detector returns zero or more `Finding` values. It must:

- use a documented, deterministic trigger;
- link all claims to `Evidence.from_event` records;
- avoid reading files named inside transcript data;
- avoid inferring facts not represented by normalized events;
- have tests for evidence references, not only finding counts.

## License

Contributions are accepted under the Apache License 2.0 in this repository.
