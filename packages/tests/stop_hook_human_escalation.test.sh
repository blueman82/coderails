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

jq '.loop_id = "loop-3"' "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
: >"$claude_root/$slug/S1/.human-approval-loop-3-1"
run_claude
check "Claude marker write failure stays blocked" 2 "$CLAUDE_RC"
check "Claude marker write failure still requests human approval" 1 "$(printf '%s' "$CLAUDE_OUT" | jq -e -s 'length == 1 and .[0].systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"

jq '.loop_id = "loop-4"' "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
rm -f "$claude_root/$slug/S1/.human-approval-loop-4-1"
claude_output_failure_bin="$TMP/claude-output-failure-bin"
mkdir -p "$claude_output_failure_bin"
cat >"$claude_output_failure_bin/jq" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "-n" ]]; then
  exit 1
fi
exec /usr/bin/jq "$@"
EOF
chmod +x "$claude_output_failure_bin/jq"
PATH="$claude_output_failure_bin:$PATH" run_claude
check "Claude output-generation failure stays blocked" 2 "$CLAUDE_RC"
check "Claude output-generation failure does not expose raw prompt" 0 "$(printf '%s' "$CLAUDE_OUT$CLAUDE_ERR" | grep -c 'Active agentic loop\|Continue the loop\|LOOP-STOP:' || true)"
check "Claude output-generation failure does not leave a dedupe marker" 0 "$(test -e "$claude_root/$slug/S1/.human-approval-loop-4-1" && echo 1 || echo 0)"
run_claude
check "Claude retry after output failure stays blocked" 2 "$CLAUDE_RC"
check "Claude retry after output failure emits the request" 1 "$(printf '%s' "$CLAUDE_OUT" | jq -e -s 'length == 1 and .[0].systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"

for unresolved_status in ready running blocked failed stale; do
  jq --arg status "$unresolved_status" --arg loop "loop-status-$unresolved_status" \
    '.loop_id = $loop | .graph.nodes = {A:{status:$status}} | .graph.edges = [] | .graph.joins = {}' \
    "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
    mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
  jq --arg loop "loop-status-$unresolved_status" '.loop_id = $loop' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
    mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
  jq --arg loop "loop-status-$unresolved_status" '{session_id:"S1",loop_id:$loop,revision:1,result:"GO"}' \
    >"$claude_root/$slug/S1/evals.json"
  run_claude
  check "Claude $unresolved_status graph stays blocked" 2 "$CLAUDE_RC"
  check "Claude $unresolved_status graph emits the request" 1 "$(printf '%s' "$CLAUDE_OUT" | jq -e -s 'length == 1 and .[0].systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"
done

jq '.loop_id = null' "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
claude_transcript="$TMP/claude.jsonl"
run_claude
check "Claude malformed graph identity stays blocked" 2 "$CLAUDE_RC"
check "Claude malformed graph identity explains repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph identity' && echo 1 || echo 0)"

jq '.loop_id = "loop-5" | .status = "complete" | .graph.nodes.A.status = "done"' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq '.loop_id = "loop-5"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
claude_transcript="$TMP/claude.jsonl"
run_claude
check "Claude complete graph with missing eval evidence stays blocked" 2 "$CLAUDE_RC"
check "Claude missing eval evidence explains repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'evals are STALE' && echo 1 || echo 0)"
jq -n '{session_id:"OTHER",loop_id:"other",revision:99,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
run_claude
check "Claude mismatched eval evidence stays blocked" 2 "$CLAUDE_RC"
check "Claude mismatched eval evidence explains repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'evals are STALE' && echo 1 || echo 0)"

