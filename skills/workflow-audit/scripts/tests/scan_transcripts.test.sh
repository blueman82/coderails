#!/bin/bash
# Unit test for scan_transcripts.sh — transcript scan/extraction into per-session
# tool-use event sequences. See skills/workflow-audit/scripts/scan_transcripts.sh.
set -u
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scan_transcripts.sh"
FIXTURES="$(cd "$(dirname "$0")" && pwd)/fixtures"
fails=0
check() { # desc, expected, actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected: %s\n      actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_contains() { # desc, haystack, needle
  if printf '%s' "$2" | grep -qF "$3"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected to contain: %s\n      actual: %s\n' "$1" "$3" "$2"; fails=$((fails+1)); fi
}
check_not_contains() { # desc, haystack, needle
  if printf '%s' "$2" | grep -qF "$3"; then
    printf 'FAIL - %s\n      must NOT contain: %s\n      actual: %s\n' "$1" "$3" "$2"; fails=$((fails+1))
  else printf 'ok   - %s\n' "$1"
  fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# ── Corpus layout: $TMP/<project-slug>/<uuid>.jsonl ─────────────────────────
mkdir -p "$TMP/proj-small" "$TMP/proj-edge" "$TMP/proj-sentinel" "$TMP/proj-corrupt" "$TMP/proj-clean" "$TMP/proj-own"
cp "$FIXTURES/fixture-small.jsonl"    "$TMP/proj-small/11111111-1111-1111-1111-111111111111.jsonl"
cp "$FIXTURES/fixture-edge.jsonl"     "$TMP/proj-edge/22222222-2222-2222-2222-222222222222.jsonl"
cp "$FIXTURES/fixture-sentinel.jsonl" "$TMP/proj-sentinel/33333333-3333-3333-3333-333333333333.jsonl"

# ── 1. All-record-types fixture parses to the expected event sequence ──────
OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-small --days 36500)
EVENTS=$(printf '%s' "$OUT" | jq -c '.events')
EXPECTED='[{"tool":"Bash","head":"git log"},{"tool":"Read"},{"tool":"Skill","head":"prime"},{"tool":"Agent","head":"general-purpose"}]'
check "all-record-types fixture -> expected event sequence" "$EXPECTED" "$EVENTS"
check "event_count matches events length" "4" "$(printf '%s' "$OUT" | jq -r '.event_count')"
check "session_id == uuid basename sans .jsonl" "11111111-1111-1111-1111-111111111111" "$(printf '%s' "$OUT" | jq -r '.session_id')"
check "project_slug == directory name" "proj-small" "$(printf '%s' "$OUT" | jq -r '.project_slug')"

# ── 2. Bare-string content (user and assistant) doesn't crash ───────────────
EDGE_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-edge --days 36500 2>"$TMP/edge.err")
EDGE_RC=$?
check "bare-string content fixture -> script exits 0" "0" "$EDGE_RC"
EDGE_EVENTS=$(printf '%s' "$EDGE_OUT" | jq -c '.events')
EDGE_EXPECTED='[{"tool":"Bash","head":"npm test"},{"tool":"mcp__claude-in-chrome__navigate"}]'
check "bare-string content fixture -> correct events despite bare-string content records" "$EDGE_EXPECTED" "$EDGE_EVENTS"

# ── 3. last-prompt record is skipped (never read, never crashes) ────────────
check "last-prompt fixture -> event_count excludes it" "2" "$(printf '%s' "$EDGE_OUT" | jq -r '.event_count')"

# ── 4. Sentinel absent from scan output ─────────────────────────────────────
SENTINEL_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-sentinel --days 36500)
check_not_contains "sentinel string never appears in scan output" "$SENTINEL_OUT" "SENTINEL_sk_live_99xyz"
check_contains "sentinel fixture Bash head is still 'curl -H' (two tokens only)" "$SENTINEL_OUT" '"head":"curl -H"'
# Confirm the fixture genuinely contains the sentinel (negative-control sanity: input isn't empty).
check_contains "sentinel fixture itself contains the sentinel (input sanity)" "$(cat "$FIXTURES/fixture-sentinel.jsonl")" "SENTINEL_sk_live_99xyz"

# ── 5. Corrupt line yields distinct jq_parse_error, not folded into zero-events ─
cp "$FIXTURES/fixture-small.jsonl" "$TMP/proj-corrupt/44444444-4444-4444-4444-444444444444.jsonl"
printf '{ this is not valid json\n' >> "$TMP/proj-corrupt/44444444-4444-4444-4444-444444444444.jsonl"
CORRUPT_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-corrupt --days 36500 2>&1 >/dev/null)
check_contains "corrupt line -> jq_parse_error on stderr" "$CORRUPT_ERR" "jq_parse_error:"

# Negative control: a clean fixture must NOT emit jq_parse_error (detector fires only on real corruption).
cp "$FIXTURES/fixture-small.jsonl" "$TMP/proj-clean/55555555-5555-5555-5555-555555555555.jsonl"
CLEAN_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-clean --days 36500 2>&1 >/dev/null)
check_not_contains "clean fixture -> no jq_parse_error (negative control)" "$CLEAN_ERR" "jq_parse_error:"

# A corrupt trailing line must still surface jq_parse_error while the valid
# events earlier in the SAME file are not discarded (per-line isolation, not
# whole-file slurp failure).
CORRUPT_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-corrupt --days 36500 2>/dev/null)
check "corrupt trailing line -> valid events from same file still emitted" "4" "$(printf '%s' "$CORRUPT_OUT" | jq -r '.event_count')"

