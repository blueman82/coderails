#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
exec bash "$ROOT/packages/tests/stop_hook_human_escalation.test.sh" "$@"
