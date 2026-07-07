#!/bin/bash
# Unit test for write_queue_entry.sh — writes a QueueFileEntry JSON file per
# propose-verdict judge output. See skills/workflow-audit/scripts/write_queue_entry.sh.
set -u
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/write_queue_entry.sh"
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

FIXTURE_PROPOSE="$FIXTURES/queue-proposal.json"
SESSIONS_JSON='["11111111-1111-1111-1111-111111111111","22222222-2222-2222-2222-222222222222","33333333-3333-3333-3333-333333333333"]'

# All mktemp -d dirs created below are recorded in TMPDIR_LEDGER and swept on
# exit, matching the cleanup convention used by the other workflow-audit test
# files. A ledger file (not a variable) is used because mktempd is invoked via
# command substitution (QDIRn=$(mktempd)), which forks a subshell — a variable
# mutated inside it would never be visible back in this script.
TMPDIR_LEDGER=$(mktemp)
mktempd() { local d; d=$(mktemp -d); printf '%s\n' "$d" >> "$TMPDIR_LEDGER"; printf '%s' "$d"; }
EXTRA_ERR_FILE=$(mktemp)
trap 'xargs rm -rf < "$TMPDIR_LEDGER"; rm -f "$TMPDIR_LEDGER" "$EXTRA_ERR_FILE"' EXIT

# ── 1. A propose-verdict fixture writes exactly one file named <hash>.json ──
QDIR1=$(mktempd)
HASH1=$(cat "$FIXTURE_PROPOSE" | bash "$SCRIPT" --queue-dir "$QDIR1" --count 3 --sessions "$SESSIONS_JSON")
RC1=$?
check "propose fixture -> exit 0" "0" "$RC1"
check "propose fixture -> exactly one file in queue dir" "1" "$(ls "$QDIR1" | wc -l | tr -d ' ')"
check "propose fixture -> the written file is named <hash>.json" "1" "$(ls "$QDIR1" | grep -c "^${HASH1}\.json$")"

WRITTEN1="$QDIR1/$HASH1.json"

# ── 2. toolName field is exactly "workflow-audit:propose-skill" ────────────
check "written file toolName is exactly workflow-audit:propose-skill" "workflow-audit:propose-skill" \
  "$(jq -r '.toolName' "$WRITTEN1")"

# ── 3. status field is exactly "pending" ────────────────────────────────────
check "written file status is exactly pending" "pending" "$(jq -r '.status' "$WRITTEN1")"

# ── 4. toolInput contains all six fields and no others ──────────────────────
check "toolInput keys are exactly the six D2-whitelisted fields" \
  '["cluster_ngram","count","proposed_description","proposed_name","sessions","task_summary"]' \
  "$(jq -Sc '.toolInput | keys' "$WRITTEN1")"

