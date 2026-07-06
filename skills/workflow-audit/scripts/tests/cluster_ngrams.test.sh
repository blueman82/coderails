#!/bin/bash
# Unit test for cluster_ngrams.sh — n-gram clustering over scan_transcripts.sh's
# per-session JSONL stream. See skills/workflow-audit/scripts/cluster_ngrams.sh.
set -u
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/cluster_ngrams.sh"
SCAN_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scan_transcripts.sh"
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

FIXTURE_3S="$FIXTURES/cluster-3sessions.jsonl"

# ── 1. Hand-computed fixture (3 sessions share a bigram AND a trigram) ──────
OUT=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 3)
RC=$?
check "3-session fixture -> exit 0" "0" "$RC"
check "3-session fixture -> scanned_sessions == 4" "4" "$(printf '%s' "$OUT" | jq -r '.scanned_sessions')"

TRIGRAM_CLUSTER=$(printf '%s' "$OUT" | jq -c '.clusters[] | select(.n == 3)')
check "trigram cluster ngram is exact" '["Bash:git log","Bash:git push","Skill:prime"]' "$(printf '%s' "$TRIGRAM_CLUSTER" | jq -c '.ngram')"
check "trigram cluster count == 3" "3" "$(printf '%s' "$TRIGRAM_CLUSTER" | jq -r '.count')"
check "trigram cluster sessions == exact sorted list of 3 distinct session ids" \
  '["11111111-1111-1111-1111-111111111111","22222222-2222-2222-2222-222222222222","33333333-3333-3333-3333-333333333333"]' \
  "$(printf '%s' "$TRIGRAM_CLUSTER" | jq -c '.sessions | sort')"

BIGRAM_A=$(printf '%s' "$OUT" | jq -c '.clusters[] | select(.n == 2 and .ngram == ["Bash:git log","Bash:git push"])')
check "bigram A (git log -> git push) count == 3" "3" "$(printf '%s' "$BIGRAM_A" | jq -r '.count')"
BIGRAM_B=$(printf '%s' "$OUT" | jq -c '.clusters[] | select(.n == 2 and .ngram == ["Bash:git push","Skill:prime"])')
check "bigram B (git push -> prime) count == 3" "3" "$(printf '%s' "$BIGRAM_B" | jq -r '.count')"

# Below-threshold: session 4's [Read, Write] bigram appears in only 1 session (< 3).
check_not_contains "below-threshold [Read,Write] bigram is NOT listed as a cluster" \
  "$(printf '%s' "$OUT" | jq -c '.clusters')" '"Read","Write"'
check "below_threshold diagnostics counts the excluded [Read,Write] n-gram (>=1)" "true" \
  "$(printf '%s' "$OUT" | jq -r '.diagnostics.below_threshold >= 1')"

# Sort order: count desc, then n desc -> the n=3 cluster must sort before the n=2 clusters.
FIRST_N=$(printf '%s' "$OUT" | jq -r '.clusters[0].n')
check "clusters sorted count desc, n desc -> first cluster is the trigram (n=3)" "3" "$FIRST_N"

# ── 2. No-repeats input -> clean empty-clusters result, exit 0 ─────────────
NOREPEAT_IN='{"session_id":"s1","project_slug":"p","event_count":2,"events":[{"tool":"Read"},{"tool":"Write"}]}'
NOREPEAT_OUT=$(printf '%s\n' "$NOREPEAT_IN" | bash "$SCRIPT" --min-sessions 3)
NOREPEAT_RC=$?
check "no-repeats input -> exit 0" "0" "$NOREPEAT_RC"
check "no-repeats input -> empty clusters array" "[]" "$(printf '%s' "$NOREPEAT_OUT" | jq -c '.clusters')"
# Negative control: the real repeats fixture must NOT also produce empty clusters.
check "negative control: repeats fixture does NOT yield empty clusters" "false" \
  "$(printf '%s' "$OUT" | jq -r '.clusters | length == 0')"

# ── 3. Malformed stdin line -> jq_parse_error:<line-no>, remaining lines processed ──
MALFORMED_IN=$(printf '{ not valid json\n%s' "$(cat "$FIXTURE_3S")")
MALFORMED_ERR=$(printf '%s\n' "$MALFORMED_IN" | bash "$SCRIPT" --min-sessions 3 2>&1 >/dev/null)
check_contains "malformed first line -> jq_parse_error:1 on stderr" "$MALFORMED_ERR" "jq_parse_error:1"
MALFORMED_OUT=$(printf '%s\n' "$MALFORMED_IN" | bash "$SCRIPT" --min-sessions 3 2>/dev/null)
check "malformed line -> remaining valid lines still scanned (scanned_sessions == 4)" "4" \
  "$(printf '%s' "$MALFORMED_OUT" | jq -r '.scanned_sessions')"