jq '.loop_id = "loop-6" | .status = "complete" | .graph.nodes = {} | .graph.joins = {} | .graph.edges = []' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-6",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-6"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude empty graph stays blocked" 2 "$CLAUDE_RC"
check "Claude empty graph emits no approval request" "" "$CLAUDE_OUT"
check "Claude empty graph explains graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-7" | .graph.nodes = {A:{status:"done"}} | .graph.edges = {} | .graph.joins = {}' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-7",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-7"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude malformed edges stay blocked" 2 "$CLAUDE_RC"
check "Claude malformed edges emit no approval request" "" "$CLAUDE_OUT"
check "Claude malformed edges explain graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-8" | .graph.edges = [] | .graph.joins = []' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-8",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-8"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude malformed joins stay blocked" 2 "$CLAUDE_RC"
check "Claude malformed joins emit no approval request" "" "$CLAUDE_OUT"
check "Claude malformed joins explain graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-11" | .graph.nodes = {A:"done"} | .graph.edges = [] | .graph.joins = {} | .graph.active_wave = null | .graph.hard_stop = null' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-11",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-11"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude malformed node member stays blocked" 2 "$CLAUDE_RC"
check "Claude malformed node member emits no approval request" "" "$CLAUDE_OUT"
check "Claude malformed node member explains graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-12" | .graph.nodes = {A:{status:"done"}} | .graph.edges = ["edge"] | .graph.joins = {}' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-12",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-12"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude malformed edge member stays blocked" 2 "$CLAUDE_RC"
check "Claude malformed edge member emits no approval request" "" "$CLAUDE_OUT"
check "Claude malformed edge member explains graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-14" | .graph.nodes = {A:{status:"done"}} | .graph.edges = [{from:"ghost",to:"A"}] | .graph.joins = {}' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-14",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-14"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude unknown edge node stays blocked" 2 "$CLAUDE_RC"
check "Claude unknown edge node emits no approval request" "" "$CLAUDE_OUT"
check "Claude unknown edge node explains graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-13" | .graph.nodes = {A:{status:"done"}} | .graph.edges = [] | .graph.joins = {A:"join"}' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-13",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-13"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude malformed join member stays blocked" 2 "$CLAUDE_RC"
check "Claude malformed join member emits no approval request" "" "$CLAUDE_OUT"
check "Claude malformed join member explains graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-15" | .graph.nodes = {A:{status:"done"}} | .graph.edges = [] | .graph.joins = {A:{mode:"all",released:false,inputs:["ghost"]}}' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-15",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-15"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude unknown join node stays blocked" 2 "$CLAUDE_RC"
check "Claude unknown join node emits no approval request" "" "$CLAUDE_OUT"
check "Claude unknown join node explains graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-10" | del(.graph.active_wave) | del(.graph.hard_stop)' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{session_id:"S1",loop_id:"loop-10",revision:1,result:"GO"}' >"$claude_root/$slug/S1/evals.json"
jq '.loop_id = "loop-10"' "$claude_root/$slug/S1/retro.json" >"$TMP/retro.json" &&
  mv "$TMP/retro.json" "$claude_root/$slug/S1/retro.json"
run_claude
check "Claude missing graph control fields stays blocked" 2 "$CLAUDE_RC"
check "Claude missing graph control fields emit no approval request" "" "$CLAUDE_OUT"
check "Claude missing graph control fields explain graph repair" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'graph shape' && echo 1 || echo 0)"

jq '.loop_id = "loop-9" | .schema_version = 2 | .proof_disposition = "none: no executable surface" | .graph.nodes = {A:{status:"done"}} | .graph.edges = [] | .graph.joins = {} | .graph.active_wave = null | .graph.hard_stop = null' \
  "$claude_root/$slug/S1/progress.json" >"$TMP/progress.json" &&
  mv "$TMP/progress.json" "$claude_root/$slug/S1/progress.json"
jq -n '{schema_version:2,session_id:"S1",loop_id:"loop-9",cost:{total_usd_estimate:1,total_tokens:2,prices_as_of:"2026-08-28"}}' \
  >"$claude_root/$slug/S1/retro.json"
jq -n --arg head "$(git -C "$ROOT" rev-parse HEAD)" '{scope:"loop",session_id:"S1",loop_id:"loop-9",revision:1,verification_level:0,verification_justification:"focused regression",frozen_sha:$head,head_sha:$head,evals:[],result:"GO"}' \
  >"$claude_root/$slug/S1/evals.json"
