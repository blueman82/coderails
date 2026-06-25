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
  jq -n --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' >> "$out"
  printf '%s' "$out"
}

# Transcript with a text message but NO file edits — hook skips file_count check.
mk_transcript_no_edit() { # text -> path
  local text="$1" out="$TMP/t_ne_$RANDOM.jsonl"
  jq -n --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' > "$out"
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

# Case 2: no files edited (file_count=0) -> allow even with untagged DNV
T=$(mk_transcript_no_edit "Some text.
## Did Not Verify
- untagged item about something")
check "no files edited -> allow" 0 "$(run "$(payload "$T")")"

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

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
