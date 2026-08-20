#!/usr/bin/env bash
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
  local hook="$1" cwd="$2" command="$3"
  jq -nc --arg cwd "$cwd" --arg command "$command" '{
    session_id: "s1",
    cwd: $cwd,
    hook_event_name: "PreToolUse",
    tool_name: "Bash",
    tool_input: {command: $command}
  }' | "$hook"
}

check "hooks.json parses" jq -e . "$HOOKS/hooks.json"
check "native matcher names" jq -e '
  [.hooks.PreToolUse[].matcher] == ["^Bash$", "^request_user_input$", "^apply_patch$"] and
  [.hooks.PostToolUse[].matcher] == ["^apply_patch$"]
' "$HOOKS/hooks.json"
check "all commands use PLUGIN_ROOT" jq -e '
  [.hooks[][] | .hooks[] | .command] | all(test("^\\\"\\$\\{PLUGIN_ROOT\\}/hooks/scripts/[^\\\"]+\\\"$"))
' "$HOOKS/hooks.json"
check "no legacy plugin-root variables" sh -c '! grep -R -E "CLAUDE_PLUGIN_ROOT|CODEX_PLUGIN_ROOT" "$1"' sh "$HOOKS"
check "no lifecycle adapter" test ! -e "$HOOKS/lifecycle.py"
check "no graph or parallel hooks" sh -c '! grep -R -E "graph_|parallel-review|parallel_review|enforce_pr_workflow|loop_state_guard" "$1"' sh "$HOOKS"

missing=0
while IFS= read -r command; do
  relative=$(printf '%s' "$command" | sed -e 's#^"${PLUGIN_ROOT}/##' -e 's#"$##')
  [[ -x "$PACKAGE/$relative" ]] || missing=1
done < <(jq -r '.hooks[][] | .hooks[] | .command' "$HOOKS/hooks.json")
check "hook command paths exist" test "$missing" -eq 0

bootstrap=$(printf '%s' '{"session_id":"s1","cwd":"/tmp","hook_event_name":"SessionStart","source":"startup"}' | PLUGIN_ROOT="$PACKAGE" "$HOOKS/scripts/inject_bootstrap.sh")
check "bootstrap returns native orchestration guidance" sh -c 'printf "%s" "$1" | jq -e ".hookSpecificOutput.additionalContext | contains(\"using-coderails\") and contains(\"top-level session as the orchestrator\") and contains(\"delegate do-work tool calls with spawn_agent\")"' sh "$bootstrap"

destructive=$(printf '%s' '{"session_id":"s1","cwd":"/tmp","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/example"}}' | "$HOOKS/scripts/destructive_bash_gate.sh")
check "destructive Bash is denied" sh -c 'printf "%s" "$1" | jq -e ".hookSpecificOutput.permissionDecision == \"deny\""' sh "$destructive"

security_tmp=$(mktemp -d "${TMPDIR:-/tmp}/coderails-codex-hooks.XXXXXX")
trap 'rm -rf "$security_tmp"' EXIT
test_repo="$security_tmp/repo"
git init -q "$test_repo"
git -C "$test_repo" symbolic-ref HEAD refs/heads/feature/native-config-probes

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
  printf '%s' "$protected_output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 \
    || protected_writes_denied=0
done
absolute_config_output=$(run_bash_hook "$HOOKS/scripts/destructive_bash_gate.sh" "$test_repo" "cat $test_repo/.codex/config.toml")
printf '%s' "$absolute_config_output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1 \
  || protected_writes_denied=0
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

check "unsupported subagent detection is absent" sh -c '! grep -R -E "agent_id" "$1"' sh "$HOOKS"
check "all hook text avoids Agent tool wording" sh -c '! grep -R -F "Agent tool" "$1"' sh "$HOOKS"

if [[ "$fails" -eq 0 ]]; then
  printf 'PASS\n'
  exit 0
fi
printf 'FAILED (%s)\n' "$fails"
exit 1
