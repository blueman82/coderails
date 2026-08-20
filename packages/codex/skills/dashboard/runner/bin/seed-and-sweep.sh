#!/bin/bash
# On-demand wrapper that seeds due routines and then runs one queue sweep.
# Nothing invokes it automatically; callers that only need to process intents
# already in the queue can use bin/sweeper.sh instead.
#
# This script uses an absolute Node path so it does not depend on the caller's
# PATH. Node 24's built-in TypeScript type-stripping runs
# src/*.ts files directly with no build step (verified in this worktree —
# skills/dashboard/runner has no dist/ output today; bin/sweeper.sh now
# targets src/main.ts the same way).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# The seed step's exit code must never block the sweep below — under
# set -euo pipefail a plain non-zero exit here would abort the script before
# the sweep ever runs. `|| seed_status=$?` catches the exit code without
# tripping -e.
seed_status=0
/opt/homebrew/bin/node "$SCRIPT_DIR/../src/seedMain.ts" || seed_status=$?
if [ "$seed_status" -ne 0 ]; then
    echo "seed step failed (exit $seed_status), continuing to sweep" >&2
fi

exec /opt/homebrew/bin/node "$SCRIPT_DIR/../src/main.ts"