# ── 5. hash equals sha256(JSON.stringify(sortKeysDeep(toolInput))) ─────────
# Independent oracle: inline the same canonicalise+hash logic assistant-agent's
# sendGate.ts uses, computed here in node rather than reusing the script's own
# jq -S -c pipeline, so this is a real cross-check and not a tautology.
EXPECTED_HASH1=$(jq -c '.toolInput' "$WRITTEN1" | node -e '
function sortKeysDeep(v) {
  if (Array.isArray(v)) return v.map(sortKeysDeep);
  if (v !== null && typeof v === "object") {
    const sorted = {};
    for (const k of Object.keys(v).sort()) sorted[k] = sortKeysDeep(v[k]);
    return sorted;
  }
  return v;
}
const crypto = require("crypto");
let raw = "";
process.stdin.on("data", (d) => { raw += d; });
process.stdin.on("end", () => {
  const toolInput = JSON.parse(raw);
  const canonical = JSON.stringify(sortKeysDeep(toolInput));
  process.stdout.write(crypto.createHash("sha256").update(canonical).digest("hex"));
});
')
check "written file hash equals independently-computed sha256(canonicalise(toolInput))" "$EXPECTED_HASH1" \
  "$(jq -r '.hash' "$WRITTEN1")"
check "written file hash matches its own filename" "$HASH1" "$(jq -r '.hash' "$WRITTEN1")"

# ── 5b. Default --queue-dir (no flag passed) resolves to
#     ~/.claude/coderails-dashboard/queue — exercise the actual default
#     branch, not just the explicitly-passed-flag path every other case uses.
DEFAULT_QUEUE_DIR="$HOME/.claude/coderails-dashboard/queue"
DEFAULT_BEFORE_COUNT=$(ls "$DEFAULT_QUEUE_DIR" 2>/dev/null | wc -l | tr -d ' ')
HASH_DEFAULT=$(cat "$FIXTURE_PROPOSE" | bash "$SCRIPT" --count 3 --sessions "$SESSIONS_JSON")
check "no --queue-dir flag -> writes into the default ~/.claude/coderails-dashboard/queue" "1" \
  "$([ -f "$DEFAULT_QUEUE_DIR/$HASH_DEFAULT.json" ] && echo 1 || echo 0)"
check "default-queue-dir file has the same hash as the explicit-queue-dir run (same input)" "$HASH1" "$HASH_DEFAULT"
# Clean up only the file this test itself created, leaving any pre-existing
# default-queue-dir contents untouched.
rm -f "$DEFAULT_QUEUE_DIR/$HASH_DEFAULT.json" 2>/dev/null
DEFAULT_AFTER_COUNT=$(ls "$DEFAULT_QUEUE_DIR" 2>/dev/null | wc -l | tr -d ' ')
check "default-queue-dir test cleans up after itself (no net file left behind)" "$DEFAULT_BEFORE_COUNT" "$DEFAULT_AFTER_COUNT"

# ── 6. A reject-verdict fixture produces ZERO files (negative control) ──────
QDIR2=$(mktempd)
REJECT_JSON='{"cluster_ngram":["Bash:rm"],"verdict":"reject","reject_reason":"tooling-mechanics artifact","task_summary":"x","proposed_name":"","proposed_description":""}'
REJECT_OUT=$(printf '%s' "$REJECT_JSON" | bash "$SCRIPT" --queue-dir "$QDIR2" --count 1 --sessions '["s1"]')
REJECT_RC=$?
check "reject-verdict fixture -> exit 0 (silent no-op)" "0" "$REJECT_RC"
check "reject-verdict fixture -> no stdout" "" "$REJECT_OUT"
check "reject-verdict fixture -> zero files written" "0" "$(ls "$QDIR2" 2>/dev/null | wc -l | tr -d ' ')"

# ── 6b. A verdict object with the "verdict" key missing entirely (distinct
#     from an explicit "reject") is also a silent no-op — the guard is
#     "!= propose", not "== reject", so an absent key must be covered too. ──
QDIR2B=$(mktempd)
NOVERDICTKEY_JSON='{"cluster_ngram":["Bash:rm"],"task_summary":"x","proposed_name":"","proposed_description":""}'
NOVERDICTKEY_OUT=$(printf '%s' "$NOVERDICTKEY_JSON" | bash "$SCRIPT" --queue-dir "$QDIR2B" --count 1 --sessions '["s1"]')
NOVERDICTKEY_RC=$?
check "missing verdict key -> exit 0 (silent no-op, not a crash)" "0" "$NOVERDICTKEY_RC"
check "missing verdict key -> no stdout" "" "$NOVERDICTKEY_OUT"
check "missing verdict key -> zero files written" "0" "$(ls "$QDIR2B" 2>/dev/null | wc -l | tr -d ' ')"

# ── 7. Sentinel pass-through: task_summary round-trips verbatim (this proves
#     the writer is a faithful pass-through of judge-vetted vocabulary, NOT a
#     second privacy filter that would strip or reconstruct content) ────────
QDIR3=$(mktempd)
SENTINEL='SENTINEL_sk_live_99xyz'
SENTINEL_JSON=$(jq -n --arg s "$SENTINEL" '{cluster_ngram:["Bash:curl"],verdict:"propose",reject_reason:"",task_summary:("contains " + $s + " in a judge-vetted summary"),proposed_name:"x",proposed_description:"y"}')
HASH3=$(printf '%s' "$SENTINEL_JSON" | bash "$SCRIPT" --queue-dir "$QDIR3" --count 1 --sessions '["s1"]')
check_contains "sentinel string round-trips verbatim into written toolInput.task_summary" \
  "$(jq -r '.toolInput.task_summary' "$QDIR3/$HASH3.json")" "$SENTINEL"

# ── 8. Idempotency: same input+count+sessions -> same filename both times ──
QDIR4=$(mktempd)
HASH_RUN1=$(cat "$FIXTURE_PROPOSE" | bash "$SCRIPT" --queue-dir "$QDIR4" --count 3 --sessions "$SESSIONS_JSON")
HASH_RUN2=$(cat "$FIXTURE_PROPOSE" | bash "$SCRIPT" --queue-dir "$QDIR4" --count 3 --sessions "$SESSIONS_JSON")
check "re-running with identical input produces the same hash/filename" "$HASH_RUN1" "$HASH_RUN2"
check "re-running with identical input does not accumulate a duplicate file" "1" \
  "$(ls "$QDIR4" | wc -l | tr -d ' ')"

# ── 9. D2 whitelist structural enforcement: an extra field in the piped
#     verdict object must NOT survive into toolInput (dropped or errors,
#     distinct failure reason from a plain propose/reject guard) ───────────
QDIR5=$(mktempd)
EXTRA_FIELD_JSON='{"cluster_ngram":["Bash:ls"],"verdict":"propose","reject_reason":"","task_summary":"s","proposed_name":"n","proposed_description":"d","raw_transcript_line":"this must never survive"}'
HASH5=$(printf '%s' "$EXTRA_FIELD_JSON" | bash "$SCRIPT" --queue-dir "$QDIR5" --count 1 --sessions '["s1"]' 2>"$EXTRA_ERR_FILE")
RC5=$?
if [ -n "$HASH5" ] && [ -f "$QDIR5/$HASH5.json" ]; then
  check "extra un-whitelisted field -> toolInput keys still exactly the six-field whitelist" \
    '["cluster_ngram","count","proposed_description","proposed_name","sessions","task_summary"]' \
    "$(jq -Sc '.toolInput | keys' "$QDIR5/$HASH5.json")"
  check_not_contains "extra un-whitelisted field -> its value never appears in the written file" \
    "$(cat "$QDIR5/$HASH5.json")" "this must never survive"
else
  # Script chose to error instead of drop — that's an acceptable structural
  # enforcement too, as long as it's a distinct, non-zero exit (not silent).
  check "extra un-whitelisted field -> if the script refuses instead of dropping, it exits non-zero (distinct failure reason)" "true" \
    "$( [ "$RC5" -ne 0 ] && echo true || echo false )"
fi

# ── 9b. Malformed/non-object stdin -> the documented jq_parse_error:stdin
#     path (write_queue_entry.sh's own error branch), not a raw jq crash ───
QDIR6=$(mktempd)
MALFORMED_ERR=$(printf '%s' '{not valid json' | bash "$SCRIPT" --queue-dir "$QDIR6" --count 1 --sessions '["s1"]' 2>&1 >/dev/null)
MALFORMED_RC=$?
check "malformed stdin -> non-zero exit" "true" "$( [ "$MALFORMED_RC" -ne 0 ] && echo true || echo false )"
check_contains "malformed stdin -> documented jq_parse_error:stdin on stderr" "$MALFORMED_ERR" "jq_parse_error:stdin"
check "malformed stdin -> zero files written" "0" "$(ls "$QDIR6" 2>/dev/null | wc -l | tr -d ' ')"

NONOBJECT_JSON='"just a string, not an object"'
QDIR6B=$(mktempd)
NONOBJECT_ERR=$(printf '%s' "$NONOBJECT_JSON" | bash "$SCRIPT" --queue-dir "$QDIR6B" --count 1 --sessions '["s1"]' 2>&1 >/dev/null)
NONOBJECT_RC=$?
check "non-object JSON stdin -> non-zero exit" "true" "$( [ "$NONOBJECT_RC" -ne 0 ] && echo true || echo false )"
check "non-object JSON stdin -> zero files written" "0" "$(ls "$QDIR6B" 2>/dev/null | wc -l | tr -d ' ')"

# ── 10. --help exits 0 ───────────────────────────────────────────────────────
HELP_OUT=$(bash "$SCRIPT" --help 2>&1)
HELP_RC=$?
check "--help exits 0" "0" "$HELP_RC"
check_contains "--help mentions queue-dir" "$HELP_OUT" "queue-dir"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
