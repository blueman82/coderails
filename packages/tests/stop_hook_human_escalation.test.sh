#!/usr/bin/env bash
# Frozen regression contract for unresolved-graph Stop hooks.
# The first blocked Stop may explain the human approval needed. Repeated
# blocked Stops must remain blocked without repeating that request or a raw
# graph inspection.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0

pass() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n       %s\n' "$1" "$2"; FAILS=$((FAILS + 1)); }
check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then pass "$name"; else fail "$name" "expected $expected, got $actual"; fi
}

git init -q "$TMP/repo"
git_dir=$(git -C "$TMP/repo" rev-parse --path-format=absolute --git-common-dir)
slug=$(printf '%s' "$git_dir" | sed 's#/#-#g')

claude_root="$TMP/claude-loops"
mkdir -p "$claude_root/$slug/S1"
jq -n '{schema_version:1,session_id:"S1",loop_id:"loop-1",revision:1,status:"in-progress",graph:{nodes:{A:{status:"pending"}},edges:[],joins:{},active_wave:null,hard_stop:null}}' \
  >"$claude_root/$slug/S1/progress.json"
jq -n '{schema_version:1,session_id:"S1",loop_id:"loop-1"}' >"$claude_root/$slug/S1/retro.json"
claude_transcript="$TMP/claude.jsonl"
printf '%s\n' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"LOOP-STOP: complete — please stop"}]}}' \
  >"$claude_transcript"

run_claude() {
  local out="$TMP/claude.out" err="$TMP/claude.err"
  printf '%s' "$(jq -cn --arg t "$claude_transcript" --arg cwd "$TMP/repo" '{session_id:"S1",cwd:$cwd,transcript_path:$t,stop_hook_active:false}')" |
    CLAUDE_AGENTIC_LOOP_DIR="$claude_root" CLAUDE_DISCIPLINE_LOG="$TMP/claude.log" \
    CLAUDE_HOOK_MAX_ATTEMPTS=1 bash "$ROOT/hooks/scripts/loop_stall_guard.sh" >"$out" 2>"$err"
  CLAUDE_RC=$?
  CLAUDE_OUT=$(cat "$out")
  CLAUDE_ERR=$(cat "$err")
}

run_claude
check "Claude unresolved graph stays blocked" 2 "$CLAUDE_RC"
check "Claude first block emits one JSON human request" 1 "$(printf '%s' "$CLAUDE_OUT" | jq -e -s 'length == 1 and .[0].systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Claude request is clear" 1 "$(printf '%s' "$CLAUDE_OUT" | jq -r '.systemMessage // empty' | grep -qi 'human approval' && echo 1 || echo 0)"
check "Claude first block hides raw hook prompt" 0 "$(printf '%s' "$CLAUDE_OUT$CLAUDE_ERR" | grep -c 'Active agentic loop\|Continue the loop\|LOOP-STOP: complete refused' || true)"
run_claude
check "Claude repeated unresolved graph stays blocked" 2 "$CLAUDE_RC"
check "Claude repeated block does not repeat human request" "" "$CLAUDE_OUT"
check "Claude repeated block does not repeat raw hook prompt" 0 "$(printf '%s' "$CLAUDE_OUT$CLAUDE_ERR" | grep -c 'Active agentic loop\|Continue the loop\|LOOP-STOP: complete refused' || true)"

claude_transcript="$TMP/claude-no-declaration.jsonl"
printf '%s\n' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"I am done"}]}}' \
  >"$claude_transcript"
jq '.loop_id = "loop-2"' "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
run_claude
check "Claude missing declaration stays blocked" 2 "$CLAUDE_RC"
check "Claude missing declaration emits one human request" 1 "$(printf '%s' "$CLAUDE_OUT" | jq -e -s 'length == 1 and .[0].systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Claude missing declaration hides raw hook prompt" 0 "$(printf '%s' "$CLAUDE_OUT$CLAUDE_ERR" | grep -c 'Active agentic loop\|Continue the loop\|LOOP-STOP:' || true)"
run_claude
check "Claude repeated missing declaration stays blocked" 2 "$CLAUDE_RC"
check "Claude repeated missing declaration does not repeat request" "" "$CLAUDE_OUT"

