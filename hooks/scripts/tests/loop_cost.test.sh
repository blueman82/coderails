#!/bin/bash
# Behavioural test for loop_cost.sh — exercises dc_mine_token_usage against
# synthetic ~/.claude/projects-shaped fixture trees. All state lives under a
# temp dir standing in for HOME, never the real ~/.claude/projects.
# Run: bash hooks/scripts/tests/loop_cost.test.sh
set -u
LIB="$(cd "$(dirname "$0")/.." && pwd)/lib/loop_cost.sh"
PRICES="$(cd "$(dirname "$0")/.." && pwd)/lib/model_prices.json"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %q\n  actual:   %q\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# shellcheck source=/dev/null
. "$LIB"

# Point the lib at our fixture tree instead of the real ~/.claude/projects.
export CLAUDE_PROJECTS_DIR="$TMP/projects"
export CLAUDE_MODEL_PRICES_FILE="$PRICES"
mkdir -p "$TMP/projects"

# Helper: write an assistant usage line. Emits a full cache_creation split
# object (matches real transcripts) unless legacy=1, in which case it emits
# the flat cache_creation_input_tokens field instead (pre-split shape).
usage_line() { # id model input output cache_read cw5m cw1h [legacy]
  local id="$1" model="$2" input="$3" output="$4" cread="$5" cw5m="$6" cw1h="$7" legacy="${8:-0}"
  if [ "$legacy" = "1" ]; then
    jq -cn --arg id "$id" --arg model "$model" --argjson input "$input" --argjson output "$output" \
      --argjson cread "$cread" --argjson cwtot "$((cw5m + cw1h))" \
      '{type:"assistant",message:{id:$id,model:$model,usage:{input_tokens:$input,output_tokens:$output,cache_read_input_tokens:$cread,cache_creation_input_tokens:$cwtot}}}'
  else
    jq -cn --arg id "$id" --arg model "$model" --argjson input "$input" --argjson output "$output" \
      --argjson cread "$cread" --argjson cw5m "$cw5m" --argjson cw1h "$cw1h" \
      '{type:"assistant",message:{id:$id,model:$model,usage:{input_tokens:$input,output_tokens:$output,cache_read_input_tokens:$cread,cache_creation:{ephemeral_5m_input_tokens:$cw5m,ephemeral_1h_input_tokens:$cw1h}}}}'
  fi
}

# --- Test (a): dedupe — one message.id repeated 10x identical -> counted ONCE (E2) ---
sess="dedupe-session"
proj="$TMP/projects/-test-proj-a"
mkdir -p "$proj"
{
  for _ in $(seq 1 10); do
    usage_line "msg_dup1" "claude-opus-4-8" 100 50 0 0 0
  done
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].input_tokens')
check "dedupe: 10 identical lines for one message.id counted once (input_tokens)" "100" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].output_tokens')
check "dedupe: 10 identical lines for one message.id counted once (output_tokens)" "50" "$result"

# --- Test (b): worker inclusion — orchestrator .jsonl + subagents/agent-x.jsonl
# -> both models appear in models_used (E3) ---
sess="worker-session"
proj="$TMP/projects/-test-proj-b"
mkdir -p "$proj/$sess/subagents"
usage_line "msg_orch1" "claude-opus-4-8" 10 5 0 0 0 > "$proj/$sess.jsonl"
usage_line "msg_worker1" "claude-haiku-4-5" 20 8 0 0 0 > "$proj/$sess/subagents/agent-x.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.models_used | sort | join(",")')
check "worker inclusion: orchestrator + subagent models both present" "claude-haiku-4-5,claude-opus-4-8" "$result"
result=$(printf '%s' "$out" | jq -r '.transcripts_scanned')
check "worker inclusion: transcripts_scanned counts orchestrator + 1 subagent = 2" "2" "$result"

# --- Test (b2): worker inclusion — recursion into a NESTED subagents dir
# (agent spawning agent) must not be flat-glob-missed ---
sess="nested-worker-session"
proj="$TMP/projects/-test-proj-b2"
mkdir -p "$proj/$sess/subagents/agent-outer/subagents"
usage_line "msg_orch_b2" "claude-opus-4-8" 1 1 0 0 0 > "$proj/$sess.jsonl"
usage_line "msg_nested1" "claude-sonnet-5" 30 10 0 0 0 > "$proj/$sess/subagents/agent-outer/subagents/agent-inner.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.models_used | contains(["claude-sonnet-5"])')
check "worker inclusion: nested subagent transcript found via recursion" "true" "$result"
result=$(printf '%s' "$out" | jq -r '.transcripts_scanned')
check "worker inclusion: transcripts_scanned counts orchestrator + 1 nested subagent = 2" "2" "$result"

