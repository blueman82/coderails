# shellcheck shell=bash

# --- Test (l): missing prices file — the [ -f "$prices_file" ] fail-open
# bail must emit a DISTINCT stderr diagnostic naming the path it looked for,
# so this branch is no longer indistinguishable from "no usage data found"
# or "jq missing" (the ambiguity that cost prior loops wrong root-cause
# guesses). Return value is unchanged: still {}, still exit 0. ---
sess="missing-prices-session"
proj="$TMP/projects/-test-proj-l"
mkdir -p "$proj"
usage_line "msg_l1" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
bogus_prices="$TMP/does-not-exist-prices.json"
stderr_out=$(CLAUDE_MODEL_PRICES_FILE="$bogus_prices" dc_mine_token_usage "$sess" 2>&1 1>/dev/null)
stdout_out=$(CLAUDE_MODEL_PRICES_FILE="$bogus_prices" dc_mine_token_usage "$sess" 2>/dev/null)
rc=0
CLAUDE_MODEL_PRICES_FILE="$bogus_prices" dc_mine_token_usage "$sess" >/dev/null 2>&1 || rc=$?
check "missing prices file: distinct stderr diagnostic mentions the path" "true" "$(printf '%s' "$stderr_out" | grep -qF "$bogus_prices" && echo true || echo false)"
check "missing prices file: still fail-opens to {} on stdout" "{}" "$stdout_out"
check "missing prices file: still exit 0" "0" "$rc"

# --- Test (m): jq absent — the `command -v jq` bail must emit a distinct
# stderr diagnostic, so it's no longer indistinguishable from any other
# fail-open cause. Simulate absence with a PATH containing no jq, run in a
# FRESH bash -c subshell (not this script's own shell) — bash caches a
# command's resolved path in its hash table once invoked (this file's own
# `usage_line` helper already called jq earlier), and a one-shot `PATH=...`
# prefix on a single command does not clear that cache, so `command -v jq`
# would still report "found" and silently fall through to a LATER bail
# instead of this one. A fresh subshell starts with an empty hash table, so
# `command -v jq` genuinely re-searches PATH. Return value unchanged: still
# {}, still exit 0. ---
sess="jq-absent-session"
proj="$TMP/projects/-test-proj-m"
mkdir -p "$proj"
usage_line "msg_m1" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
empty_path_dir="$TMP/empty-path-m"
mkdir -p "$empty_path_dir"
run_jq_absent() {
    CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" bash -c "
    PATH='$empty_path_dir'
    . '$LIB'
    dc_mine_token_usage '$sess'
  "
}
stderr_out=$(run_jq_absent 2>&1 1>/dev/null)
stdout_out=$(run_jq_absent 2>/dev/null)
rc=0
run_jq_absent >/dev/null 2>&1 || rc=$?
check "jq absent: distinct stderr diagnostic" "true" "$(printf '%s' "$stderr_out" | grep -qF "jq not found" && echo true || echo false)"
check "jq absent: still fail-opens to {} on stdout" "{}" "$stdout_out"
check "jq absent: still exit 0" "0" "$rc"

# --- Test (n): empty session id — the `[ -n "$session" ]` bail must emit a
# distinct stderr diagnostic. This is a CALLER error, not an environmental
# fail-open, so stdout is no longer a bare {} (that shape is indistinguishable
# from "mined successfully, nothing to report" once stderr is discarded —
# the exact ambiguity that once hid a real $28.91/49.3M-token loop cost).
# Stdout must instead be self-describing JSON: an `error` field, no
# total_tokens/total_usd_estimate/schema_version keys. Exit 0 unchanged. ---
stderr_out=$(dc_mine_token_usage "" 2>&1 1>/dev/null)
stdout_out=$(dc_mine_token_usage "" 2>/dev/null)
rc=0
dc_mine_token_usage "" >/dev/null 2>&1 || rc=$?
check "empty session id: distinct stderr diagnostic" "true" "$(printf '%s' "$stderr_out" | grep -qF "empty session id" && echo true || echo false)"
check "empty session id: stdout is valid JSON" "true" "$(printf '%s' "$stdout_out" | jq -e . >/dev/null 2>&1 && echo true || echo false)"
check "empty session id: stdout has an .error field" "true" "$(printf '%s' "$stdout_out" | jq -e '.error' >/dev/null 2>&1 && echo true || echo false)"
check "empty session id: .error names the fix (session id argument)" "true" "$(printf '%s' "$stdout_out" | jq -r '.hint' | grep -qF "session id" && echo true || echo false)"
check "empty session id: stdout has NO total_tokens key (not mistakable for a real mine)" "false" "$(printf '%s' "$stdout_out" | jq -e 'has("total_tokens")' >/dev/null 2>&1 && echo true || echo false)"
check "empty session id: still exit 0" "0" "$rc"