codex_root="$TMP/codex-loops"
mkdir -p "$codex_root/$slug/S1"
jq -n '{schema_version:2,session_id:"S1",loop_id:"loop-1",revision:1,status:"in-progress",graph:{nodes:{A:{status:"pending",outcome:"pending",retry:{attempts:0,max:2},evidence:[]}},edges:[],joins:{},active_wave:null,hard_stop:null}}' \
  >"$codex_root/$slug/S1/progress.json"

run_codex() {
  local out="$TMP/codex.out"
  printf '%s' "$(jq -cn --arg cwd "$TMP/repo" '{session_id:"S1",cwd:$cwd,last_assistant_message:"done",hook_event_name:"Stop"}')" |
    CODERAILS_AGENTIC_LOOP_DIR="$codex_root" PLUGIN_ROOT="$ROOT/packages/codex" \
    CODERAILS_DISCIPLINE_LOG="$TMP/codex.log" "$ROOT/packages/codex/hooks/scripts/graph_completion_guard.sh" >"$out"
  CODEX_OUT=$(cat "$out")
}

run_codex
check "Codex unresolved graph stays blocked" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.decision == "block"' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Codex first block emits one human request" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Codex request is clear" 1 "$(printf '%s' "$CODEX_OUT" | jq -r '.systemMessage // empty' | grep -qi 'human approval' && echo 1 || echo 0)"
check "Codex first block hides raw graph dump" 0 "$(printf '%s' "$CODEX_OUT" | grep -c 'progress.json\|active_wave\|nodes' || true)"
run_codex
check "Codex repeated unresolved graph stays blocked" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.decision == "block"' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Codex repeated block does not repeat human request" "" "$(printf '%s' "$CODEX_OUT" | jq -r '.systemMessage // empty')"
check "Codex repeated block does not repeat raw graph dump" 0 "$(printf '%s' "$CODEX_OUT" | grep -c 'progress.json\|active_wave\|nodes' || true)"

codex_evidence_root="$TMP/codex-evidence"
mkdir -p "$codex_evidence_root/$slug/S2"
jq -n '{schema_version:2,session_id:"S2",loop_id:"loop-2",revision:2,status:"complete",completion:{revision:1},graph:{nodes:{A:{status:"done",outcome:"done",retry:{attempts:0,max:2},evidence:["observed"]}},edges:[],joins:{},active_wave:null,hard_stop:null}}' \
  >"$codex_evidence_root/$slug/S2/progress.json"
codex_evidence_out=$(printf '%s' "$(jq -cn --arg cwd "$TMP/repo" '{session_id:"S2",cwd:$cwd,last_assistant_message:"done",hook_event_name:"Stop"}')" |
  CODERAILS_AGENTIC_LOOP_DIR="$codex_evidence_root" PLUGIN_ROOT="$ROOT/packages/codex" \
  CODERAILS_DISCIPLINE_LOG="$TMP/codex-evidence.log" "$ROOT/packages/codex/hooks/scripts/graph_completion_guard.sh")
check "Codex invalid completion evidence stays blocked" 1 "$(printf '%s' "$codex_evidence_out" | jq -e '.decision == "block"' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Codex invalid completion evidence is not called unresolved graph" "" "$(printf '%s' "$codex_evidence_out" | jq -r '.systemMessage // empty')"
check "Codex invalid completion evidence explains the repair" 1 "$(printf '%s' "$codex_evidence_out" | jq -r '.reason // empty' | grep -qi 'completion evidence' && echo 1 || echo 0)"

if [ "$FAILS" -eq 0 ]; then echo PASS; exit 0; fi
echo "FAILED ($FAILS)"; exit 1