# --- Test (c): fail-open — unknown session id -> {} and exit 0 (E4) ---
rc_out=$(dc_mine_token_usage "session-does-not-exist-anywhere" 2>/dev/null)
rc=$?
check "fail-open: unknown session id -> exit 0" "0" "$rc"
check "fail-open: unknown session id -> {}" "{}" "$rc_out"

# --- Test (d): synthetic model skip — a message.model=="<synthetic>" line excluded ---
sess="synthetic-session"
proj="$TMP/projects/-test-proj-d"
mkdir -p "$proj"
{
  usage_line "msg_real1" "claude-opus-4-8" 10 5 0 0 0
  usage_line "msg_synth1" "<synthetic>" 999 999 0 0 0
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.models_used | join(",")')
check "synthetic skip: <synthetic> model excluded from models_used" "claude-opus-4-8" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model | has("<synthetic>")')
check "synthetic skip: <synthetic> has no per_model entry" "false" "$result"

# --- Test (e): multi-model per-model split correct ---
sess="multimodel-session"
proj="$TMP/projects/-test-proj-e"
mkdir -p "$proj"
{
  usage_line "msg_e1" "claude-opus-4-8" 100 50 0 0 0
  usage_line "msg_e2" "claude-haiku-4-5" 200 75 0 0 0
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].input_tokens')
check "multi-model split: opus input_tokens isolated from haiku" "100" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-haiku-4-5"].input_tokens')
check "multi-model split: haiku input_tokens isolated from opus" "200" "$result"
# Rollup check: total_tokens/total_usd_estimate sum across BOTH models, not
# just the last one written (opus 150 tok/$0.00175 + haiku 275 tok/$0.000575).
result=$(printf '%s' "$out" | jq -r '.total_tokens')
check "multi-model split: total_tokens rolls up both models (150+275)" "425" "$result"
result=$(printf '%s' "$out" | jq -r '.total_usd_estimate')
check "multi-model split: total_usd_estimate rolls up both models" "0.002325" "$result"

# --- Test (f): cache 5m vs 1h priced at different multipliers ---
sess="cache-split-session"
proj="$TMP/projects/-test-proj-f"
mkdir -p "$proj"
# opus: input=0 output=0 cache_read=0, cw5m=1,000,000 cw1h=0 -> usd = 1 * 6.25 = 6.25
usage_line "msg_f1" "claude-opus-4-8" 0 0 0 1000000 0 > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].usd_estimate')
check "cache 5m priced at 5m multiplier (opus 1M cw5m tokens -> \$6.25)" "6.25" "$result"

sess="cache-split-session-1h"
proj="$TMP/projects/-test-proj-f1h"
mkdir -p "$proj"
# opus: cw1h=1,000,000 -> usd = 1 * 10.00 = 10.00
usage_line "msg_f2" "claude-opus-4-8" 0 0 0 0 1000000 > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].usd_estimate')
check "cache 1h priced at 1h multiplier (opus 1M cw1h tokens -> \$10.00)" "10" "$result"

# --- Test (g): legacy flat cache_creation_input_tokens (no split object)
# -> ALL counted as cache_write_5m (conservative — cheaper multiplier) ---
sess="legacy-cache-session"
proj="$TMP/projects/-test-proj-g"
mkdir -p "$proj"
usage_line "msg_g1" "claude-opus-4-8" 0 0 0 500000 500000 1 > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].cache_write_5m_tokens')
check "legacy cache_creation_input_tokens: all counted as cache_write_5m" "1000000" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].cache_write_1h_tokens')
check "legacy cache_creation_input_tokens: none counted as cache_write_1h" "0" "$result"

