#!/usr/bin/env bash
# Nested shell and jq programs are intentionally single-quoted for literal expansion.
# shellcheck disable=SC2016
set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PACKAGE="$ROOT/packages/codex"
HOOKS="$PACKAGE/hooks"
fails=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'ok   - %s\n' "$label"
  else
    printf 'FAIL - %s\n' "$label"
    fails=$((fails + 1))
  fi
}

run_bash_hook() {
  local hook="$1" cwd="$2" command="$3" workdir="${4:-}"
  jq -nc --arg cwd "$cwd" --arg command "$command" --arg workdir "$workdir" '{
    session_id: "s1",
    cwd: $cwd,
    hook_event_name: "PreToolUse",
    tool_name: "Bash",
    tool_input: {command: $command, workdir: $workdir}
  }' | "$hook"
}

check "hooks.json parses" jq -e . "$HOOKS/hooks.json"
check "native matcher names" jq -e '
  [.hooks.PreToolUse[].matcher] == ["^Bash$", "^request_user_input$", "^spawn_agent$", "^apply_patch$"] and
  [.hooks.PostToolUse[].matcher] == ["^apply_patch$"]
' "$HOOKS/hooks.json"
check "all commands use PLUGIN_ROOT" jq -e '
  [.hooks[][] | .hooks[] | .command] | all(test("^\\\"\\$\\{PLUGIN_ROOT\\}/hooks/scripts/[^\\\"]+\\\"$"))
' "$HOOKS/hooks.json"
check "no legacy plugin-root variables" sh -c '! grep -R -E "CLAUDE_PLUGIN_ROOT|CODEX_PLUGIN_ROOT" "$1"' sh "$HOOKS"
check "no lifecycle adapter" test ! -e "$HOOKS/lifecycle.py"
check "native graph hooks are registered" jq -e '
  ([.hooks.Stop[].hooks[].command] | index("\"${PLUGIN_ROOT}/hooks/scripts/graph_completion_guard.sh\"")) != null and
  ([.hooks.PreToolUse[] | select(.matcher == "^spawn_agent$") | .hooks[].command] == ["\"${PLUGIN_ROOT}/hooks/scripts/loop_dispatch_guard.sh\""])
' "$HOOKS/hooks.json"
check "shared and cross-provider hooks stay absent" sh -c '! grep -R -E "parallel-review|parallel_review|enforce_pr_workflow|claude -p|codex exec" "$1"' sh "$HOOKS"

missing=0
while IFS= read -r command; do
  relative=$(printf '%s' "$command" | sed -e 's#^"${PLUGIN_ROOT}/##' -e 's#"$##')
  [[ -x "$PACKAGE/$relative" ]] || missing=1
done < <(jq -r '.hooks[][] | .hooks[] | .command' "$HOOKS/hooks.json")
check "hook command paths exist" test "$missing" -eq 0

bootstrap=$(printf '%s' '{"session_id":"s1","cwd":"/tmp","hook_event_name":"SessionStart","source":"startup"}' | PLUGIN_ROOT="$PACKAGE" "$HOOKS/scripts/inject_bootstrap.sh")
check "bootstrap returns native orchestration and graph guidance" sh -c 'printf "%s" "$1" | jq -e ".hookSpecificOutput.additionalContext | contains(\"using-coderails\") and contains(\"top-level session as the orchestrator\") and contains(\"delegate do-work tool calls with spawn_agent\") and contains(\"Native graph resume\")"' sh "$bootstrap"

missing_dispatch=$(printf '%s' '{"session_id":"missing","cwd":"/tmp","hook_event_name":"PreToolUse","tool_name":"spawn_agent","tool_input":{"task_name":"loop-worker-A","message":"work"}}' | CODERAILS_AGENTIC_LOOP_DIR="${TMPDIR:-/tmp}/coderails-codex-hooks-missing-$$" PLUGIN_ROOT="$PACKAGE" "$HOOKS/scripts/loop_dispatch_guard.sh")
check "native worker dispatch without loop state is denied" sh -c 'printf "%s" "$1" | jq -e ".hookSpecificOutput.permissionDecision == \"deny\""' sh "$missing_dispatch"

