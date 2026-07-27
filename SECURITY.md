# Security policy

## Supported version

Security fixes are applied to the latest released version and the current main development line.

## Local-first threat boundary

FailureKata is designed to process transcripts without network access. The package does not import an HTTP client, send telemetry, check for updates, or call a hosted model. It reads only the local paths supplied to the CLI and writes only requested report, kata, and ledger paths.

Transcript content is untrusted data. Adapters do not execute transcript commands, import paths mentioned by a transcript, evaluate code, or follow instructions embedded in messages. Generated kata tests import only a learner-created `solution.py` when the learner explicitly runs those tests.

## Secret scrubbing limitations

The scrubber handles common token formats, authorization headers, private-key blocks, credential assignments, and values under common sensitive field names. It cannot recognize every proprietary token, encoded secret, personal datum, or secret split over several events. Redaction digests are one-way truncated SHA-256 identifiers used to preserve equality; they should not be treated as suitable protection for low-entropy values.

Recommended handling:

1. Keep original transcripts in a restricted local directory.
2. Sanitize at the transcript source when possible.
3. Inspect reports and generated fixtures before sharing them.
4. Do not use a shared ledger for confidential case notes.
5. Delete local artifacts when they are no longer needed.

## Reporting a vulnerability

Please report vulnerabilities privately to the project maintainers rather than opening a public issue containing exploit details or real transcripts. Include the affected version, reproduction using synthetic data, impact, and a suggested mitigation if available. Never attach a production transcript, credential, or personal data.

Maintainers should acknowledge a report promptly, reproduce it with synthetic data, coordinate a fix and release, and credit the reporter if requested. There is currently no bug-bounty program.
