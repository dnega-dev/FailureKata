"""Command-line interface for FailureKata."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import __version__
from .adapters import AdapterError, adapter_descriptions
from .detectors import detector_descriptions
from .kata import KataGenerationError, generate_kata
from .ledger import GrowthLedger, LedgerError
from .pipeline import analyze_file
from .reporting import render_json, render_markdown


class CLIError(ValueError):
    pass


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _write_output(text: str, output: Optional[Path]) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _add_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("transcript", type=_path, help="local JSONL transcript path")
    parser.add_argument(
        "--adapter",
        choices=("auto", "generic", "claude-code"),
        default="auto",
        help="input shape (default: detect from first JSONL record)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        metavar="0..1",
        help="omit findings below this confidence",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="failure-kata",
        description="Convert local coding-agent transcript failures into executable practice katas.",
        epilog="FailureKata performs no network operations and never uploads transcript content.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="detect evidence-linked failure patterns")
    _add_input_options(analyze)
    analyze.add_argument("--format", choices=("json", "markdown"), default="json")
    analyze.add_argument("-o", "--output", type=_path, help="write report to this local file")

    generate = commands.add_parser("generate", help="analyze and generate executable kata folders")
    _add_input_options(generate)
    generate.add_argument(
        "--finding",
        action="append",
        default=[],
        metavar="ID_OR_PATTERN",
        help="finding ID or pattern to generate (repeatable; default: highest-confidence finding)",
    )
    generate.add_argument("--all", action="store_true", help="generate a kata for every finding")
    generate.add_argument("-o", "--output", type=_path, required=True, help="parent folder for generated kata(s)")
    generate.add_argument("--force", action="store_true", help="replace files in an existing matching kata folder")
    generate.add_argument("--format", choices=("json", "text"), default="text")

    ledger = commands.add_parser("ledger", help="manage a local spaced-review growth ledger")
    ledger.add_argument(
        "--file",
        type=_path,
        default=Path(".failure-kata-ledger.json"),
        help="ledger JSON path (default: .failure-kata-ledger.json)",
    )
    ledger_commands = ledger.add_subparsers(dest="ledger_command", required=True)
    ledger_add = ledger_commands.add_parser("add", help="add a generated kata")
    ledger_add.add_argument("kata", type=_path, help="generated kata folder")
    ledger_add.add_argument("--supersedes", help="entry ID replaced by this kata")
    ledger_list = ledger_commands.add_parser("list", help="list review entries")
    ledger_list.add_argument("--due", action="store_true", help="show only due, active entries")
    ledger_list.add_argument("--format", choices=("json", "markdown"), default="markdown")
    ledger_review = ledger_commands.add_parser("review", help="record a review outcome")
    ledger_review.add_argument("entry_id")
    ledger_review.add_argument("--outcome", required=True, choices=("again", "hard", "good", "easy"))

    adapters = commands.add_parser("adapters", help="list supported adapters and detectors")
    adapters.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser


def _cmd_analyze(args: argparse.Namespace) -> int:
    if args.output is not None and args.output.resolve() == args.transcript.resolve():
        raise CLIError("report output must not overwrite the input transcript")
    _, _, report = analyze_file(args.transcript, args.adapter, args.min_confidence)
    text = render_json(report) if args.format == "json" else render_markdown(report)
    _write_output(text, args.output)
    return 0


def _select_findings(findings: Sequence[Any], selectors: Sequence[str], select_all: bool) -> List[Any]:
    if not findings:
        raise CLIError("no supported failure pattern was detected")
    if select_all:
        if selectors:
            raise CLIError("--all cannot be combined with --finding")
        return list(findings)
    if not selectors:
        return [findings[0]]
    selected = []
    selected_ids = set()
    for selector in selectors:
        matches = [
            item for item in findings if item.finding_id == selector or item.pattern == selector
        ]
        if not matches:
            raise CLIError("no finding matches %r" % selector)
        for item in matches:
            if item.finding_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item.finding_id)
    return selected


def _cmd_generate(args: argparse.Namespace) -> int:
    transcript, findings, _ = analyze_file(args.transcript, args.adapter, args.min_confidence)
    selected = _select_findings(findings, args.finding, args.all)
    generated = [generate_kata(args.output, item, transcript, force=args.force) for item in selected]
    if args.format == "json":
        sys.stdout.write(json.dumps({"generated": [str(path) for path in generated]}, indent=2, sort_keys=True) + "\n")
    else:
        for path in generated:
            sys.stdout.write("generated %s\n" % path)
    return 0


def _ledger_markdown(entries: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "# FailureKata growth ledger",
        "",
        "| Entry | Pattern | Next review | Interval | Status |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for entry in entries:
        lines.append(
            "| `%s` | `%s` | %s | %s days | %s |"
            % (
                entry.get("entry_id", ""),
                entry.get("pattern", ""),
                entry.get("next_review_on", ""),
                entry.get("interval_days", ""),
                "superseded" if entry.get("superseded_by") else "active",
            )
        )
    if not entries:
        lines.append("| — | — | — | — | No entries |")
    return "\n".join(lines) + "\n"


def _cmd_ledger(args: argparse.Namespace) -> int:
    ledger = GrowthLedger(args.file)
    if args.ledger_command == "add":
        entry = ledger.add_kata(args.kata, supersedes=args.supersedes)
        sys.stdout.write(json.dumps(entry, indent=2, sort_keys=True) + "\n")
        return 0
    if args.ledger_command == "list":
        entries = ledger.list_entries(due_only=args.due)
        if args.format == "json":
            sys.stdout.write(json.dumps({"entries": entries}, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(_ledger_markdown(entries))
        return 0
    if args.ledger_command == "review":
        entry = ledger.review(args.entry_id, args.outcome)
        sys.stdout.write(json.dumps(entry, indent=2, sort_keys=True) + "\n")
        return 0
    raise CLIError("unknown ledger command")


def _cmd_adapters(args: argparse.Namespace) -> int:
    payload = {"adapters": adapter_descriptions(), "detectors": detector_descriptions()}
    if args.format == "json":
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return 0
    lines = ["# FailureKata capabilities", "", "## Adapters", ""]
    lines.extend("- `%s` — %s" % (item["name"], item["description"]) for item in payload["adapters"])
    lines.extend(["", "## Detectors", ""])
    lines.extend("- `%s` — %s" % (item["pattern"], item["description"]) for item in payload["detectors"])
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            return _cmd_analyze(args)
        if args.command == "generate":
            return _cmd_generate(args)
        if args.command == "ledger":
            return _cmd_ledger(args)
        if args.command == "adapters":
            return _cmd_adapters(args)
        raise CLIError("unknown command")
    except (AdapterError, KataGenerationError, LedgerError, CLIError, OSError, ValueError) as exc:
        parser.exit(2, "failure-kata: error: %s\n" % exc)
    return 2