destructive=$(printf '%s' '{"session_id":"s1","cwd":"/tmp","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/example"}}' | "$HOOKS/scripts/destructive_bash_gate.sh")
check "destructive Bash is denied" sh -c 'printf "%s" "$1" | jq -e ".hookSpecificOutput.permissionDecision == \"deny\""' sh "$destructive"

security_tmp=$(mktemp -d "${TMPDIR:-/tmp}/coderails-codex-hooks.XXXXXX")
trap 'rm -rf "$security_tmp"' EXIT
test_repo="$security_tmp/repo"
git init -q "$test_repo"
git -C "$test_repo" symbolic-ref HEAD refs/heads/feature/native-config-probes

main_repo="$security_tmp/main-repo"
feature_repo="$security_tmp/feature-repo"
pwd_repo="$security_tmp/pwd-repo"
ceiling_data="$security_tmp/verification-data"
git init -q "$main_repo"
git -C "$main_repo" symbolic-ref HEAD refs/heads/main
git init -q "$feature_repo"
git -C "$feature_repo" symbolic-ref HEAD refs/heads/feature/e5
git init -q "$pwd_repo"
git -C "$pwd_repo" symbolic-ref HEAD refs/heads/feature/pwd
workdir_output=$(PLUGIN_DATA="$ceiling_data" run_bash_hook "$HOOKS/scripts/verification_volume_ceiling.sh" "$main_repo" "packages/tests/codex_hooks.test.sh" "$feature_repo")
cwd_output=$(PLUGIN_DATA="$ceiling_data" run_bash_hook "$HOOKS/scripts/verification_volume_ceiling.sh" "$main_repo" "packages/tests/codex_hooks.test.sh")
pwd_output=$(cd "$pwd_repo" && PLUGIN_DATA="$ceiling_data" run_bash_hook "$HOOKS/scripts/verification_volume_ceiling.sh" "" "packages/tests/codex_hooks.test.sh")
if [[ -z "$workdir_output$cwd_output$pwd_output" ]] &&
  grep -qx 1 "$ceiling_data/verification-ceiling/feature-e5__full-suite.count" &&
  grep -qx 1 "$ceiling_data/verification-ceiling/main__full-suite.count" &&
  grep -qx 1 "$ceiling_data/verification-ceiling/feature-pwd__full-suite.count"; then
  printf 'ok   - verification ceiling uses workdir, cwd, then PWD\n'
else
  printf 'FAIL - verification ceiling uses workdir, cwd, then PWD\n'
  fails=$((fails + 1))
fi

mkdir -p "$test_repo/.codex"
repo_marker="$security_tmp/repo-command-ran"
printf 'printf compromised > "%s"\n' "$repo_marker" >"$test_repo/.codex/test_command"
repo_config_output=$(run_bash_hook "$HOOKS/scripts/test_gate.sh" "$test_repo" "git commit -m test")
check "repository test command is ignored" test ! -e "$repo_marker"
check "missing trusted test command allows commit" test -z "$repo_config_output"

