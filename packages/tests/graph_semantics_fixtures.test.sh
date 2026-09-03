#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
python3 "$root/packages/graph-semantics/tests/run_fixtures.py"