# --- Test (n2): NO argument at all (not even ""), with stderr fully
# discarded — the exact real-world call shape (an orchestrator invoking the
# fail-open helper bare and piping stderr to /dev/null) that hid the real
# cost this fix exists to surface. Requires `local session="${1:-}"` in the
# lib: under this test file's `set -u`, `local session="$1"` with ZERO
# positional args is an unbound-variable error that aborts the whole script
# before this assertion ever runs — that abort would itself be a broken
# fail-open (a caller error must never crash a `set -u` caller), so the `:-`
# default is part of the fix, not incidental. This test FAILS against
# origin/main's code (bare {} on stdout, no .error field) and PASSES here. ---
stdout_out=$(dc_mine_token_usage 2>/dev/null)
rc=0
dc_mine_token_usage >/dev/null 2>&1 || rc=$?
check "no argument at all: stdout alone (stderr discarded) reveals the caller error" "true" "$(printf '%s' "$stdout_out" | jq -e '.error' >/dev/null 2>&1 && echo true || echo false)"
check "no argument at all: still exit 0 (fail-open preserved even with zero args under set -u)" "0" "$rc"

# --- Test (n3): ordering — the empty-session-id caller-error bail must fire
# even when jq is ALSO absent from PATH, i.e. it must be checked BEFORE the
# `command -v jq` bail, not after. If ordered the other way, a jq-absent
# environment would shadow a genuine zero-argument caller error behind the
# jq bail's plain {} instead of the self-describing error object. Reuses
# test (m)'s fresh-subshell PATH shim (bash caches a resolved command in its
# hash table, so a one-shot PATH= prefix alone would not force `command -v
# jq` to re-search) with ZERO positional args instead of a session id. The
# empty PATH also hides `dirname` (used for self-path resolution earlier in
# the function), which emits a harmless "dirname: command not found" to
# stderr — assert on stdout only, never 2>&1, so that noise doesn't corrupt
# the JSON-validity check. This test FAILS against origin/main's code
# (jq-not-found bail fires first, plain {} on stdout, no .error field) and
# PASSES here. ---
empty_path_dir_n3="$TMP/empty-path-n3"
mkdir -p "$empty_path_dir_n3"
run_jq_absent_no_args() {
    CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" bash -c "
    PATH='$empty_path_dir_n3'
    . '$LIB'
    dc_mine_token_usage
  "
}
stdout_out=$(run_jq_absent_no_args 2>/dev/null)
rc=0
run_jq_absent_no_args >/dev/null 2>&1 || rc=$?
check "ordering: jq absent + zero args still yields the caller-error object (not jq's plain {})" "true" "$(printf '%s' "$stdout_out" | jq -e '.error' >/dev/null 2>&1 && echo true || echo false)"
check "ordering: jq absent + zero args still exit 0" "0" "$rc"

