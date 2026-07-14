#!/bin/bash
# Behavioural test for crack_on_gate.sh — feeds synthetic UserPromptSubmit and
# PreToolUse payloads and asserts the two-event contract:
#   UserPromptSubmit: "crack on" in the RAW submitted prompt (payload .prompt)
#     stamps a per-session crack_on_active flag; anything else does not.
#   PreToolUse (AskUserQuestion): flag stamped for this session+repo -> deny;
#     no flag, other sessions, or other tools -> allow.
# The negative-control section is the load-bearing proof that detection reads
# the raw prompt and NEVER the transcript/context — "crack on" appears in the
# agentic-loop skill body and injected memory of essentially every session, so
# a transcript scan would brick AskUserQuestion fleet-wide.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/crack_on_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

# Isolate all flag/state writes and log lines from the real ~/.claude.
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/loopdir"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"

CWD="$TMP/project"
mkdir -p "$CWD"

ups_payload() { # prompt session_id -> UserPromptSubmit json
  jq -n --arg prompt "$1" --arg sid "$2" --arg cwd "$CWD" \
    '{"hook_event_name":"UserPromptSubmit","session_id":$sid,"cwd":$cwd,"prompt":$prompt}'
}

# ups_payload_with_transcript <prompt> <session_id> <transcript_path>
ups_payload_with_transcript() {
  jq -n --arg prompt "$1" --arg sid "$2" --arg cwd "$CWD" --arg tp "$3" \
    '{"hook_event_name":"UserPromptSubmit","session_id":$sid,"cwd":$cwd,"prompt":$prompt,"transcript_path":$tp}'
}

ptu_payload() { # tool_name session_id -> PreToolUse json
  jq -n --arg tool "$1" --arg sid "$2" --arg cwd "$CWD" \
    '{"hook_event_name":"PreToolUse","session_id":$sid,"cwd":$cwd,"tool_name":$tool,"tool_input":{}}'
}

run_ups() { # json -> exit code (UserPromptSubmit must always exit 0)
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>/dev/null
  echo $?
}

run_ptu() { # json -> DENY|ALLOW
  local out
  out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}

