#!/bin/bash
# Aggregate test runner — discovers all *.test.sh in this directory and runs each.
set -u
cd "$(dirname "$0")"

fails=0
total=0

for test_file in *.test.sh; do
  [ -f "$test_file" ] || continue
  total=$((total + 1))
  printf '\n=== %s ===\n' "$test_file"
  if bash "$test_file"; then
    printf 'OK\n'
  else
    rc=$?
    fails=$((fails + 1))
    printf 'FAILED (exit %d)\n' "$rc"
  fi
done

if [ "$total" -eq 0 ]; then
  printf 'run_all: ERROR — no *.test.sh files found in %s\n' "$(pwd)" >&2
  exit 1
fi

printf '\n--- run_all: %d/%d suites passed ---\n' "$((total - fails))" "$total"

[ "$fails" -eq 0 ] && exit 0 || exit 1
