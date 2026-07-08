#!/bin/bash
# Behavioural test for check_verify_loop.sh — feeds synthetic Stop payloads with
# fixture transcripts and asserts exit codes. All state lives under a temp dir.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/check_verify_loop.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
export CLAUDE_HOOK_SLEEP_S=0
fails=0

# Build a JSONL transcript with an Edit tool use + an assistant text message.
# The hook skips when no files were edited (file_count < 1), so every case that
# needs enforcement must include at least one Write/Edit/MultiEdit tool_use entry.
mk_transcript() { # text -> path
  local text="$1" out="$TMP/t_$RANDOM.jsonl"
  # tool_use line: simulates an Edit call
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/f.py"}}]}}' > "$out"
  # text line: assistant response that the hook inspects
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' >> "$out"
  printf '%s' "$out"
}

# Transcript with a text message but NO file edits — hook skips file_count check.
mk_transcript_no_edit() { # text -> path
  local text="$1" out="$TMP/t_ne_$RANDOM.jsonl"
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' > "$out"
  printf '%s' "$out"
}

payload() { # transcript_path [stop_hook_active] -> json
  local tp="$1" sha="${2:-false}"
  printf '{"transcript_path":"%s","session_id":"S1","stop_hook_active":%s}' "$tp" "$sha"
}

run() { # json -> exit code
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>&1; echo $?
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

RESP_NO_DNV="This is a response that edits files but has no Did Not Verify section. (verified)"

# Case 1: no transcript file -> allow
check "no transcript -> allow" 0 "$(run '{"transcript_path":"/nonexistent.jsonl","session_id":"S1","stop_hook_active":false}')"

# Case 2: no files edited + NO DNV section -> allow (don't nag pure-conversation turns)
T=$(mk_transcript_no_edit "Some text. (verified)")
check "no files edited, no DNV section -> allow" 0 "$(run "$(payload "$T")")"

# Case 2b: no files edited + untagged DNV bullet -> BLOCK (DNV section present = enforce it)
T=$(mk_transcript_no_edit "Some text. (verified)
## Did Not Verify
- untagged item about something")
check "no files edited + untagged DNV -> block" 2 "$(run "$(payload "$T")")"

# Case 2c: no files edited + all bullets tagged (unverifiable) -> allow
T=$(mk_transcript_no_edit "Some text. (verified)
## Did Not Verify
- (unverifiable: prod-only observation) whether the deploy actually succeeded")
check "no files edited + all bullets tagged -> allow" 0 "$(run "$(payload "$T")")"

# Case 3: stop_hook_active=true -> allow (loop-guard prevents re-block)
T=$(mk_transcript "Some text.
## Did Not Verify
- untagged item about something")
check "stop_hook_active -> allow" 0 "$(run "$(payload "$T" true)")"

# Case 4: no DNV section in response -> allow
T=$(mk_transcript "$RESP_NO_DNV")
check "no DNV section -> allow" 0 "$(run "$(payload "$T")")"

# Case 5: DNV section with untagged bullet -> block (exit 2)
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- the integration test was not run")
check "untagged DNV bullet -> block" 2 "$(run "$(payload "$T")")"

# Case 6: DNV section where ALL bullets are tagged (unverifiable) -> allow
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- (unverifiable: prod-only observation) whether the deploy actually succeeded")
check "all bullets tagged unverifiable -> allow" 0 "$(run "$(payload "$T")")"

# Case 7: DNV section with mixed bullets (one tagged, one not) -> block
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- (unverifiable: external system) deploy pipeline status
- tests were not run locally")
check "mixed bullets (one untagged) -> block" 2 "$(run "$(payload "$T")")"

# Case 8: DNV section with multiple untagged bullets -> block
T=$(mk_transcript "Some text here. (inferred)
## Did Not Verify
- call sites in app.py were not read
- the dedup test catches the bug")
check "multiple untagged bullets -> block" 2 "$(run "$(payload "$T")")"

# Case 9: empty DNV bullet (bare "- ") -> allow (not a claim)
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- ")
check "bare DNV bullet (no content) -> allow" 0 "$(run "$(payload "$T")")"

# ── SubagentStop cases ────────────────────────────────────────────────────────
# SubagentStop payloads carry last_assistant_message directly. The hook must read
# that field, not transcript_path (which is the PARENT session transcript).
# For file_count, the hook scans agent_transcript_path; if absent/unreadable,
# file_count is treated as 0 (graceful skip — no false blocks).

subagentstop_payload() { # last_assistant_message [agent_transcript_path] -> json
  local msg="$1" atp="${2:-/nonexistent/subagent.jsonl}"
  jq -n --arg msg "$msg" --arg atp "$atp" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_sub",
    "agent_id": "agent-test",
    "transcript_path": "/nonexistent/parent.jsonl",
    "agent_transcript_path": $atp,
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }'
}

# Build a subagent transcript that includes file edits (so file_count >= 1).
mk_agent_transcript() { # text -> path
  local text="$1" out="$TMP/at_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/f.py"}}]}}' > "$out"
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' >> "$out"
  printf '%s' "$out"
}