# --- Test (h): unpriced model — counted, usd_estimate 0, listed in unpriced_models ---
sess="unpriced-session"
proj="$TMP/projects/-test-proj-h"
mkdir -p "$proj"
usage_line "msg_h1" "claude-made-up-model-9000" 111 22 0 0 0 > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-made-up-model-9000"].input_tokens')
check "unpriced model: tokens still counted" "111" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-made-up-model-9000"].usd_estimate')
check "unpriced model: usd_estimate is 0" "0" "$result"
result=$(printf '%s' "$out" | jq -r '.unpriced_models | contains(["claude-made-up-model-9000"])')
check "unpriced model: listed in unpriced_models" "true" "$result"

# --- Test (h2): dated-snapshot model ID (e.g. claude-haiku-4-5-20251001, the
# resolved form real transcripts carry) prices via its bare alias in the
# table -- normalized for RATE LOOKUP ONLY. per_model/models_used keep the
# raw dated string (must match what's literally in the transcript), and the
# rate applied is the alias's rate (not left unpriced). ---
sess="dated-snapshot-session"
proj="$TMP/projects/-test-proj-h2"
mkdir -p "$proj"
usage_line "msg_h2" "claude-haiku-4-5-20251001" 1000000 0 0 0 0 > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model | has("claude-haiku-4-5-20251001")')
check "dated snapshot: raw dated ID kept as per_model key (not normalized away)" "true" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-haiku-4-5-20251001"].usd_estimate')
check "dated snapshot: priced via bare alias rate (haiku \$1.00/MTok input -> \$1.00)" "1" "$result"
result=$(printf '%s' "$out" | jq -r '.unpriced_models | contains(["claude-haiku-4-5-20251001"])')
check "dated snapshot: NOT listed in unpriced_models (rate was found via normalization)" "false" "$result"
result=$(printf '%s' "$out" | jq -r '.models_used | join(",")')
check "dated snapshot: models_used carries the raw dated string, not the alias" "claude-haiku-4-5-20251001" "$result"

# --- Test (i): schema shape — top-level required keys present ---
sess="shape-session"
proj="$TMP/projects/-test-proj-i"
mkdir -p "$proj"
usage_line "msg_i1" "claude-opus-4-8" 10 5 0 0 0 > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
for key in schema_version prices_as_of price_source per_model total_tokens total_usd_estimate transcripts_scanned unpriced_models notes models_used; do
  result=$(printf '%s' "$out" | jq -e "has(\"$key\")" 2>/dev/null)
  check "schema shape: top-level key '$key' present" "true" "$result"
done
result=$(printf '%s' "$out" | jq -r '.schema_version')
check "schema shape: schema_version is 1" "1" "$result"

# --- Test (i2): session_id path-traversal is neutralised before it is
# globbed into a path (defence-in-depth, mirrors als_sanitise_session_id's
# framing — session_id is caller-supplied, not attacker-controlled, but the
# sanitisation still applies). A "../../secret/leak"-shaped session_id must
# not escape CLAUDE_PROJECTS_DIR: plant a real transcript OUTSIDE the
# projects tree at the literal traversal target, and one INSIDE at the
# sanitised path; only the sanitised (inside) one may be found. ---
outside_dir="$TMP/outside-secret"
mkdir -p "$outside_dir"
usage_line "msg_outside" "claude-opus-4-8" 999999 999999 0 0 0 > "$outside_dir/leak.jsonl"
sess='../../outside-secret/leak'
sanitised_sess='__outside-secret_leak'
proj="$TMP/projects/-traversal-proj"
mkdir -p "$proj"
usage_line "msg_inside" "claude-sonnet-5" 42 7 0 0 0 > "$proj/$sanitised_sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model | has("claude-opus-4-8")')
check "traversal: outside-projects-dir transcript NOT mined" "false" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-sonnet-5"].input_tokens // "absent"')
check "traversal: sanitised in-tree transcript IS mined" "42" "$result"

# --- Test (i2b): whole-batch wipeout guard — a line that IS valid JSON but
# has a WRONG-TYPED usage field (a string, not an object) must not crash the
# jq -s aggregation and wipe every other transcript's real numbers to {}.
# The bad line is dropped like any other malformed input; the good line
# still counts. This is distinct from the parse-tolerance test below (which
# covers non-JSON garbage) — this covers well-formed JSON with a type error
# one level deeper, which `fromjson?` alone cannot catch. ---
sess="wrong-typed-usage-session"
proj="$TMP/projects/-test-proj-wipeout"
mkdir -p "$proj"
{
  usage_line "msg_good1" "claude-opus-4-8" 100 50 0 0 0
  jq -cn '{type:"assistant",message:{id:"msg_bad1",model:"claude-opus-4-8",usage:"not-an-object"}}'
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].input_tokens // "WIPED"')
check "whole-batch wipeout: wrong-typed usage line dropped, valid line still counted (not wiped to {})" "100" "$result"

