#!/bin/bash
# Behavioural tests for scripts/post_review.sh
# Tests: validate_summary grammar + write_cache behaviour.
set -u
SCRIPT="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/post_review.sh"
source "$SCRIPT"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_str() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_val() { # desc expected actual
  check_str "$1" "$2" "$3"
}

# ─── Task 1: validate_summary ─────────────────────────────────────────────────

# (a) ## No findings → pass
BODY_A="$TMP/body_a.md"
printf '## No findings\n' > "$BODY_A"
post_review::validate_summary "$BODY_A"
check "validate: '## No findings' → exit 0" 0 $?

# (b) All three headings each with a bullet → pass
BODY_B="$TMP/body_b.md"
cat > "$BODY_B" <<'BODY'
## Critical
- something critical

## Important
- something important

## Suggestions
- a suggestion
BODY
post_review::validate_summary "$BODY_B"
check "validate: all three headings with bullets → exit 0" 0 $?

# (c) All three headings, one section with 'None' → pass
BODY_C="$TMP/body_c.md"
cat > "$BODY_C" <<'BODY'
## Critical
None

## Important
- something important

## Suggestions
None
BODY
post_review::validate_summary "$BODY_C"
check "validate: sections with 'None' → exit 0" 0 $?

# (d) ## Critical with empty section → fail
BODY_D="$TMP/body_d.md"
cat > "$BODY_D" <<'BODY'
## Critical

## Important
- important item

## Suggestions
- suggestion
BODY
post_review::validate_summary "$BODY_D" 2>/dev/null
check "validate: ## Critical with empty section → exit 1" 1 $?

# (e) One-line 'review done' → fail
BODY_E="$TMP/body_e.md"
printf 'review done\n' > "$BODY_E"
post_review::validate_summary "$BODY_E" 2>/dev/null
check "validate: one-line 'review done' → exit 1" 1 $?

# (f) Missing ## Suggestions → fail
BODY_F="$TMP/body_f.md"
cat > "$BODY_F" <<'BODY'
## Critical
- critical item

## Important
- important item
BODY
post_review::validate_summary "$BODY_F" 2>/dev/null
check "validate: missing ## Suggestions → exit 1" 1 $?

# ─── Task 2: write_cache ──────────────────────────────────────────────────────

# Build a minimal valid progress.json stub
PROG="$TMP/progress.json"
cat > "$PROG" <<'JSON'
{
  "schema_version": 1,
  "session_id": "sess-test",
  "status": "in-progress",
  "created": "2026-06-30T00:00:00Z",
  "authorising_prompt_raw": "test",
  "work": [],
  "review": {
    "ran": false,
    "pr": null,
    "head_sha": null,
    "summary_posted": false,
    "summary_url": null,
    "summary_author": null,
    "posted_at": null
  }
}
JSON

post_review::write_cache "$PROG" 42 "deadbeef" "https://github.com/x/y/issues/42#issuecomment-1" "reviewer-bot" "2026-06-30T10:00:00Z"

check "write_cache: exits 0 on existing file" 0 $?
check_val "write_cache: .review.ran == true" "true" "$(jq -r '.review.ran' "$PROG")"
check_val "write_cache: .review.summary_posted == true" "true" "$(jq -r '.review.summary_posted' "$PROG")"
check_val "write_cache: .review.pr == 42" "42" "$(jq -r '.review.pr' "$PROG")"
check_val "write_cache: .review.head_sha == deadbeef" "deadbeef" "$(jq -r '.review.head_sha' "$PROG")"
check_val "write_cache: .review.summary_url captured" "https://github.com/x/y/issues/42#issuecomment-1" "$(jq -r '.review.summary_url' "$PROG")"
check_val "write_cache: .review.summary_author captured" "reviewer-bot" "$(jq -r '.review.summary_author' "$PROG")"
check_val "write_cache: .review.posted_at captured" "2026-06-30T10:00:00Z" "$(jq -r '.review.posted_at' "$PROG")"
check_val "write_cache: base .status unchanged" "in-progress" "$(jq -r '.status' "$PROG")"
check_val "write_cache: base .session_id unchanged" "sess-test" "$(jq -r '.session_id' "$PROG")"

# write_cache on non-existent path → warns to stderr, exits 0, creates no file
NONEXIST="$TMP/does/not/exist/progress.json"
stderr_out=$(post_review::write_cache "$NONEXIST" 42 "sha" "url" "author" "2026-06-30T00:00:00Z" 2>&1 1>/dev/null)
check "write_cache: non-existent path → exit 0" 0 $?
[[ -f "$NONEXIST" ]]
check "write_cache: non-existent path → does not create file" 1 $?
[[ -n "$stderr_out" ]]
check "write_cache: non-existent path → warns to stderr" 0 $?

# ─── Test A: write_cache jq-failure path ─────────────────────────────────────
# Feed a corrupted/non-JSON progress.json to write_cache; assert:
#   (a) exit 1
#   (b) original file content unchanged
#   (c) no leftover .tmp file

CORRUPT="$TMP/corrupt_progress.json"
printf 'THIS IS NOT JSON }{' > "$CORRUPT"
CORRUPT_ORIGINAL=$(cat "$CORRUPT")
CORRUPT_TMP="${CORRUPT}.tmp"

post_review::write_cache "$CORRUPT" 42 "deadbeef" "https://x" "bot" "2026-06-30T00:00:00Z" 2>/dev/null
check "write_cache: jq-failure → exit 1" 1 $?
check_str "write_cache: jq-failure → original file unchanged" "$CORRUPT_ORIGINAL" "$(cat "$CORRUPT")"
[[ -f "$CORRUPT_TMP" ]]
check "write_cache: jq-failure → no leftover .tmp file" 1 $?

# ─── Test B: validate_summary missing-file path ───────────────────────────────
# Call validate_summary with a path that does not exist; assert exit 1 and
# a "file not found" message on stderr.

MISSING_FILE="$TMP/does_not_exist_at_all.md"
stderr_missing=$(post_review::validate_summary "$MISSING_FILE" 2>&1)
check "validate_summary: missing file → exit 1" 1 $?
[[ "$stderr_missing" == *"not found"* ]]
check "validate_summary: missing file → stderr contains 'not found'" 0 $?

# ─── Fix 5: ambiguous ## No findings + structured headings → exit 1 ──────────
BODY_AMB="$TMP/body_ambiguous.md"
cat > "$BODY_AMB" <<'BODY'
## No findings

## Critical
- something critical
BODY
post_review::validate_summary "$BODY_AMB" 2>/dev/null
check "validate_summary: ambiguous '## No findings' + structured headings → exit 1" 1 $?

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