check "malformed line -> remaining valid lines still cluster (trigram count == 3)" "3" \
  "$(printf '%s' "$MALFORMED_OUT" | jq -r '.clusters[] | select(.n==3) | .count')"

# Negative control: a clean stream must NOT emit jq_parse_error.
CLEAN_ERR=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 3 2>&1 >/dev/null)
check_not_contains "clean input -> no jq_parse_error (negative control)" "$CLEAN_ERR" "jq_parse_error:"

# ── 4. --min-sessions honoured ───────────────────────────────────────────────
MINSESS2_OUT=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 4)
check "min-sessions 4 (higher than any support) -> no clusters" "[]" "$(printf '%s' "$MINSESS2_OUT" | jq -c '.clusters')"
DEFAULT_OUT=$(cat "$FIXTURE_3S" | bash "$SCRIPT")
check "default --min-sessions is 3 -> trigram cluster present" "3" \
  "$(printf '%s' "$DEFAULT_OUT" | jq -r '.clusters[] | select(.n==3) | .count')"

# ── 5. --top caps output and notes truncation in diagnostics ───────────────
TOP_OUT=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 3 --top 1)
check "top 1 -> exactly 1 cluster returned" "1" "$(printf '%s' "$TOP_OUT" | jq -r '.clusters | length')"
check "top 1 -> diagnostics notes truncation" "true" "$(printf '%s' "$TOP_OUT" | jq -r '.diagnostics.truncated == true')"
NOTOP_OUT=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 3)
check "no --top (below default cap) -> diagnostics does not claim truncation" "false" \
  "$(printf '%s' "$NOTOP_OUT" | jq -r '.diagnostics.truncated // false')"
# --top 0 is nonsensical ("give me the top zero") -> floor to 1 rather than
# silently reporting empty clusters with truncated:true (misleading diagnostic).
TOP0_OUT=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 3 --top 0)
check "--top 0 is floored to 1 (not zero clusters)" "1" "$(printf '%s' "$TOP0_OUT" | jq -r '.clusters | length')"

# ── 6. Ordering is stable across repeated runs ──────────────────────────────
RUN1=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 3 | jq -c '[.clusters[].ngram]')
RUN2=$(cat "$FIXTURE_3S" | bash "$SCRIPT" --min-sessions 3 | jq -c '[.clusters[].ngram]')
check "cluster ordering stable across repeated runs" "$RUN1" "$RUN2"

# ── 7. A session id appearing twice in input doesn't double-count distinct support ──
DUPSESSION_IN=$(printf '%s\n%s\n%s\n' \
  '{"session_id":"dup-1","project_slug":"p","event_count":2,"events":[{"tool":"Bash","head":"git log"},{"tool":"Bash","head":"git push"}]}' \
  '{"session_id":"dup-1","project_slug":"p","event_count":2,"events":[{"tool":"Bash","head":"git log"},{"tool":"Bash","head":"git push"}]}' \
  '{"session_id":"dup-2","project_slug":"p","event_count":2,"events":[{"tool":"Bash","head":"git log"},{"tool":"Bash","head":"git push"}]}')
DUPSESSION_OUT=$(printf '%s\n' "$DUPSESSION_IN" | bash "$SCRIPT" --min-sessions 3)
check "duplicate session_id lines don't inflate distinct-session support (2 distinct ids -> below threshold 3)" "[]" \
  "$(printf '%s' "$DUPSESSION_OUT" | jq -c '.clusters')"

# ── 8. Sentinel / privacy pass-through: only whitelisted fields appear ─────
SENTINEL_IN=$(printf '%s\n%s\n%s\n' \
  '{"session_id":"sent-1","project_slug":"p","event_count":1,"events":[{"tool":"Bash","head":"curl SENTINEL_abc"}]}' \
  '{"session_id":"sent-2","project_slug":"p","event_count":1,"events":[{"tool":"Bash","head":"curl SENTINEL_abc"}]}' \
  '{"session_id":"sent-3","project_slug":"p","event_count":1,"events":[{"tool":"Bash","head":"curl SENTINEL_abc"}]}')
