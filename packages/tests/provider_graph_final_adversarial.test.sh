#!/usr/bin/env bash
# Final production-path adversarial checks for the independent Claude and Codex graphs.
# shellcheck disable=SC2329 # Assertion callbacks are invoked indirectly through "$@".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -r "$TMP"' EXIT
FAILS=0
CLAUDE_GRAPH="$ROOT/hooks/scripts/lib/graph_dispatch.sh"
CODEX_PACKAGE="$ROOT/packages/codex"
CODEX_GRAPH="$CODEX_PACKAGE/skills/agentic-loop/scripts/graph.py"

# shellcheck disable=SC1090 # Fixed production path under the repository root.
source "$CLAUDE_GRAPH"

pass() { printf 'ok   - %s\n' "$1"; }
fail() {
	printf 'FAIL - %s\n      %s\n' "$1" "$2"
	FAILS=$((FAILS + 1))
}
expect_ok() {
	local name="$1" output
	shift
	if output=$("$@" 2>&1); then pass "$name"; else fail "$name" "$output"; fi
}
expect_rejected() {
	local name="$1" output
	shift
	if output=$("$@" 2>&1); then fail "$name" "unexpected success: $output"; else pass "$name"; fi
}
node() {
	local status="${1:-pending}"
	jq -cn --arg status "$status" '{status:$status,outcome:$status,retry:{attempts:0,max:2},evidence:[]}'
}
write_state() {
	local path="$1" provider="$2" status="${3:-pending}" revision="${4:-1}"
	local active_wave=null
	[[ "$status" != "running" ]] || {
		if [[ "$provider" == "claude" ]]; then
			active_wave=$(jq -cn --argjson revision "$revision" '{wave_id:("wave-"+($revision|tostring)),revision:$revision,nodes:["A"]}')
		else
			active_wave=$(jq -cn --argjson revision "$revision" '{id:("wave-"+($revision|tostring)),revision:$revision,nodes:["A"]}')
		fi
	}
	jq -n --arg status "$status" --argjson revision "$revision" --argjson active "$active_wave" \
		--argjson a "$(node "$status")" '{
          schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:$revision,status:"in-progress",
          work_units:{one:{status:"pending"},two:{status:"pending"},three:{status:"pending"}},
          graph:{nodes:{A:$a},edges:[],joins:{},active_wave:$active,hard_stop:null}
        }' >"$path"
}
write_evals() {
	local path="$1" revision="$2" grader="${3:-$ROOT/scripts/post_evals.sh}" sha
	sha=$(git -C "$ROOT" rev-parse HEAD)
	jq -n --arg sha "$sha" --argjson revision "$revision" '{
          schema_version:1,scope:"loop",task_ref:"loop-test",verification_level:0,
          verification_justification:"final adversarial fixture",frozen_at:"2026-08-20T00:00:00Z",
          frozen_sha:$sha,head_sha:$sha,session_id:"session-test",loop_id:"loop-test",
          revision:$revision,evals:[],amendments:[],result:null,graded_at:null
        }' >"$path"
	"$grader" grade-loop "$path" >/dev/null
}
write_completion_evidence() {
	local proof="$1" retro="$2" transcript="${3:-}"
	jq -n '{session_id:"session-test",loop_id:"loop-test",proofs:[{id:"P1",cmd:"true",status:"pass",evidence:"observed"}]}' >"$proof"
	jq -n '{schema_version:2,session_id:"session-test",loop_id:"loop-test",status:"complete"}' >"$retro"
	[[ -z "$transcript" ]] || printf '%s\n' \
		'{"type":"function_call","name":"exec_command","call_id":"proof-1","arguments":"{\"cmd\":\"true\"}"}' \
		'{"type":"function_call_output","call_id":"proof-1","output":"{\"exit_code\":0}"}' >"$transcript"
}
claude_complete() {
	graph_dispatch_complete "$1" --session session-test --evals "$2" --proof "$3" --retro "$4"
}
claude_guard_denied() {
	local root="$1" state="$2" evals="$3" wave revision input output dir
	wave=$(jq -r '.graph.active_wave.wave_id' "$state")
	revision=$(jq -r '.revision' "$state")
	dir="$root/fixture/session-test"
	mkdir -p "$dir"
	cp "$state" "$dir/progress.json"
	cp "$evals" "$dir/evals.json"
	input=$(jq -cn --arg cwd "$ROOT" --arg wave "$wave" --argjson revision "$revision" '{
      tool_name:"Agent",session_id:"session-test",cwd:$cwd,
      tool_input:{subagent_type:"coderails:loop-worker",prompt:("CODERAILS_GRAPH_DISPATCH="+({session_id:"session-test",loop_id:"loop-test",revision:$revision,wave_id:$wave,node_id:"A"}|tojson))}}
    ')
	output=$(printf '%s' "$input" | CLAUDE_AGENTIC_LOOP_DIR="$root" CLAUDE_DISCIPLINE_LOG="$TMP/claude.log" \
		"$ROOT/hooks/scripts/loop_dispatch_guard.sh")
	printf '%s' "$output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}

test_claude_stable_dispatch_exact_completion() {
	local state="$TMP/claude-lifecycle.json" evals="$TMP/claude-lifecycle-evals.json"
	local proof="$TMP/claude-lifecycle-proof.json" retro="$TMP/claude-lifecycle-retro.json" wave
	write_state "$state" claude
	write_evals "$evals" 1
	graph_dispatch_begin_wave "$state" >/dev/null
	if claude_guard_denied "$TMP/claude-guard" "$state" "$evals"; then
		fail "Claude dispatch accepts stable loop eval identity after begin-wave" "stable graded evals were rejected after graph revision advanced"
	else
		pass "Claude dispatch accepts stable loop eval identity after begin-wave"
	fi
	wave=$(jq -r '.graph.active_wave.wave_id' "$state")
	graph_dispatch_record "$state" "{\"wave_id\":\"$wave\",\"results\":{\"A\":{\"outcome\":\"done\",\"evidence\":\"done\"}}}" >/dev/null
	write_completion_evidence "$proof" "$retro"
	expect_rejected "Claude completion remains exact-revision-bound" claude_complete "$state" "$evals" "$proof" "$retro"
	write_evals "$evals" "$(jq -r '.revision' "$state")"
	expect_ok "Claude completion accepts exact current revision" claude_complete "$state" "$evals" "$proof" "$retro"
}

test_codex_proof_loop_binding() {
	local state="$TMP/codex-replay.json" evals="$TMP/codex-replay-evals.json"
	local proof="$TMP/codex-replay-proof.json" retro="$TMP/codex-replay-retro.json" transcript="$TMP/codex-replay.jsonl"
	write_state "$state" codex "done"
	write_evals "$evals" 1
	write_completion_evidence "$proof" "$retro"
	printf '%s\n' \
		'{"type":"turn_context","payload":{"session_id":"session-test","loop_id":"loop-old"}}' \
		'{"type":"function_call","name":"exec_command","call_id":"old-proof","arguments":"{\"cmd\":\"true\"}"}' \
		'{"type":"function_call_output","call_id":"old-proof","output":"{\"exit_code\":0}"}' >"$transcript"
	expect_rejected "Codex rejects same-session proof replay from an earlier loop" \
		python3 "$CODEX_GRAPH" complete "$state" --session session-test --evals "$evals" \
		--proof "$proof" --retro "$retro" --transcript "$transcript"
}

test_claude_state_validation() {
	local base="$TMP/claude-valid.json" state mutation
	write_state "$base" claude
	for mutation in schema status missing-evidence object-evidence; do
		state="$TMP/claude-$mutation.json"
		case "$mutation" in
		schema) jq '.schema_version=1' "$base" >"$state" ;;
		status) jq '.status="bogus"' "$base" >"$state" ;;
		missing-evidence) jq 'del(.graph.nodes.A.evidence)' "$base" >"$state" ;;
		object-evidence) jq '.graph.nodes.A.evidence={}' "$base" >"$state" ;;
		esac
		expect_rejected "Claude rejects malformed graph: $mutation" graph_dispatch_inspect "$state"
	done
}

