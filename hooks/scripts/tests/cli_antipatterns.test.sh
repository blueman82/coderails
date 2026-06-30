#!/bin/bash
# Repo-wide lint for statically-catchable CLI antipattern bug classes.
# These three patterns all shipped and were fixed in PR #84; this test guards against
# re-introduction across ANY command or script file in the repo.
#
# Bug class 1: gh api -f key=@file — -f posts the LITERAL string "@file"; only -F reads it.
# Bug class 2: bare /pr-review-toolkit:review-pr all in workflow.md — fails the per-PR gate.
# Bug class 3: jq `| first | {url:` without select(. != null) — produces {url:null,...} on no-match.
#
# Each assertion section has two parts:
#   A) self-test: feeds a known-bad string to a temp file and confirms the grep FIRES (exit 0).
#   B) repo scan: greps real files and confirms ZERO violations (hit counter stays 0).
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s  actual exit: %s\n' "$1" "$2" "$3"
    fails=$((fails+1)); fi
}

# Collect all command and script source files to scan.
# We exclude the test directory itself to avoid false-positives from self-test fixtures.
# Use a newline-delimited string (compatible with bash 3.2 on macOS — no mapfile).
SCAN_FILES_LIST=$(
  find "$REPO_ROOT/commands" -name '*.md' -type f
  find "$REPO_ROOT/scripts" -name '*.sh' -type f
)

# ─── Bug class 1: gh api -f key=@ (raw-field with file sigil — literal-string trap) ────────
#
# The pattern -f <identifier>=@ tells gh to post the LITERAL string "@<something>" as the
# field value.  The correct form is -F which reads the file.  The pattern is grep-detectable.
# We check for `-f <word>=@` (a word boundary before =@ keeps false-positives low).

BAD1_FILE="$TMP/bad_gh_raw_field.sh"
printf '%s\n' 'gh api graphql -f body=@/tmp/comment.md' > "$BAD1_FILE"

grep -qE -- '-f [a-zA-Z_]+=@' "$BAD1_FILE"
check "self-test: -f key=@ pattern FIRES on bad input (assertion not vacuous)" 0 $?

# Repo scan: no command or script file may contain -f <word>=@ in a gh invocation.
bad1_hit=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if grep -nE -- '-f [a-zA-Z_]+=@' "$f"; then
    printf '  ^^ gh raw-field file-read trap in: %s\n' "$f"
    bad1_hit=1
  fi
done <<< "$SCAN_FILES_LIST"
check "repo scan: no -f key=@ (gh raw-field file-read trap) in command/script files" 0 $((bad1_hit))

# ─── Bug class 2: bare 'review-pr all' in workflow.md (fails the per-PR hook gate) ──────────
#
# The enforce_pr_workflow.sh hook validates that review-pr invocations start with a PR number.
# A bare "review-pr all" argument skips that check incorrectly.  Scoped to workflow.md because
# that is the authoritative invocation document for this repo's PR workflow.

WORKFLOW_FILE="$REPO_ROOT/commands/workflow.md"
BAD2_FILE="$TMP/bad_workflow.md"
printf '%s\n' 'Run `/pr-review-toolkit:review-pr all` to review.' > "$BAD2_FILE"

grep -qF '`/pr-review-toolkit:review-pr all`' "$BAD2_FILE"
check "self-test: bare 'review-pr all' pattern FIRES on bad input (assertion not vacuous)" 0 $?

grep -qF '`/pr-review-toolkit:review-pr all`' "$WORKFLOW_FILE"
check "repo scan: workflow.md does NOT contain bare '/pr-review-toolkit:review-pr all'" 1 $?

# ─── Bug class 3: jq `| first | {url:` without select(. != null) guard ──────────────────────
#
# When a jq filter produces an empty array, `first` yields `null`.  Piping null into an object
# projection `{url:.html_url,...}` produces a non-empty JSON object with null fields rather
# than empty output — causing downstream bash checks to incorrectly conclude a match was found.
#
# Narrow heuristic: any line containing `| first | {url:` is the known-dangerous idiom.
# A line with that idiom MUST also contain `select(. != null)` between `first` and the projection.
# We check: grep finds the projection idiom on the same line, and that same line also has the guard.
# Limitation: this catches only the exact `{url:` projection form; other projections after first
# would not be caught.  This is intentional — narrow enough to avoid false-positives.

BAD3_FILE="$TMP/bad_jq_first.sh"
# This line has first | {url: but NO select guard — the dangerous form.
printf '%s\n' '--jq "[.[] | select(.body | startswith(X))] | first | {url:.html_url,id:.id}"' > "$BAD3_FILE"

grep -qE '\| first \|.*\{url:' "$BAD3_FILE"
check "self-test: '| first | {url:' pattern FIRES on bad input (assertion not vacuous)" 0 $?

# Self-test part 2: confirm the guard check correctly identifies the ABSENCE of select(. != null).
grep -E '\| first \|.*\{url:' "$BAD3_FILE" | grep -qF 'select(. != null)'
check "self-test: bad input correctly fails the select-guard check (guard is absent)" 1 $?

# Repo scan: any line with | first | {url: MUST also have select(. != null).
bad3_hit=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  # Find lines with the dangerous idiom; skip if grep found nothing.
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if ! printf '%s' "$line" | grep -qF 'select(. != null)'; then
      printf '%s: %s\n' "$f" "$line"
      printf '  ^^ jq first|{url: projection without select(. != null) guard\n'
      bad3_hit=1
    fi
  done <<< "$(grep -nE '\| first \|.*\{url:' "$f" 2>/dev/null)"
done <<< "$SCAN_FILES_LIST"
check "repo scan: all '| first | {url:' projections have select(. != null) guard" 0 $((bad3_hit))

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