# --- Test (o): no transcript found — the `[ -n "$orch_transcript" ]` bail
# must emit a distinct stderr diagnostic naming the session (unchanged), but
# is now a CALLER error, not an environmental fail-open: a wrong/stale/
# typo'd session id is NOT a correct call, and is the MORE LIKELY real-world
# mistake (easier to pass than no id at all). It is the same failure class as
# the empty-session-id path (test (n) below) — a bare {} on stdout is
# indistinguishable from "mined successfully, nothing to report" once stderr
# is discarded, which is exactly the ambiguity that once hid a real
# $28.91/49.3M-token loop cost. Stdout must be self-describing JSON: an
# `error` field, no total_tokens/total_usd_estimate/schema_version keys.
# Exit 0 unchanged. This test FAILS against origin/main's code (bare {} on
# stdout, no .error field) and PASSES here — see (o RED/GREEN) below for the
# demonstration of both directions. ---
sess="no-transcript-diag-session"
stderr_out=$(dc_mine_token_usage "$sess" 2>&1 1>/dev/null)
stdout_out=$(dc_mine_token_usage "$sess" 2>/dev/null)
rc=0
dc_mine_token_usage "$sess" >/dev/null 2>&1 || rc=$?
check "no transcript: distinct stderr diagnostic mentions the session" "true" "$(printf '%s' "$stderr_out" | grep -qF "no transcript found" && printf '%s' "$stderr_out" | grep -qF "$sess" && echo true || echo false)"
check "no transcript: stdout is valid JSON" "true" "$(printf '%s' "$stdout_out" | jq -e . >/dev/null 2>&1 && echo true || echo false)"
check "no transcript: stdout has an .error field" "true" "$(printf '%s' "$stdout_out" | jq -e '.error' >/dev/null 2>&1 && echo true || echo false)"
check "no transcript: .error names the session id" "true" "$(printf '%s' "$stdout_out" | jq -r '.error' | grep -qF "$sess" && echo true || echo false)"
check "no transcript: .hint names the fix" "true" "$(printf '%s' "$stdout_out" | jq -r '.hint' | grep -qF "session id" && echo true || echo false)"
check "no transcript: stdout has NO total_tokens key (not mistakable for a real mine)" "false" "$(printf '%s' "$stdout_out" | jq -e 'has("total_tokens")' >/dev/null 2>&1 && echo true || echo false)"
check "no transcript: still exit 0" "0" "$rc"

# --- Test (o2): a session id containing a literal double-quote and backslash
# resolves (via als_sanitise_session_id, which strips "/" and collapses ".."
# but NOT '"' or '\') to an unresolvable session — the JSON string built at
# the :127 bail must not be corrupted by those characters landing raw inside
# it. Proves the printf '%s' format-arg substitution plus the belt-and-braces
# strip actually produces valid JSON, not just "looks right" on an ordinary
# session id. ---
sess='ab"c\de'
stdout_out=$(dc_mine_token_usage "$sess" 2>/dev/null)
check "no transcript, quote/backslash in session id: stdout still valid JSON" "true" "$(printf '%s' "$stdout_out" | jq -e . >/dev/null 2>&1 && echo true || echo false)"
check "no transcript, quote/backslash in session id: stdout has an .error field" "true" "$(printf '%s' "$stdout_out" | jq -e '.error' >/dev/null 2>&1 && echo true || echo false)"

# --- Fault-injection harness for tests (p)/(q): a jq SHIM placed first on
# PATH that fails (or emits garbage) ONLY for the stage-2 aggregation jq
# (recognisable by 'unique_by' in its program text), and delegates to the
# REAL jq for every other invocation (the per-line parse stage, the pricing
# stage, and this test file's own `jq` calls). REAL_JQ is resolved dynamically
# (not hardcoded) so the shim works on any machine regardless of jq's
# install location. This reproduces a genuine jq failure that the existing
# `2>/dev/null` on the aggregation pipeline would otherwise mute completely —
# the exact "identical {}, no cause" symptom this task exists to kill. ---
REAL_JQ="$(command -v jq)"
shim_dir="$TMP/jq-shim"
mkdir -p "$shim_dir"

# --- Test (p): mining jq produces nothing (aggregation jq exits non-zero) —
# the `[ -n "$mined" ]` bail must emit a distinct stderr diagnostic. ---
cat >"$shim_dir/jq" <<SHIM
#!/bin/bash
for a in "\$@"; do
  if [[ "\$a" == *"unique_by"* ]]; then
    exit 1
  fi