test_claude_completion_grading() {
	local state="$TMP/claude-grade.json" evals="$TMP/claude-grade-evals.json"
	local proof="$TMP/claude-grade-proof.json" retro="$TMP/claude-grade-retro.json" checksum
	write_state "$state" claude "done"
	write_evals "$evals" 1
	write_completion_evidence "$proof" "$retro"
	checksum=$(printf '[]\nNO-GO' | shasum -a 256 | awk '{print $1}')
	jq --arg checksum "$checksum" '.result="NO-GO" | .grading={by:"post_evals.sh grade-loop",checksum:$checksum,amendments_at_grade:0}' \
		"$evals" >"$evals.tmp" && mv "$evals.tmp" "$evals"
	expect_rejected "Claude rejects verification-level-0 NO-GO" claude_complete "$state" "$evals" "$proof" "$retro"
	write_evals "$evals" 1
	jq '.grading={by:"forged",checksum:"forged",amendments_at_grade:0}' "$evals" >"$evals.tmp" && mv "$evals.tmp" "$evals"
	expect_rejected "Claude rejects forged grading" claude_complete "$state" "$evals" "$proof" "$retro"
}

test_claude_native_routing() {
	local docs="$ROOT/skills/agentic-loop/execution-graph.md" dispatch="$ROOT/hooks/scripts/lib/graph_dispatch.sh"
	if rg -q 'real `Agent` call|own Agent tool calls' "$docs" "$dispatch" &&
		! rg -q 'spawn-sandboxed-worker\.sh|claude -p' "$docs"; then
		pass "Claude graph routing uses native Agent only"
	else
		fail "Claude graph routing uses native Agent only" "graph documentation routes through a nested/sandbox worker path"
	fi
}