# --- Test (i2c): same wipeout risk one level deeper — a well-formed usage
# OBJECT whose cache_creation field is wrong-typed (a string, not an
# object) must not crash when indexed for .ephemeral_5m_input_tokens. Falls
# through to the legacy flat-field branch (cache_creation_input_tokens),
# same as if cache_creation were absent. ---
sess="wrong-typed-cache-creation-session"
proj="$TMP/projects/-test-proj-wipeout2"
mkdir -p "$proj"
{
  jq -cn '{type:"assistant",message:{id:"msg_cc1",model:"claude-opus-4-8",usage:{input_tokens:1,output_tokens:1,cache_creation:"garbage",cache_creation_input_tokens:500}}}'
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].input_tokens // "WIPED"')
check "wrong-typed cache_creation: batch not wiped, valid fields still counted" "1" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].cache_write_5m_tokens')
check "wrong-typed cache_creation: falls through to legacy flat field (500)" "500" "$result"

# --- Test (i2d): same wipeout risk a THIRD level deep — a well-formed usage
# object with an otherwise-valid shape but a WRONG-TYPED NUMERIC LEAF (e.g.
# input_tokens is a string, not a number). `// 0` alone does NOT catch this
# ("abc" // 0 is still "abc"; adding that to a number throws) — must use
# `| numbers) // 0` to actually coerce a wrong type, not just null/false.
# Mixed with a fully-valid line: proves (a) the batch is not wiped, (b) the
# bad line's wrong-typed field coerces to 0 while its OTHER valid field
# still contributes, (c) the valid line is counted in full. ---
sess="wrong-typed-numeric-leaf-session"
proj="$TMP/projects/-test-proj-wipeout3"
mkdir -p "$proj"
{
  usage_line "msg_good_leaf" "claude-opus-4-8" 100 50 0 0 0
  jq -cn '{type:"assistant",message:{id:"msg_bad_leaf",model:"claude-opus-4-8",usage:{input_tokens:"abc",output_tokens:5}}}'
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].input_tokens // "WIPED"')
check "wrong-typed numeric leaf: batch not wiped, wrong-typed input_tokens coerced to 0 (only good line's 100 counted)" "100" "$result"
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].output_tokens // "WIPED"')
check "wrong-typed numeric leaf: bad line's VALID output_tokens (5) still contributes alongside good line's 50" "55" "$result"

# --- Test (i3): stage-1 parse tolerance — a genuinely non-JSON garbage
# line mixed in with a valid usage line must not zero the whole transcript.
# Guards the `fromjson? // empty` filter: a malformed line drops itself,
# not the file. ---
sess="garbage-line-session"
proj="$TMP/projects/-test-proj-garbage"
mkdir -p "$proj"
{
  printf '%s\n' 'this is not valid json at all {{{'
  usage_line "msg_garbage_ok" "claude-opus-4-8" 10 5 0 0 0
  printf '%s\n' '{"truncated": "mid-wri'
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].input_tokens // "absent"')
check "parse tolerance: garbage lines dropped, valid line still counted" "10" "$result"

# --- Test (j): a line missing message.id is skipped (not a valid usage event) ---
sess="no-id-session"
proj="$TMP/projects/-test-proj-j"
mkdir -p "$proj"
{
  printf '%s\n' '{"type":"assistant","message":{"model":"claude-opus-4-8","usage":{"input_tokens":999,"output_tokens":999}}}'
  usage_line "msg_j1" "claude-opus-4-8" 10 5 0 0 0
} > "$proj/$sess.jsonl"
out=$(dc_mine_token_usage "$sess")
result=$(printf '%s' "$out" | jq -r '.per_model["claude-opus-4-8"].input_tokens')
check "missing message.id line skipped, only valid line counted" "10" "$result"

