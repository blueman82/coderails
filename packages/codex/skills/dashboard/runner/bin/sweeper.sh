#!/bin/bash
# On-demand wrapper for one queue sweep. It uses an absolute Node path so it
# does not depend on the caller's PATH.
#
# Runs src/main.ts directly via Node 24's built-in TypeScript type-stripping
# (no build step) — matches bin/seed-and-sweep.sh's proven-working pattern.
# The previous ../dist/main.js target never existed (no build step produces
# dist/, and dist/ is gitignored), so that entrypoint failed with
# MODULE_NOT_FOUND.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /opt/homebrew/bin/node "$SCRIPT_DIR/../src/main.ts"
