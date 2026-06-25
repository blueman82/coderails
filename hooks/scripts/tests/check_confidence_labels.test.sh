#!/bin/bash
# Behavioural test for check_confidence_labels.sh — feeds synthetic Stop payloads
# with fixture transcripts and asserts exit codes. All state lives under a temp dir.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/check_confidence_labels.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
export CLAUDE_HOOK_SLEEP_S=0
fails=0

# Build a synthetic JSONL transcript with one assistant text message.
mk_transcript() { # text -> path
  local text="$1" out="$TMP/t_$RANDOM.jsonl"
  jq -n --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' > "$out"
  printf '%s' "$out"
}

payload() { # transcript_path -> json
  printf '{"transcript_path":"%s","session_id":"S1"}' "$1"
}

run() { # json -> exit code
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>&1; echo $?
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

LONG_TEXT=$(printf '%200s' | tr ' ' 'x')  # exactly 200 chars — meets the >=200 threshold

# Case 1: long response WITH a (verified) label -> allow (exit 0)
T=$(mk_transcript "${LONG_TEXT} (verified) and more text here")
check "labelled long response -> allow" 0 "$(run "$(payload "$T")")"

# Case 2: long response with (inferred) label -> allow
T=$(mk_transcript "${LONG_TEXT} (inferred) something")
check "inferred label -> allow" 0 "$(run "$(payload "$T")")"

# Case 3: long response with (guess) label -> allow
T=$(mk_transcript "${LONG_TEXT} (guess) something")
check "guess label -> allow" 0 "$(run "$(payload "$T")")"

# Case 4: long response with NO label -> block (exit 2)
T=$(mk_transcript "${LONG_TEXT}")
check "unlabelled long response -> block" 2 "$(run "$(payload "$T")")"

# Case 5: short response (< 200 chars) with NO label -> allow
T=$(mk_transcript "Short response without labels.")
check "short unlabelled response -> allow" 0 "$(run "$(payload "$T")")"

# Case 6: no transcript file -> allow
check "no transcript -> allow" 0 "$(run '{"transcript_path":"/nonexistent/path.jsonl","session_id":"S1"}')"

# Case 7: empty transcript_path -> allow
check "empty transcript_path -> allow" 0 "$(run '{"session_id":"S1"}')"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