bash "$ROOT/scripts/post_evals.sh" grade-loop "$claude_root/$slug/S1/evals.json" >/dev/null
PATH="$claude_output_failure_bin:$PATH" run_claude
check "Claude completion output failure stays blocked" 2 "$CLAUDE_RC"
check "Claude completion output failure reports the block" 1 "$(printf '%s' "$CLAUDE_ERR" | grep -qi 'output' && echo 1 || echo 0)"

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

run_codex_at() {
  local root="$1" session="$2" out="$3"
  printf '%s' "$(jq -cn --arg cwd "$TMP/repo" --arg session "$session" '{session_id:$session,cwd:$cwd,last_assistant_message:"done",hook_event_name:"Stop"}')" |
    CODERAILS_AGENTIC_LOOP_DIR="$root" PLUGIN_ROOT="$ROOT/packages/codex" \
    CODERAILS_DISCIPLINE_LOG="$TMP/codex-marker-failure.log" "$ROOT/packages/codex/hooks/scripts/graph_completion_guard.sh" >"$out"
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

codex_marker_failure_root="$TMP/codex-marker-failure"
mkdir -p "$codex_marker_failure_root/$slug/S3"
jq '.session_id = "S3" | .loop_id = "loop-3" | .revision = 3' "$codex_root/$slug/S1/progress.json" >"$codex_marker_failure_root/$slug/S3/progress.json"
: >"$codex_marker_failure_root/$slug/S3/.human-approval-loop-3-3"
codex_marker_failure_out="$TMP/codex-marker-failure.out"
run_codex_at "$codex_marker_failure_root" S3 "$codex_marker_failure_out"
CODEX_OUT=$(cat "$codex_marker_failure_out")
check "Codex marker write failure stays blocked" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.decision == "block"' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Codex marker write failure still requests human approval" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"

codex_output_failure_bin="$TMP/codex-output-failure-bin"
mkdir -p "$codex_output_failure_bin"
cat >"$codex_output_failure_bin/jq" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "-n" ]]; then
  exit 1
fi
exec /usr/bin/jq "$@"
EOF
chmod +x "$codex_output_failure_bin/jq"
codex_output_failure_out="$TMP/codex-output-failure.out"
PATH="$codex_output_failure_bin:$PATH" run_codex_at "$codex_marker_failure_root" S3 "$codex_output_failure_out"
CODEX_OUT=$(cat "$codex_output_failure_out")
check "Codex output-generation failure stays blocked" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.decision == "block"' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Codex output-generation failure still requests human approval" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.systemMessage != null' >/dev/null 2>&1 && echo 1 || echo 0)"

codex_malformed_root="$TMP/codex-malformed"
mkdir -p "$codex_malformed_root/$slug/S4"
printf '{not-json\n' >"$codex_malformed_root/$slug/S4/progress.json"
codex_malformed_out="$TMP/codex-malformed.out"
run_codex_at "$codex_malformed_root" S4 "$codex_malformed_out"
CODEX_OUT=$(cat "$codex_malformed_out")
check "Codex malformed state stays blocked" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.decision == "block"' >/dev/null 2>&1 && echo 1 || echo 0)"
check "Codex malformed state explains repair" 1 "$(printf '%s' "$CODEX_OUT" | jq -r '.reason // empty' | grep -qi 'invalid' && echo 1 || echo 0)"

codex_malformed_output_out="$TMP/codex-malformed-output.out"
PATH="$codex_output_failure_bin:$PATH" run_codex_at "$codex_malformed_root" S4 "$codex_malformed_output_out"
CODEX_OUT=$(cat "$codex_malformed_output_out")
check "Codex malformed-state output failure stays blocked" 1 "$(printf '%s' "$CODEX_OUT" | jq -e '.decision == "block"' >/dev/null 2>&1 && echo 1 || echo 0)"

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