trusted_config=$(git -C "$test_repo" rev-parse --git-path coderails/test_command)
case "$trusted_config" in /*) ;; *) trusted_config="$test_repo/$trusted_config" ;; esac
mkdir -p "$(dirname "$trusted_config")"
trusted_marker="$security_tmp/trusted-command-ran"
printf 'printf trusted > "%s" && test -s "%s"\n' "$trusted_marker" "$trusted_marker" >"$trusted_config"
trusted_output=$(run_bash_hook "$HOOKS/scripts/test_gate.sh" "$test_repo" "git commit -m test")
check "trusted per-worktree test command supports shell syntax" test -e "$trusted_marker"
check "trusted passing test command allows commit" test -z "$trusted_output"
check "trusted command does not fall back to repository file" test ! -e "$repo_marker"
check "test gate does not use eval" sh -c '! grep -Eq "(^|[[:space:]])eval([[:space:]]|$)" "$1"' sh "$HOOKS/scripts/test_gate.sh"
printf 'false\n' >"$trusted_config"
failing_output=$(run_bash_hook "$HOOKS/scripts/test_gate.sh" "$test_repo" "git commit -m test")
check "trusted failing test command denies commit" sh -c 'printf "%s" "$1" | jq -e ".hookSpecificOutput.permissionDecision == \"deny\""' sh "$failing_output"

protected_writes_denied=1
for protected_command in \
  'python3 -c '\''open(".codex/config.toml").read()'\''' \
  'python -c '\''from pathlib import Path; Path("./.codex/requirements.toml").write_text("x")'\''' \
  'pip install -r .codex/requirements.toml' \
  'uv pip install --requirements=./.codex/requirements.toml' \
  'awk '\''{print}'\'' .codex/config.toml' \
  'cat .codex/requirements.toml' \
  'printf x > ./.codex/../.codex/config.toml' \
  'printf x | tee .codex/requirements.toml' \
  'cp source .codex/config.toml' \
  'mv source .codex/requirements.toml' \
  'dd of=.codex/config.toml' \
  'sed -i s/x/y/ .codex/requirements.toml' \
  'perl -i -pe s/x/y/ .codex/config.toml'; do
  protected_output=$(run_bash_hook "$HOOKS/scripts/destructive_bash_gate.sh" "$test_repo" "$protected_command")
  printf '%s' "$protected_output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 ||
    protected_writes_denied=0
done
absolute_config_output=$(run_bash_hook "$HOOKS/scripts/destructive_bash_gate.sh" "$test_repo" "cat $test_repo/.codex/config.toml")
printf '%s' "$absolute_config_output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 ||
  protected_writes_denied=0
check "literal native config paths are denied on every branch" test "$protected_writes_denied" -eq 1

lookalikes_allowed=1
for lookalike_command in \
  'printf x > .codex/config.toml.bak' \
  'cat .codex/requirements.toml.bak' \
  'cat .codexish/config.toml'; do
  lookalike_output=$(run_bash_hook "$HOOKS/scripts/destructive_bash_gate.sh" "$test_repo" "$lookalike_command")
  [[ -z "$lookalike_output" ]] || lookalikes_allowed=0
done
check "similar non-config paths remain allowed" test "$lookalikes_allowed" -eq 1

graph_root="$security_tmp/graph-loops"
graph_dir="$graph_root/fixture/s-complete"
mkdir -p "$graph_dir"
jq -n '{
  schema_version:2,session_id:"s-complete",loop_id:"loop-1",revision:1,status:"in-progress",
  graph:{nodes:{A:{status:"pending",outcome:"pending",retry:{attempts:0,max:2},evidence:[]}},edges:[],joins:{},active_wave:null,hard_stop:null}
}' >"$graph_dir/progress.json"
incomplete_stop=$(printf '%s' '{"session_id":"s-complete","cwd":"/tmp","hook_event_name":"Stop","last_assistant_message":"done"}' | CODERAILS_AGENTIC_LOOP_DIR="$graph_root" PLUGIN_ROOT="$PACKAGE" "$HOOKS/scripts/graph_completion_guard.sh")
check "incomplete native graph blocks Stop" sh -c 'printf "%s" "$1" | jq -e ".decision == \"block\""' sh "$incomplete_stop"
git_head=$(git -C "$ROOT" rev-parse HEAD)
jq -n --arg sha "$git_head" '{schema_version:1,scope:"loop",task_ref:"loop-1",verification_level:0,verification_justification:"hook fixture",frozen_at:"2026-08-20T00:00:00Z",frozen_sha:$sha,head_sha:$sha,session_id:"s-complete",loop_id:"loop-1",revision:1,evals:[],amendments:[],result:null,graded_at:null}' >"$graph_dir/evals.json"
"$ROOT/scripts/post_evals.sh" grade-loop "$graph_dir/evals.json" >/dev/null
jq -n '{session_id:"s-complete",loop_id:"loop-1",proofs:[{id:"P1",cmd:"true",status:"pass",evidence:"observed"}]}' >"$graph_dir/proof.json"
jq -n '{schema_version:2,session_id:"s-complete",loop_id:"loop-1",status:"complete"}' >"$graph_dir/retro.json"
proof_transcript="$graph_dir/transcript.jsonl"
jq -cn '{type:"response_item",payload:{type:"custom_tool_call",name:"exec",call_id:"proof-call",input:"const r = await tools.exec_command({cmd:\"true\"}); text(JSON.stringify({exit_code:r.exit_code,output:r.output}));"}}' >"$proof_transcript"
jq -cn '{type:"response_item",payload:{type:"custom_tool_call_output",call_id:"proof-call",output:[{type:"input_text",text:"{\"exit_code\":0,\"output\":\"\"}"}]}}' >>"$proof_transcript"
jq '.graph.nodes.A.status="done" | .graph.nodes.A.outcome="done"' "$graph_dir/progress.json" >"$graph_dir/done.json"
mv "$graph_dir/done.json" "$graph_dir/progress.json"
python3 "$PACKAGE/skills/agentic-loop/scripts/graph.py" complete "$graph_dir/progress.json" --session s-complete --evals "$graph_dir/evals.json" --proof "$graph_dir/proof.json" --retro "$graph_dir/retro.json" --transcript "$proof_transcript" >/dev/null
complete_stop=$(jq -cn --arg transcript "$proof_transcript" '{session_id:"s-complete",cwd:"/tmp",hook_event_name:"Stop",last_assistant_message:"done",transcript_path:$transcript}' | CODERAILS_AGENTIC_LOOP_DIR="$graph_root" PLUGIN_ROOT="$PACKAGE" "$HOOKS/scripts/graph_completion_guard.sh")
check "completed native graph allows Stop" test -z "$complete_stop"
jq -cn '{type:"response_item",payload:{type:"custom_tool_call",name:"exec",call_id:"proof-outer-only",input:"const r = await tools.exec_command({cmd:\"true\"}); text(r.output);"}}' >>"$proof_transcript"
jq -cn '{type:"response_item",payload:{type:"custom_tool_call_output",call_id:"proof-outer-only",output:[{type:"input_text",text:"Script completed\nWall time 0.1 seconds\nProcess exited with code 1\nFinal output:"}]}}' >>"$proof_transcript"
outer_only_stop=$(jq -cn --arg transcript "$proof_transcript" '{session_id:"s-complete",cwd:"/tmp",hook_event_name:"Stop",last_assistant_message:"done",transcript_path:$transcript}' | CODERAILS_AGENTIC_LOOP_DIR="$graph_root" PLUGIN_ROOT="$PACKAGE" "$HOOKS/scripts/graph_completion_guard.sh")
check "completed native graph rejects outer-only Script completed proof" sh -c 'printf "%s" "$1" | jq -e ".decision == \"block\""' sh "$outer_only_stop"
jq -cn '{type:"response_item",payload:{type:"custom_tool_call",name:"exec",call_id:"proof-failed",input:"const r = await tools.exec_command({cmd:\"true\"}); text(JSON.stringify({exit_code:r.exit_code,output:r.output}));"}}' >>"$proof_transcript"
jq -cn '{type:"response_item",payload:{type:"custom_tool_call_output",call_id:"proof-failed",output:[{type:"input_text",text:"{\"exit_code\":1,\"output\":\"\"}"}]}}' >>"$proof_transcript"
failed_proof_stop=$(jq -cn --arg transcript "$proof_transcript" '{session_id:"s-complete",cwd:"/tmp",hook_event_name:"Stop",last_assistant_message:"done",transcript_path:$transcript}' | CODERAILS_AGENTIC_LOOP_DIR="$graph_root" PLUGIN_ROOT="$PACKAGE" "$HOOKS/scripts/graph_completion_guard.sh")
check "completed native graph rejects a last-failed proof command" sh -c 'printf "%s" "$1" | jq -e ".decision == \"block\""' sh "$failed_proof_stop"

check "unsupported subagent detection is absent" sh -c '! grep -R -E "agent_id" "$1"' sh "$HOOKS"
check "hook text names only native orchestration" sh -c '! grep -R -E "[Aa]gent tool" "$1"' sh "$HOOKS"

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS\n'
  exit 0
fi
printf 'FAILED (%s)\n' "$fails"
exit 1
