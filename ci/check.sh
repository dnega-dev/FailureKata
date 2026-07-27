#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1

python3 -m unittest discover -s "$ROOT/tests" -v
python3 -m compileall -q "$ROOT/src" "$ROOT/tests"