# n-grams need n>=2, so single-event sessions can't cluster; use 2-event sessions instead.
SENTINEL_IN2=$(printf '%s\n%s\n%s\n' \
  '{"session_id":"sent-1","project_slug":"p","event_count":2,"events":[{"tool":"Bash","head":"curl SENTINEL_abc"},{"tool":"Read"}]}' \
  '{"session_id":"sent-2","project_slug":"p","event_count":2,"events":[{"tool":"Bash","head":"curl SENTINEL_abc"},{"tool":"Read"}]}' \
  '{"session_id":"sent-3","project_slug":"p","event_count":2,"events":[{"tool":"Bash","head":"curl SENTINEL_abc"},{"tool":"Read"}]}')
SENTINEL_OUT=$(printf '%s\n' "$SENTINEL_IN2" | bash "$SCRIPT" --min-sessions 3)
check_contains "sentinel head survives verbatim as the event string" "$SENTINEL_OUT" "Bash:curl SENTINEL_abc"
check "output top-level keys are exactly the documented schema" '["clusters","diagnostics","scanned_sessions"]' \
  "$(printf '%s' "$SENTINEL_OUT" | jq -c '. | keys | sort')"
check "cluster object keys are exactly the documented schema" '["count","n","ngram","sessions"]' \
  "$(printf '%s' "$SENTINEL_OUT" | jq -c '.clusters[0] | keys | sort')"

# ── 7b. Sessions with 0 or 1 events contribute zero n-grams without error ──
SHORTSESSION_IN=$(printf '%s\n%s\n' \
  '{"session_id":"short-0","project_slug":"p","event_count":0,"events":[]}' \
  '{"session_id":"short-1","project_slug":"p","event_count":1,"events":[{"tool":"Read"}]}')
SHORTSESSION_OUT=$(printf '%s\n' "$SHORTSESSION_IN" | bash "$SCRIPT" --min-sessions 1)
check "0/1-event sessions -> both still counted in scanned_sessions" "2" \
  "$(printf '%s' "$SHORTSESSION_OUT" | jq -r '.scanned_sessions')"
check "0/1-event sessions -> contribute zero n-grams (no clusters, nothing below threshold)" "[]" \
  "$(printf '%s' "$SHORTSESSION_OUT" | jq -c '.clusters')"

# ── 7c. Same n-gram repeated within one session: count reflects raw
#     occurrences (across all sessions) while sessions stays deduplicated to
#     distinct-session support — the two fields measure different things. ──
REPEAT_IN=$(printf '%s\n%s\n%s\n' \
  '{"session_id":"rep-1","project_slug":"p","event_count":4,"events":[{"tool":"A"},{"tool":"B"},{"tool":"A"},{"tool":"B"}]}' \
  '{"session_id":"rep-2","project_slug":"p","event_count":2,"events":[{"tool":"A"},{"tool":"B"}]}' \
  '{"session_id":"rep-3","project_slug":"p","event_count":2,"events":[{"tool":"A"},{"tool":"B"}]}')
REPEAT_OUT=$(printf '%s\n' "$REPEAT_IN" | bash "$SCRIPT" --min-sessions 3)
REPEAT_CLUSTER=$(printf '%s' "$REPEAT_OUT" | jq -c '.clusters[] | select(.ngram == ["A","B"])')
check "same-session-repeated ngram -> count == raw occurrences (2+1+1=4)" "4" \
  "$(printf '%s' "$REPEAT_CLUSTER" | jq -r '.count')"
check "same-session-repeated ngram -> sessions stays deduplicated to 3 distinct ids" \
  '["rep-1","rep-2","rep-3"]' "$(printf '%s' "$REPEAT_CLUSTER" | jq -c '.sessions | sort')"

# ── 8b. Non-string tool/head fields never crash or leak raw JSON (regression
#     guard for the same type-coercion privacy-boundary hole WU1 hit) ───────
NONSTRING_HEAD_IN=$(printf '%s\n%s\n%s\n' \
  '{"session_id":"ns-1","project_slug":"p","event_count":1,"events":[{"tool":"Bash","head":{"nested":"should_not_leak"}}]}' \
  '{"session_id":"ns-2","project_slug":"p","event_count":1,"events":[{"tool":"Bash","head":{"nested":"should_not_leak"}}]}' \
  '{"session_id":"ns-3","project_slug":"p","event_count":1,"events":[{"tool":"Bash","head":{"nested":"should_not_leak"}}]}')
NONSTRING_OUT=$(printf '%s\n' "$NONSTRING_HEAD_IN" | bash "$SCRIPT" --min-sessions 3 2>/tmp/cluster_ngrams_nonstring.err)
NONSTRING_RC=$?
check "non-string head field -> script still exits 0" "0" "$NONSTRING_RC"
check_not_contains "non-string head field -> never leaks raw object to stdout" "$NONSTRING_OUT" "should_not_leak"
NONSTRING_ERR=$(cat /tmp/cluster_ngrams_nonstring.err); rm -f /tmp/cluster_ngrams_nonstring.err
check_not_contains "non-string head field -> no raw jq crash trace on stderr" "$NONSTRING_ERR" "cannot be added"

