# FailureKata

FailureKata is a local-first, zero-runtime-dependency Python 3.9+ tool that turns coding-agent transcript failures into executable practice exercises. It normalizes JSONL events, scrubs likely credentials in memory, detects evidence-backed failure patterns, and generates a standalone kata with deterministic `unittest` tests.

> **Privacy boundary:** FailureKata contains no network client and does not upload transcripts. Input, reports, generated fixtures, and the review ledger stay at paths you choose. Redaction is defense in depth, not a guarantee; inspect generated artifacts before sharing them.

## What the MVP includes

- Generic JSONL and simplified Claude Code JSONL adapters.
- Deterministic scrubbing for common API keys, bearer/basic tokens, JWTs, private keys, credential assignments, and sensitive object fields.
- Eight transparent detectors:
  - repeated failed attempts;
  - skipped verification;
  - premature completion;
  - weak decomposition;
  - context loss / re-asking;
  - retrying the same failing action;
  - missing source lookup;
  - tests that only assert status.
- Finding records with event ID, normalized event index, original JSONL line, field, excerpt, and content SHA-256.
- JSON and Markdown reports.
- Kata folders with a brief, two sanitized fixtures, hints, solution contract (never a solution), metadata, and executable `unittest` tests.
- A local growth ledger with supersession links and spaced-review dates.

Detectors are reviewable heuristics, not a judgment of intent or a proof that work was poor. See [the detection model](docs/detection-model.md).

## Quick start

No install is required from a checkout:

```console
PYTHONPATH=src python -m failure_kata adapters
PYTHONPATH=src python -m failure_kata analyze examples/transcripts/generic_failure.jsonl --format markdown
PYTHONPATH=src python -m failure_kata analyze examples/transcripts/claude_code_failure.jsonl --format json -o report.json
```

Or install locally (no runtime packages are required):

```console
python -m pip install -e .
failure-kata --version
```

### Analyze

```console
failure-kata analyze TRANSCRIPT.jsonl \
  --adapter auto \
  --min-confidence 0.75 \
  --format json \
  --output analysis.json
```

`--adapter` accepts `auto`, `generic`, or `claude-code`. Auto-detection only examines the first non-empty JSON object. An invalid JSONL line produces a source-line-specific error.

### Generate a kata

Generate the highest-confidence finding:

```console
failure-kata generate examples/transcripts/generic_failure.jsonl -o .generated
```

Select one pattern or exact finding ID, or generate all findings:

```console
failure-kata generate transcript.jsonl -o .generated --finding skipped-verification
failure-kata generate transcript.jsonl -o .generated --finding skipped-verification-0123456789ab
failure-kata generate transcript.jsonl -o .generated --all --format json
```

A generated folder contains:

```text
README.md
SOLUTION_CONTRACT.md
HINTS.md
metadata.json
fixtures/events.json
fixtures/scenario.json
tests/test_kata.py
```

It intentionally omits `solution.py`. In the kata directory, create it according to `SOLUTION_CONTRACT.md`, then run:

```console
python -m unittest discover -s tests -v
```

### Keep a growth ledger

```console
failure-kata ledger --file learning.json add .generated/KATA_FOLDER
failure-kata ledger --file learning.json list --due
failure-kata ledger --file learning.json review ENTRY_ID --outcome good
```

When a better kata replaces an earlier one:

```console
failure-kata ledger --file learning.json add NEW_KATA --supersedes OLD_ENTRY_ID
```

The old entry receives `superseded_by`; the new entry receives `supersedes`. Review outcomes (`again`, `hard`, `good`, `easy`) update deterministic review intervals and `next_review_on`.

## Generic JSONL shape

One object is required per non-empty line. The adapter recognizes common aliases:

```json
{"id":"m1","type":"message","role":"user","content":"Fix the parser"}
{"id":"c1","type":"tool_call","role":"assistant","name":"edit_file","content":{"path":"parser.py"}}
{"id":"r1","type":"tool_result","role":"tool","status":"success","content":"updated"}
```

`content` may be a string or any JSON value. IDs default to `line-N`. Unknown fields are retained as scrubbed metadata. See the example transcripts for the simplified Claude Code content-block shape.

## Security and data handling

- No telemetry, HTTP dependency, update checker, or cloud integration exists.
- Scrubbing occurs before adapters create normalized events and before detector excerpts or kata fixtures are produced.
- Reports include the input file path and a SHA-256 of the original file, but not the full normalized transcript.
- Kata fixtures include only events referenced by the chosen finding, not the entire transcript.
- Secret recognition is necessarily incomplete. Use restricted local permissions and review artifacts before sharing.

Read [SECURITY.md](SECURITY.md) for threat boundaries and reporting.

## Development

```console
./ci/check.sh
```

The check runs the full standard-library `unittest` suite and `compileall`. The project intentionally has no runtime or test dependencies. Contributor guidance is in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