# flag_count <session_id> -> number of crack_on_active files stamped under
# the isolated loop dir for that session (0 or 1 in every case below).
flag_count() {
  find "$CLAUDE_AGENTIC_LOOP_DIR" -path "*/$1/crack_on_active" 2>/dev/null | grep -c .
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- Baseline: no flag, AskUserQuestion allowed ---
check "fresh session: AskUserQuestion -> allow" ALLOW "$(run_ptu "$(ptu_payload AskUserQuestion sess-fresh)")"

# --- POSITIVE: "crack on" in the raw prompt stamps the flag, then denies ---
check "UPS 'crack on' prompt exits 0" 0 "$(run_ups "$(ups_payload "Right — crack on with the plan, no gates." sess-pos)")"
check "flag stamped for sess-pos" 1 "$(flag_count sess-pos)"
check "sess-pos: AskUserQuestion -> deny" DENY "$(run_ptu "$(ptu_payload AskUserQuestion sess-pos)")"

# Case-insensitive + punctuation-adjacent forms.
check "UPS 'CRACK ON' exits 0" 0 "$(run_ups "$(ups_payload "CRACK ON" sess-upper)")"
check "sess-upper: AskUserQuestion -> deny" DENY "$(run_ptu "$(ptu_payload AskUserQuestion sess-upper)")"
check "UPS 'crack on!' exits 0" 0 "$(run_ups "$(ups_payload "ok, crack on! ship it" sess-punct)")"
check "sess-punct: AskUserQuestion -> deny" DENY "$(run_ptu "$(ptu_payload AskUserQuestion sess-punct)")"
check "UPS multiline prompt containing 'crack on' stamps" 0 "$(run_ups "$(ups_payload "$(printf 'line one\njust crack on please\nline three')" sess-multi)")"
check "sess-multi: AskUserQuestion -> deny" DENY "$(run_ptu "$(ptu_payload AskUserQuestion sess-multi)")"

# --- Word-boundary negatives: lookalike prompts must NOT stamp ---
check "UPS 'crackdown online' exits 0" 0 "$(run_ups "$(ups_payload "discuss the crackdown online" sess-neg1)")"
check "no flag for sess-neg1" 0 "$(flag_count sess-neg1)"
check "sess-neg1: AskUserQuestion -> allow" ALLOW "$(run_ptu "$(ptu_payload AskUserQuestion sess-neg1)")"
check "UPS 'crack ongoing' does not stamp" 0 "$(run_ups "$(ups_payload "there is a crack ongoing in the wall" sess-neg2)")"
check "sess-neg2: AskUserQuestion -> allow" ALLOW "$(run_ptu "$(ptu_payload AskUserQuestion sess-neg2)")"
check "UPS 'firecracker on' does not stamp" 0 "$(run_ups "$(ups_payload "put the firecracker on the table" sess-neg3)")"
check "sess-neg3: AskUserQuestion -> allow" ALLOW "$(run_ptu "$(ptu_payload AskUserQuestion sess-neg3)")"

# --- NEGATIVE CONTROL (game-resistance, mandatory): "crack on" ONLY in the
# transcript/context — the agentic-loop skill body and injected memory carry
# the phrase in ~every session — while the raw prompt is benign. The flag must
# NOT be stamped and AskUserQuestion must stay ALLOWED. This is the assertion
# that proves detection is raw-prompt, not transcript-scan.
TRANSCRIPT="$TMP/transcript-negctl.jsonl"
cat > "$TRANSCRIPT" <<'EOF'
{"type":"user","message":{"content":"load the agentic-loop skill"}}
{"type":"assistant","message":{"content":[{"type":"text","text":"Loaded skills/agentic-loop/SKILL.md: when the user says crack on, no human gates apply. Memory feedback_crack_on_no_gates.md: crack on means proceed autonomously. crack on appears throughout this context."}]}}
EOF
check "UPS benign prompt + 'crack on'-laden transcript exits 0" 0 \
  "$(run_ups "$(ups_payload_with_transcript "please fix the failing test in auth.py" sess-negctl "$TRANSCRIPT")")"
check "NEGATIVE CONTROL: no flag stamped from transcript-only 'crack on'" 0 "$(flag_count sess-negctl)"
check "NEGATIVE CONTROL: sess-negctl AskUserQuestion -> allow" ALLOW \
  "$(run_ptu "$(ptu_payload AskUserQuestion sess-negctl)")"

# --- HARD-STOP PRESERVED: the deny is scoped to AskUserQuestion only. Even
# with the crack-on flag stamped, every other tool passes through untouched —
# the four agentic-loop hard-stops (turn-ending LOOP-STOP declarations, not
# AskUserQuestion calls) cannot be affected.
check "sess-pos (flag live): Bash -> allow" ALLOW "$(run_ptu "$(ptu_payload Bash sess-pos)")"
check "sess-pos (flag live): Write -> allow" ALLOW "$(run_ptu "$(ptu_payload Write sess-pos)")"
check "sess-pos (flag live): Task -> allow" ALLOW "$(run_ptu "$(ptu_payload Task sess-pos)")"

# --- Session isolation: one session's flag never leaks into another ---
check "sess-other (never said crack on): AskUserQuestion -> allow" ALLOW \
  "$(run_ptu "$(ptu_payload AskUserQuestion sess-other)")"

# --- Degenerate payloads: gate stands aside (exit 0, no stamp, no deny) ---
check "UPS empty prompt exits 0" 0 "$(run_ups "$(ups_payload "" sess-empty)")"
check "no flag for sess-empty" 0 "$(flag_count sess-empty)"
check "UPS no prompt field exits 0" 0 "$(run_ups '{"hook_event_name":"UserPromptSubmit","session_id":"sess-nofield"}')"
check "empty stdin exits 0" 0 "$(printf '' | bash "$HOOK" >/dev/null 2>/dev/null; echo $?)"
# Missing session_id: unkeyable — must not stamp anything or deny anything.
check "UPS crack on, no session_id -> exits 0" 0 "$(run_ups "$(jq -n --arg cwd "$CWD" '{"hook_event_name":"UserPromptSubmit","cwd":$cwd,"prompt":"crack on"}')")"
check "PTU AskUserQuestion, no session_id -> allow" ALLOW "$(run_ptu "$(jq -n --arg cwd "$CWD" '{"hook_event_name":"PreToolUse","cwd":$cwd,"tool_name":"AskUserQuestion","tool_input":{}}')")"

# --- UserPromptSubmit stays well-behaved: no deny JSON on its stdout ---
ups_out=$(printf '%s' "$(ups_payload "crack on" sess-stdout)" | bash "$HOOK" 2>/dev/null)
if printf '%s' "$ups_out" | grep -q 'permissionDecision'; then
  check "UPS emits no permissionDecision JSON" clean dirty
else
  check "UPS emits no permissionDecision JSON" clean clean
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