done
exec "$REAL_JQ" "\$@"
SHIM
chmod +x "$shim_dir/jq"
sess="mining-crash-session"
proj="$TMP/projects/-test-proj-p"
mkdir -p "$proj"
usage_line "msg_p1" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
stderr_out=$(PATH="$shim_dir:$PATH" CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" dc_mine_token_usage "$sess" 2>&1 1>/dev/null)
stdout_out=$(PATH="$shim_dir:$PATH" CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" dc_mine_token_usage "$sess" 2>/dev/null)
rc=0
PATH="$shim_dir:$PATH" CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" dc_mine_token_usage "$sess" >/dev/null 2>&1 || rc=$?
check "mining jq crash: distinct stderr diagnostic (no output)" "true" "$(printf '%s' "$stderr_out" | grep -qF "mining produced no output" && echo true || echo false)"
check "mining jq crash: still fail-opens to {} on stdout" "{}" "$stdout_out"
check "mining jq crash: still exit 0" "0" "$rc"

# --- Test (q): mining jq produces non-JSON garbage (exits 0 but the stage-2
# aggregation stage's stdout is not valid JSON) — the `jq -e .` validity
# check bail must emit a distinct stderr diagnostic, different from test (p)'s
# "no output" message, since these are two different failure stages. ---
cat >"$shim_dir/jq" <<SHIM
#!/bin/bash
for a in "\$@"; do
  if [[ "\$a" == *"unique_by"* ]]; then
    echo "not-valid-json-garbage"
    exit 0
  fi
done
exec "$REAL_JQ" "\$@"
SHIM
chmod +x "$shim_dir/jq"
sess="mining-garbage-session"
proj="$TMP/projects/-test-proj-q"
mkdir -p "$proj"
usage_line "msg_q1" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
stderr_out=$(PATH="$shim_dir:$PATH" CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" dc_mine_token_usage "$sess" 2>&1 1>/dev/null)
stdout_out=$(PATH="$shim_dir:$PATH" CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" dc_mine_token_usage "$sess" 2>/dev/null)
rc=0
PATH="$shim_dir:$PATH" CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" dc_mine_token_usage "$sess" >/dev/null 2>&1 || rc=$?
check "mining jq garbage: distinct stderr diagnostic (invalid JSON)" "true" "$(printf '%s' "$stderr_out" | grep -qF "mining produced invalid JSON" && echo true || echo false)"
check "mining jq garbage: still fail-opens to {} on stdout" "{}" "$stdout_out"
check "mining jq garbage: still exit 0" "0" "$rc"
rm -f "$shim_dir/jq"

# --- Test (r): pricing jq produces nothing — a prices file that EXISTS
# (passes the line-59 guard) but contains invalid JSON, so the `--slurpfile
# prices` stage fails and `result` comes back empty. Distinguishes this
# stage from the mining-stage failures above and from "prices file missing"
# (test l). ---
sess="pricing-crash-session"
proj="$TMP/projects/-test-proj-r"
mkdir -p "$proj"
usage_line "msg_r1" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
invalid_prices="$TMP/invalid-prices.json"
printf 'not valid json {{{' >"$invalid_prices"
stderr_out=$(CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$invalid_prices" dc_mine_token_usage "$sess" 2>&1 1>/dev/null)
stdout_out=$(CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$invalid_prices" dc_mine_token_usage "$sess" 2>/dev/null)
rc=0
CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$invalid_prices" dc_mine_token_usage "$sess" >/dev/null 2>&1 || rc=$?
check "pricing jq crash: distinct stderr diagnostic (pricing produced no output)" "true" "$(printf '%s' "$stderr_out" | grep -qF "pricing produced no output" && echo true || echo false)"
check "pricing jq crash: still fail-opens to {} on stdout" "{}" "$stdout_out"
check "pricing jq crash: still exit 0" "0" "$rc"

# --- Test (t): headless orphan detection — a sibling top-level .jsonl in the
# SAME <proj> dir as the orchestrator transcript, with an mtime inside the
# orchestrator's activity window, is a candidate headless `claude -p` child
# (own top-level session, no subagents/ parent linkage exists to attribute
# its tokens directly — see the lib's header comment). It must be SURFACED
# as a count, not silently dropped, and its tokens must NOT be folded into
# total_tokens/total_usd_estimate (no attribution without proof). The
# orchestrator transcript itself and files in subagents/ must never be
# double-counted as orphans. ---
sess="orphan-session"
proj="$TMP/projects/-test-proj-t"
mkdir -p "$proj/$sess/subagents"
usage_line "msg_orph_orch" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
usage_line "msg_orph_worker" "claude-haiku-4-5" 5 5 0 0 0 >"$proj/$sess/subagents/agent-y.jsonl"
# A sibling top-level session in the same proj dir, mtime pinned to the same
# moment as the orchestrator transcript -> inside its activity window.
usage_line "msg_orph_child" "claude-sonnet-5" 999 999 0 0 0 >"$proj/headless-child-1.jsonl"
touch -t "$(date -j -v-2M +%Y%m%d%H%M 2>/dev/null || date -d '-2 minutes' +%Y%m%d%H%M 2>/dev/null)" "$proj/$sess.jsonl" "$proj/headless-child-1.jsonl" 2>/dev/null
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.headless_children_excluded_count')
check "headless orphan detection: one in-window sibling top-level session counted" "1" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model | has("claude-sonnet-5")')
check "headless orphan detection: orphan's tokens NOT folded into per_model (no fabricated attribution)" "false" "$result"
result=$(printf '%s' "$out" | jq -r '.total_tokens')
check "headless orphan detection: orphan's tokens NOT folded into total_tokens" "25" "$result"

# --- Test (t2): negative case — a sibling top-level session in the SAME proj
# dir but with an mtime FAR OUTSIDE the orchestrator's activity window (a
# different, unrelated run in the same repo) must NOT be counted as a
# candidate orphan. Without this negative case, a bare "count every sibling"
# implementation would pass test (t) too -- this is what actually proves the
# time-window filter discriminates rather than just counting everything. ---
sess="orphan-window-session"
proj="$TMP/projects/-test-proj-t2"
mkdir -p "$proj"
usage_line "msg_orph_w_orch" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
usage_line "msg_orph_w_far" "claude-sonnet-5" 111 22 0 0 0 >"$proj/far-away-session.jsonl"
touch -t "$(date -j -v-2M +%Y%m%d%H%M 2>/dev/null || date -d '-2 minutes' +%Y%m%d%H%M 2>/dev/null)" "$proj/$sess.jsonl" 2>/dev/null
touch -t "$(date -j -v-30d +%Y%m%d%H%M 2>/dev/null || date -d '-30 days' +%Y%m%d%H%M 2>/dev/null)" "$proj/far-away-session.jsonl" 2>/dev/null
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.headless_children_excluded_count')
check "headless orphan detection: out-of-window sibling NOT counted (proves time filter, not a bare sibling count)" "0" "$result"

# --- Test (t3): the orchestrator's own transcript and subagent transcripts
# must never count themselves as headless orphans (no double-count / no
# self-flagging), even though the orchestrator file is itself in-window by
# construction. ---
sess="orphan-noself-session"
proj="$TMP/projects/-test-proj-t3"
mkdir -p "$proj/$sess/subagents"
usage_line "msg_noself_orch" "claude-opus-4-8" 10 5 0 0 0 >"$proj/$sess.jsonl"
usage_line "msg_noself_worker" "claude-haiku-4-5" 5 5 0 0 0 >"$proj/$sess/subagents/agent-z.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.headless_children_excluded_count')
check "headless orphan detection: no siblings present -> count is 0 (orchestrator/subagent files never self-count)" "0" "$result"

# --- Test (s): pairwise distinctness — all 7 fail-open bails in $LIB must
# emit 7 DIFFERENT stderr messages. Tests (l)/(m)/(n)/(o)/(p)/(q)/(r) each
# assert its OWN bail's message individually, but none of them assert the
# messages differ FROM EACH OTHER — two bails silently sharing wording would
# reproduce the identical-{}-for-every-cause bug this whole file exists to
# kill, one layer up (message collision instead of stdout collision). Read
# every `echo "loop_cost: ..." >&2` literal straight out of the library
# source and require exactly 7 unique strings. ---
msg_count=$(grep -oE 'echo "loop_cost:[^"]*"' "$LIB" | wc -l | tr -d ' ')
unique_count=$(grep -oE 'echo "loop_cost:[^"]*"' "$LIB" | sort -u | wc -l | tr -d ' ')
check "pairwise distinctness: 7 loop_cost stderr bail messages found" "7" "$msg_count"
check "pairwise distinctness: all 7 messages are unique (no two bails share wording)" "7" "$unique_count"