# ── 5b. Non-string head fields (crafted/malformed records) never leak raw JSON
#     to stdout — regression guard for the privacy-boundary type-coercion fix.
mkdir -p "$TMP/proj-nonstring"
NONSTRING_FILE="$TMP/proj-nonstring/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"
{
  printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Skill","input":{"skill":{"secret":"should_not_leak"}}}]},"timestamp":"2026-07-05T00:00:00Z"}\n'
  printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Agent","input":{"subagent_type":["leaked","tokens"]}}]},"timestamp":"2026-07-05T00:00:01Z"}\n'
  printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":{"nested":"should_not_leak_either"}}}]},"timestamp":"2026-07-05T00:00:02Z"}\n'
} > "$NONSTRING_FILE"
NONSTRING_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-nonstring --days 36500)
check_not_contains "non-string Skill input never leaks raw object" "$NONSTRING_OUT" "should_not_leak"
check_not_contains "non-string Agent input never leaks raw array" "$NONSTRING_OUT" "leaked"
check_not_contains "non-string Bash command never leaks raw object" "$NONSTRING_OUT" "should_not_leak_either"

# ── 6. --last-sessions ordering uses in-file timestamps, NOT file mtime ─────
mkdir -p "$TMP/proj-order"
OLDER="$TMP/proj-order/66666666-6666-6666-6666-666666666666.jsonl"
NEWER="$TMP/proj-order/77777777-7777-7777-7777-777777777777.jsonl"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read"}]},"timestamp":"2020-01-01T00:00:00Z"}\n' > "$OLDER"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write"}]},"timestamp":"2026-01-01T00:00:00Z"}\n' > "$NEWER"
# Bump the OLDER file's mtime to be newest on disk — a mtime-based implementation
# would now (wrongly) pick it first under --last-sessions 1.
touch "$OLDER"
ORDER_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-order --last-sessions 1)
check "timestamp-based recency survives an mtime bump (not mtime-based)" \
  "77777777-7777-7777-7777-777777777777" "$(printf '%s' "$ORDER_OUT" | jq -r '.session_id')"

# ── 7. Own-session exclusion ─────────────────────────────────────────────────
mkdir -p "$TMP/proj-own"
cp "$FIXTURES/fixture-small.jsonl" "$TMP/proj-own/OWNSESSION.jsonl"
OWN_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP" CLAUDE_CODE_SESSION_ID="OWNSESSION" bash "$SCRIPT" --project proj-own --days 36500 2>&1 >/dev/null)
OWN_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" CLAUDE_CODE_SESSION_ID="OWNSESSION" bash "$SCRIPT" --project proj-own --days 36500 2>/dev/null)
check "own session excluded -> no output for that session" "" "$OWN_OUT"
check_contains "own session excluded -> stderr names it skipped_own_session" "$OWN_ERR" "skipped_own_session:"

# ── 8. --project narrowing: proj-edge scan must not include proj-small's session,
#    AND must still include proj-edge's own session (paired positive assertion —
#    an unpaired negative-only check would pass vacuously if the filter matched
#    zero directories).
NARROW_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-edge --days 36500)
check_not_contains "--project narrowing excludes other projects' sessions" "$NARROW_OUT" "11111111-1111-1111-1111-111111111111"
check_contains "--project narrowing still includes its own project's session (not vacuous)" "$NARROW_OUT" "22222222-2222-2222-2222-222222222222"

# ── 9. --all-projects (default) scans across all project dirs ───────────────
ALL_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --all-projects --days 36500)
check_contains "--all-projects includes proj-small's session" "$ALL_OUT" "11111111-1111-1111-1111-111111111111"
check_contains "--all-projects includes proj-edge's session" "$ALL_OUT" "22222222-2222-2222-2222-222222222222"

# ── 10. --help exits 0 and prints usage ──────────────────────────────────────
HELP_OUT=$(bash "$SCRIPT" --help 2>&1)
HELP_RC=$?
check "--help exits 0" "0" "$HELP_RC"
check_contains "--help output mentions WORKFLOW_AUDIT_ROOT" "$HELP_OUT" "WORKFLOW_AUDIT_ROOT"

# ── 11. Head extraction exactness: Bash = first two whitespace tokens only ──
mkdir -p "$TMP/proj-heads"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"   git    status --short   "}}]},"timestamp":"2026-07-04T00:00:00Z"}\n' > "$TMP/proj-heads/88888888-8888-8888-8888-888888888888.jsonl"
HEADS_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-heads --days 36500)
check_contains "Bash head is exactly first two tokens, whitespace-collapsed" "$HEADS_OUT" '"head":"git status"'

# ── 12b. --days cutoff actually excludes old sessions (default path exercised) ─
mkdir -p "$TMP/proj-days"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read"}]},"timestamp":"2020-01-01T00:00:00Z"}\n' > "$TMP/proj-days/99999999-9999-9999-9999-999999999999.jsonl"
DAYS_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-days --days 14)
check "old session (2020) excluded by default --days 14 cutoff" "" "$DAYS_OUT"
DAYS_OUT_WIDE=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-days --days 36500)
check_contains "same old session included when --days is wide enough" "$DAYS_OUT_WIDE" "99999999-9999-9999-9999-999999999999"

# ── 12. Sanity stderr line prints file count + MB before scanning ───────────
SANITY_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-small --days 36500 2>&1 >/dev/null)
check_contains "sanity stderr line present (file count)" "$SANITY_ERR" "file"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