# --- Test (k): zsh self-path — dc_mine_token_usage sourced into an
# INTERACTIVE-shell-shaped zsh (not run_all.sh's bash) must still find its own
# model_prices.json via self-path resolution, not silently fail-open to {}.
# Under zsh, ${BASH_SOURCE[0]} is empty inside a function, so a bash-only
# self-path idiom returns './model_prices.json' relative to zsh's cwd (not
# the lib's directory) and the "$prices_file" existence guard fails, masking
# real usage data as {} — indistinguishable from "no data found". This test
# does NOT set CLAUDE_MODEL_PRICES_FILE, so it exercises the library's
# default self-path resolution for real, under genuine zsh, with real usage
# data present -- the only way to force the actual reported failure mode
# (a bash-only run_all.sh invocation can't reproduce it). Skips gracefully if
# zsh is unavailable on this machine. ---
if command -v zsh >/dev/null 2>&1; then
  sess="zsh-self-path-session"
  proj="$TMP/projects/-test-proj-k"
  mkdir -p "$proj"
  usage_line "msg_k1" "claude-opus-4-8" 100 50 0 0 0 > "$proj/$sess.jsonl"
  zsh_out=$(CLAUDE_PROJECTS_DIR="$TMP/projects" zsh -c "
    unset CLAUDE_MODEL_PRICES_FILE
    cd /
    . '$LIB'
    dc_mine_token_usage '$sess'
  ")
  result=$(printf '%s' "$zsh_out" | jq -r '.per_model["claude-opus-4-8"].input_tokens // "MISSING"')
  check "zsh self-path: real usage data mined under zsh (not fail-opened to {})" "100" "$result"
else
  printf 'skip - zsh self-path test (zsh not available on this machine)\n'
fi

# --- Test (k2): zsh no-transcript fail-open — under zsh, an unmatched glob
# is a hard error (nomatch is on by default), NOT a silent empty expansion
# like bash. Reaching the "for f in .../*/\"$session.jsonl\"" loop with a
# session that has no transcript anywhere must still fail-open to {} with
# exit 0, not crash with "no matches found" before the
# `[ -n "$orch_transcript" ] || { printf '{}'; return 0; }` guard ever runs.
# Must run under GENUINE zsh (a bash-only test can't reproduce this — bash
# expands the unmatched glob to the literal pattern, which is silently
# skipped by the `[ -f "$f" ] || continue` check, so it never crashes there
# in the first place). Skips gracefully if zsh is unavailable. ---
if command -v zsh >/dev/null 2>&1; then
  zsh_out=$(CLAUDE_PROJECTS_DIR="$TMP/projects" CLAUDE_MODEL_PRICES_FILE="$PRICES" zsh -c "
    . '$LIB'
    dc_mine_token_usage 'no-such-session-xyz'
  " 2>/dev/null)
  zsh_rc=$?
  check "zsh no-transcript: fail-opens to {} (not a crash)" "{}" "$zsh_out"
  check "zsh no-transcript: exit code 0" "0" "$zsh_rc"
else
  printf 'skip - zsh no-transcript fail-open test (zsh not available on this machine)\n'
fi

# --- Test (l): missing prices file — the [ -f "$prices_file" ] fail-open
# bail must emit a DISTINCT stderr diagnostic naming the path it looked for,
# so this branch is no longer indistinguishable from "no usage data found"
# or "jq missing" (the ambiguity that cost prior loops wrong root-cause
# guesses). Return value is unchanged: still {}, still exit 0. ---
sess="missing-prices-session"
proj="$TMP/projects/-test-proj-l"
mkdir -p "$proj"
usage_line "msg_l1" "claude-opus-4-8" 10 5 0 0 0 > "$proj/$sess.jsonl"
bogus_prices="$TMP/does-not-exist-prices.json"
stderr_out=$(CLAUDE_MODEL_PRICES_FILE="$bogus_prices" dc_mine_token_usage "$sess" 2>&1 1>/dev/null)
stdout_out=$(CLAUDE_MODEL_PRICES_FILE="$bogus_prices" dc_mine_token_usage "$sess" 2>/dev/null)
rc=0
CLAUDE_MODEL_PRICES_FILE="$bogus_prices" dc_mine_token_usage "$sess" >/dev/null 2>&1 || rc=$?
check "missing prices file: distinct stderr diagnostic mentions the path" "true" "$(printf '%s' "$stderr_out" | grep -qF "$bogus_prices" && echo true || echo false)"
check "missing prices file: still fail-opens to {} on stdout" "{}" "$stdout_out"
check "missing prices file: still exit 0" "0" "$rc"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails failures)"; exit 1; }