# Non-string `tool` with a string `head` must not fabricate a leading-colon
# event string (":x") — that shape isn't in the documented event grammar.
NONSTRING_TOOL_IN=$(printf '%s\n%s\n%s\n' \
  '{"session_id":"nt-1","project_slug":"p","event_count":2,"events":[{"tool":123,"head":"x"},{"tool":"Read"}]}' \
  '{"session_id":"nt-2","project_slug":"p","event_count":2,"events":[{"tool":123,"head":"x"},{"tool":"Read"}]}' \
  '{"session_id":"nt-3","project_slug":"p","event_count":2,"events":[{"tool":123,"head":"x"},{"tool":"Read"}]}')
NONSTRING_TOOL_OUT=$(printf '%s\n' "$NONSTRING_TOOL_IN" | bash "$SCRIPT" --min-sessions 3)
check_not_contains "non-string tool with string head -> never fabricates a leading-colon event string" \
  "$NONSTRING_TOOL_OUT" '":x"'

# ── 8c. Valid-but-non-object JSON lines (false/0/string/array/null) are
#     rejected as jq_parse_error, not silently counted or crashed on ─────────
NONOBJ_IN=$(printf '%s\n%s\n%s\n%s\n%s\n' 'false' '0' '"x"' '[1,2,3]' 'null')
NONOBJ_ERR=$(printf '%s\n' "$NONOBJ_IN" | bash "$SCRIPT" 2>&1 >/dev/null)
NONOBJ_OUT=$(printf '%s\n' "$NONOBJ_IN" | bash "$SCRIPT" 2>/dev/null)
NONOBJ_RC=$?
check "non-object JSON lines -> exit 0" "0" "$NONOBJ_RC"
check "non-object JSON lines -> scanned_sessions == 0 (none are valid sessions)" "0" \
  "$(printf '%s' "$NONOBJ_OUT" | jq -r '.scanned_sessions')"
check_contains "non-object JSON line 1 (false) -> jq_parse_error:1" "$NONOBJ_ERR" "jq_parse_error:1"
check_contains "non-object JSON line 2 (0) -> jq_parse_error:2" "$NONOBJ_ERR" "jq_parse_error:2"
check_contains "non-object JSON line 5 (null) -> jq_parse_error:5" "$NONOBJ_ERR" "jq_parse_error:5"
check_not_contains "non-object JSON lines -> no raw jq crash trace on stderr" "$NONOBJ_ERR" "Cannot index"

# ── 9. --help exits 0 ────────────────────────────────────────────────────────
HELP_OUT=$(bash "$SCRIPT" --help 2>&1)
HELP_RC=$?
check "--help exits 0" "0" "$HELP_RC"
check_contains "--help mentions min-sessions" "$HELP_OUT" "min-sessions"

# ── 10. Integration: real scan_transcripts.sh piped into cluster_ngrams.sh ──
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/proj-int-a" "$TMP/proj-int-b" "$TMP/proj-int-c"
# Three sessions each running: Bash "git log", Bash "git push", Skill "prime" — same
# shape as fixture-small.jsonl's event producers, built directly as transcript records.
make_session() {
  local file="$1"
  {
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"git log --oneline"}}]},"timestamp":"2026-07-06T10:00:00Z"}\n'
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"git push origin"}}]},"timestamp":"2026-07-06T10:00:01Z"}\n'
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Skill","input":{"skill":"prime"}}]},"timestamp":"2026-07-06T10:00:02Z"}\n'
  } > "$file"
}
make_session "$TMP/proj-int-a/aaaaaaaa-0000-0000-0000-000000000001.jsonl"
make_session "$TMP/proj-int-b/aaaaaaaa-0000-0000-0000-000000000002.jsonl"
make_session "$TMP/proj-int-c/aaaaaaaa-0000-0000-0000-000000000003.jsonl"
INTEGRATION_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCAN_SCRIPT" --all-projects --days 36500 | bash "$SCRIPT" --min-sessions 3)
check "integration: scan_transcripts.sh -> cluster_ngrams.sh surfaces the known trigram cluster" "3" \
  "$(printf '%s' "$INTEGRATION_OUT" | jq -r '.clusters[] | select(.ngram == ["Bash:git log","Bash:git push","Skill:prime"]) | .count')"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