test_clean_cache_codex_lifecycle() {
	local cache="$TMP/cache/coderails/coderails-codex/0.2.0" state="$TMP/cache-state.json"
	local evals="$TMP/cache-evals.json" proof="$TMP/cache-proof.json" retro="$TMP/cache-retro.json" transcript="$TMP/cache.jsonl"
	local graph grader task revision
	mkdir -p "$(dirname "$cache")"
	cp -R "$CODEX_PACKAGE" "$cache"
	graph="$cache/skills/agentic-loop/scripts/graph.py"
	grader="$cache/scripts/post_evals.sh"
	write_state "$state" codex
	if ! write_evals "$evals" 1 "$grader"; then
		fail "clean-cache Codex package exposes grade-loop" "installed post_evals.sh grade-loop failed"
		return
	fi
	python3 "$graph" begin-wave "$state" >/dev/null
	task="loop_worker_41"
	expect_ok "clean-cache Codex authorizes exact owned dispatch" python3 "$graph" authorize-dispatch "$state" \
		--session session-test --task "$task" --evals "$evals"
	python3 "$graph" record-wave "$state" '{"wave_id":"wave-2","results":{"A":{"outcome":"done","evidence":"done"}}}' >/dev/null
	revision=$(jq -r '.revision' "$state")
	write_evals "$evals" "$revision" "$grader"
	write_completion_evidence "$proof" "$retro" "$transcript"
	expect_ok "clean-cache Codex completes exact owned lifecycle" python3 "$graph" complete "$state" \
		--session session-test --evals "$evals" --proof "$proof" --retro "$retro" --transcript "$transcript"
}

test_claude_stable_dispatch_exact_completion
test_codex_proof_loop_binding
test_claude_state_validation
test_claude_completion_grading
test_claude_native_routing
test_clean_cache_codex_lifecycle

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS - provider graph final adversarial contract\n'
	exit 0
fi
printf 'FAILED - provider graph final adversarial contract (%s cases)\n' "$FAILS"
exit 1