# Case 10: SubagentStop, no DNV in message, agent transcript has edits -> allow
AT=$(mk_agent_transcript "Work done. (verified)")
check "SubagentStop no DNV -> allow" 0 "$(run "$(subagentstop_payload "Work done. (verified)" "$AT")")"

# Case 11: SubagentStop, untagged DNV bullet, agent transcript has edits -> block (exit 2)
DNV_MSG="Some work. (verified)
## Did Not Verify
- the integration test was not run"
AT=$(mk_agent_transcript "$DNV_MSG")
check "SubagentStop untagged DNV bullet -> block" 2 "$(run "$(subagentstop_payload "$DNV_MSG" "$AT")")"

# Case 12: SubagentStop, all DNV bullets tagged -> allow
TAGGED_MSG="Some work. (verified)
## Did Not Verify
- (unverifiable: external system) deploy pipeline status"
AT=$(mk_agent_transcript "$TAGGED_MSG")
check "SubagentStop all bullets tagged -> allow" 0 "$(run "$(subagentstop_payload "$TAGGED_MSG" "$AT")")"

# Case 13: SubagentStop, agent_transcript_path absent/malformed -> must BLOCK (exit 2).
# The fix: SubagentStop no longer gates on file_count; it polices last_assistant_message
# directly. So an untagged DNV bullet in the message blocks regardless of whether
# agent_transcript_path is readable.
DNV_MSG2="Some work. (verified)
## Did Not Verify
- untagged item"
check "SubagentStop unreadable agent_transcript -> block (untagged DNV in message)" 2 "$(run "$(subagentstop_payload "$DNV_MSG2" "/nonexistent/subagent.jsonl")")"

# Case 14: Repro — agent_transcript_path is a MALFORMED file (one non-JSON line),
# last_assistant_message has an untagged DNV bullet. Under the old code, jq fails on
# the malformed file, file_count becomes 0, and the hook silently exits 0 (silent-pass
# bug). Under the fix, file_count is irrelevant for SubagentStop; the untagged DNV in
# the message must block (exit 2).
MALFORMED_TRANSCRIPT="$TMP/malformed_$RANDOM.jsonl"
printf 'this is not JSON\n' > "$MALFORMED_TRANSCRIPT"
DNV_MALFORMED="Some work. (verified)
## Did Not Verify
- the integration test was not run"
check "SubagentStop malformed agent_transcript + untagged DNV -> block (repro)" 2 "$(run "$(subagentstop_payload "$DNV_MALFORMED" "$MALFORMED_TRANSCRIPT")")"

# Regression: parent transcript has untagged DNV content, but last_assistant_message
# does NOT have a DNV section — must ALLOW. Proves we read last_assistant_message,
# not transcript_path (parent session).
PARENT_T=$(mk_transcript "Parent text. (verified)
## Did Not Verify
- untagged item in parent")
# The subagentstop message itself is clean; we point transcript_path at the dirty parent
check "SubagentStop: dirty parent transcript, clean message -> allow" 0 "$(
  AT2=$(mk_agent_transcript "Clean subagent response. (verified)")
  jq -n --arg tp "$PARENT_T" --arg msg "Clean subagent response. (verified)" --arg atp "$AT2" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_reg",
    "agent_id": "agent-reg",
    "transcript_path": $tp,
    "agent_transcript_path": $atp,
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }' | bash "$HOOK" >/dev/null 2>&1; echo $?
)"

# ── Fixture-based test ───────────────────────────────────────────────────────
# Case 15: Load the real captured SubagentStop fixture, override last_assistant_message
# to a non-compliant value (untagged DNV bullet), and wire agent_transcript_path to a
# real transcript that includes file edits. Asserts exit 2.
# This keeps the fixture load-bearing so it can't drift silently from the actual payload shape.
FIXTURE="$(cd "$(dirname "$0")" && pwd)/fixtures/subagentstop_payload.json"
AT_FIX=$(mk_agent_transcript "Work. (verified)")
DNV_NON_COMPLIANT="Final response. (verified)
## Did Not Verify
- untagged item that was not resolved"
check "fixture SubagentStop non-compliant -> block" 2 "$(
  jq --arg msg "$DNV_NON_COMPLIANT" --arg atp "$AT_FIX" \
    '.last_assistant_message = $msg | .agent_transcript_path = $atp' \
    "$FIXTURE" | bash "$HOOK" >/dev/null 2>&1; echo $?
)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
