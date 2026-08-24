#!/usr/bin/env bash
# Frozen native Codex graph contracts from exact-head adversarial review.
# shellcheck disable=SC2329 # Contract callbacks are invoked indirectly by check.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGE="$ROOT/packages/codex"
GRAPH="$PACKAGE/skills/agentic-loop/scripts/graph.py"
SHAPES="$ROOT/packages/tests/codex_graph_evidence_shapes.test.sh"
HOOKS="$PACKAGE/hooks/scripts"
TMP="$(mktemp -d)"
trap 'rm -r "$TMP"' EXIT
export HOME="$TMP/home"
# shellcheck source=packages/tests/lib/codex_transcript_fixture.sh
source "$ROOT/packages/tests/lib/codex_transcript_fixture.sh"
codex_fixture::init session-test
FAILS=0
CONTROL_FAILED=0
FAILED_CASES=()

pass() { printf 'ok   - %s\n' "$1"; }
fail() {
	local name="$1" detail="$2"
	printf 'FAIL - %s\n       %s\n' "$name" "$detail"
	FAILED_CASES+=("$name")
	FAILS=$((FAILS + 1))
}
check() {
	local name="$1" function="$2" output
	if output=$("$function" 2>&1); then
		pass "$name"
	else
		fail "$name" "${output:-contract was not enforced}"
	fi
}

node() {
	local status="${1:-pending}"
	jq -cn --arg status "$status" \
		'{status:$status,outcome:$status,retry:{attempts:0,max:2},evidence:[]}'
}

write_graph() {
	local path="$1" nodes="$2" edges="${3:-[]}" joins="${4:-}"
	[[ -n "$joins" ]] || joins='{}'
	jq -n --argjson nodes "$nodes" --argjson edges "$edges" --argjson joins "$joins" '{
      schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:1,status:"in-progress",
      graph:{nodes:$nodes,edges:$edges,joins:$joins,active_wave:null,hard_stop:null}
    }' >"$path"
}

write_evals() {
	local path="$1" revision="$2"
	jq -n --argjson revision "$revision" --arg sha "$(git -C "$ROOT" rev-parse HEAD)" '{
      schema_version:1,scope:"loop",task_ref:"loop-test",verification_level:0,
      verification_justification:"native graph adversarial fixture",
      frozen_at:"2026-08-20T00:00:00Z",frozen_sha:$sha,head_sha:$sha,
      session_id:"session-test",loop_id:"loop-test",revision:$revision,
      evals:[],amendments:[],result:"VERIFICATION_LEVEL0",graded_at:"2026-08-20T00:00:01Z",
      grading:{by:"post_evals.sh grade-loop",checksum:"0e7a6c2b4c5698e9b454f904a01cca76c7e02ff4bc77ffa030a72ce24a65dde3",amendments_at_grade:0}
    }' >"$path"
}

write_completion_evidence() {
	local proof="$1" retro="$2" command="$3"
	jq -n --arg command "$command" '{
      schema_version:1,session_id:"session-test",loop_id:"loop-test",
      proofs:[{id:"P1",claim:"production command result",cmd:$command,expect:"exit 0",status:"pass",evidence:"observed in native rollout"}]
    }' >"$proof"
	jq -n '{schema_version:2,session_id:"session-test",loop_id:"loop-test",status:"complete"}' >"$retro"
}

command_rejected_unchanged() {
	local state="$1" before="$TMP/before.$RANDOM" output="$TMP/output.$RANDOM"
	shift
	cp "$state" "$before"
	if "$@" >"$output" 2>&1; then
		printf 'unexpected success: %s' "$(tr '\n' ' ' <"$output")"
		return 1
	fi
	if ! cmp -s "$before" "$state"; then
		printf 'rejection changed graph state'
		return 1
	fi
}

reset_transcript() {
	rm -r "$HOME/.codex/sessions"
	codex_fixture::init session-test
}

record_payload() {
	local state="$1" outcome="${2:-done}" wave
	wave=$(jq -r '.graph.active_wave.id' "$state")
	jq -cn --arg wave "$wave" --arg outcome "$outcome" \
		'{wave_id:$wave,results:{A:{outcome:$outcome,evidence:"checked"}}}'
}

test_transcript_evidence_rejections() {
	local state reference child parent call old_agent payload

	reset_transcript
	state="$TMP/evidence-missing.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	payload=$(record_payload "$state")
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$payload"

	reset_transcript
	state="$TMP/evidence-duplicate.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	codex_fixture::append_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	codex_fixture::append_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	payload=$(record_payload "$state")
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$payload"

	reset_transcript
	state="$TMP/evidence-foreign.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	child="$(dirname "$(codex_fixture::parent session-test)")/rollout-fixture-$(jq -r '.agent_thread_id' <<<"$reference").jsonl"
	jq -c 'if .type == "session_meta" then .payload.parent_thread_id="foreign" else . end' "$child" >"$child.tmp"
	mv "$child.tmp" "$child"
	payload=$(record_payload "$state")
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$payload"

	reset_transcript
	state="$TMP/evidence-stale.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	codex_fixture::append_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	payload=$(record_payload "$state")
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$payload"

	reset_transcript
	state="$TMP/evidence-failed.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	child="$(dirname "$(codex_fixture::parent session-test)")/rollout-fixture-$(jq -r '.agent_thread_id' <<<"$reference").jsonl"
	jq -c 'if .payload.type == "task_complete" then .payload.type="turn_aborted" else . end' "$child" >"$child.tmp"
	mv "$child.tmp" "$child"
	payload=$(record_payload "$state")
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$payload"

	reset_transcript
	state="$TMP/evidence-reused.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	codex_fixture::append_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	python3 "$GRAPH" record-wave "$state" "$(record_payload "$state" failed)" >/dev/null
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 2 wave-4)
	old_agent=$(jq -r '.graph.nodes.A.evidence[] | select(type == "object") | .agent_thread_id' "$state")
	call=$(jq -r '.spawn_call_id' <<<"$reference")
	parent=$(codex_fixture::parent session-test)
	jq -c --arg call "$call" --arg agent "$old_agent" \
		'if .payload.item.id == $call then .payload.item.agent_thread_id=$agent else . end' "$parent" >"$parent.tmp"
	mv "$parent.tmp" "$parent"
	payload=$(record_payload "$state")
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$payload"
}

validate_worker_refs() {
	PYTHONPATH="$(dirname "$GRAPH")" python3 -c \
		'import json,sys; from graph_evidence import validate_worker_evidence; validate_worker_evidence(json.load(open(sys.argv[1], encoding="utf-8")))' "$1"
}

test_evidence_shape_normalization() {
	bash "$SHAPES"
}

test_wave_tamper_and_followup() {
	local state reference followup payload

	reset_transcript
	state="$TMP/wave-tamper.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	codex_fixture::append_wave "$state"
	python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")" >/dev/null
	jq '(.graph.nodes.A.evidence[] | select(type == "object")).wave_id="wave-999"' "$state" >"$state.tmp"
	mv "$state.tmp" "$state"
	command_rejected_unchanged "$state" validate_worker_refs "$state"

	reset_transcript
	state="$TMP/followup-success.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	followup=$(codex_fixture::append_followup session-test "$reference")
	python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")" >/dev/null
	[[ "$(jq -r '.graph.nodes.A.evidence[] | select(type == "object") | .task_complete_turn_id' "$state")" == "$followup" ]]

	reset_transcript
	state="$TMP/followup-failed.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	codex_fixture::append_followup session-test "$reference" turn_aborted >/dev/null
	payload=$(record_payload "$state")
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$payload"

	reset_transcript
	state="$TMP/followup-stale.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")" >/dev/null
	codex_fixture::append_followup session-test "$reference" >/dev/null
	command_rejected_unchanged "$state" validate_worker_refs "$state"
}

install_state() {
	local source="$1" root="$2"
	mkdir -p "$root/fixture/session-test"
	cp "$source" "$root/fixture/session-test/progress.json"
}

hook_output() {
	local hook="$1" root="$2" input="$3"
	printf '%s' "$input" | HOME="$TMP/home" PLUGIN_DATA="$TMP/plugin-data" \
		CODERAILS_AGENTIC_LOOP_DIR="$root" CODERAILS_DISCIPLINE_LOG="$TMP/discipline.log" \
		PLUGIN_ROOT="$PACKAGE" "$hook"
}

hook_denied() {
	local root="$1" input="$2" output
	output=$(hook_output "$HOOKS/loop_dispatch_guard.sh" "$root" "$input")
	printf '%s' "$output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}

dispatch_input() {
	local task="$1"
	jq -cn --arg cwd "$ROOT" --arg task "$task" '{
      hook_event_name:"PreToolUse",tool_name:"spawn_agent",session_id:"session-test",cwd:$cwd,
      tool_input:{task_name:$task,message:"Implement the owned native graph node."}
    }'
}

stop_blocked() {
	local root="$1" message="$2" output
	output=$(hook_output "$HOOKS/graph_completion_guard.sh" "$root" \
		"$(jq -cn --arg cwd "$ROOT" --arg message "$message" '{
          hook_event_name:"Stop",session_id:"session-test",cwd:$cwd,last_assistant_message:$message
        }')")
	printf '%s' "$output" | jq -e '.decision == "block"' >/dev/null 2>&1
}

test_inner_proof_failure() {
	local state="$TMP/proof-state.json" evals="$TMP/proof-evals.json"
	local proof="$TMP/proof.json" retro="$TMP/proof-retro.json" transcript="$TMP/proof-rollout.jsonl"
	write_graph "$state" "$(jq -cn --argjson a "$(node "done")" '{A:$a}')"
	write_evals "$evals" 1
	write_completion_evidence "$proof" "$retro" false
	jq -cn '{type:"custom_tool_call",name:"exec",call_id:"proof-call",input:"const r = await tools.exec_command({cmd: \"false\"}); text(r.output);"}' >"$transcript"
	jq -cn --arg output $'Script completed\nWall time 0.1 seconds\nProcess exited with code 1\nFinal output:' \
		'{type:"custom_tool_call_output",call_id:"proof-call",output:$output}' >>"$transcript"
	command_rejected_unchanged "$state" python3 "$GRAPH" complete "$state" --session session-test \
		--evals "$evals" --proof "$proof" --retro "$retro" --transcript "$transcript"
}

test_released_join_inputs() {
	local state="$TMP/join.json" nodes joins
	nodes=$(jq -cn --argjson a "$(node)" --argjson j "$(node "done")" --argjson c "$(node)" '{A:$a,J:$j,C:$c}')
	joins='{"J":{"mode":"all","inputs":["A"],"released":true}}'
	write_graph "$state" "$nodes" '[{"from":"J","to":"C"}]' "$joins"
	command_rejected_unchanged "$state" python3 "$GRAPH" begin-wave "$state"
}

test_completed_dispatch_boundary() {
	local state="$TMP/complete-dispatch.json" root="$TMP/complete-dispatch-root"
	write_graph "$state" "$(jq -cn --argjson a "$(node "done")" '{A:$a}')"
	jq '.status="complete" | .revision=2 | .completion={revision:1}' "$state" >"$state.tmp"
	mv "$state.tmp" "$state"
	install_state "$state" "$root"
	if ! hook_denied "$root" "$(dispatch_input loop_worker_41)"; then
		printf 'completed graph-named spawn_agent was allowed'
		return 1
	fi
	if hook_denied "$root" "$(dispatch_input source_auditor)"; then
		printf 'unrelated native spawn_agent was denied'
		return 1
	fi
}

test_stable_eval_identity() {
	local root="$TMP/stable-evals-root"
	local state="$root/fixture/session-test/progress.json" evals="$root/fixture/session-test/evals.json"
	local stale="$TMP/stale-completion.json"
	local stale_evals="$TMP/stale-evals.json" proof="$TMP/stale-proof.json"
	local retro="$TMP/stale-retro.json" transcript="$TMP/stale-rollout.jsonl"
	mkdir -p "$(dirname "$state")"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	write_evals "$evals" 1
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	if hook_denied "$root" "$(dispatch_input loop_worker_41)"; then
		printf 'begin-wave invalidated evals graded for the same stable loop identity'
		return 1
	fi

	write_graph "$stale" "$(jq -cn --argjson a "$(node "done")" '{A:$a}')"
	jq '.revision=2' "$stale" >"$stale.tmp"
	mv "$stale.tmp" "$stale"
	write_evals "$stale_evals" 1
	write_completion_evidence "$proof" "$retro" true
	jq -cn '{type:"function_call",name:"exec_command",call_id:"stale-proof",arguments:"{\"cmd\":\"true\"}"}' >"$transcript"
	jq -cn '{type:"function_call_output",call_id:"stale-proof",output:"{\"exit_code\":0}"}' >>"$transcript"
	command_rejected_unchanged "$stale" python3 "$GRAPH" complete "$stale" --session session-test \
		--evals "$stale_evals" --proof "$proof" --retro "$retro" --transcript "$transcript"
}

test_bootstrap_exact_path() {
	local state="$TMP/bootstrap.json" root="$TMP/bootstrap-root" installed output context
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	install_state "$state" "$root"
	installed="$root/fixture/session-test/progress.json"
	output=$(hook_output "$HOOKS/inject_bootstrap.sh" "$root" \
		"$(jq -cn --arg cwd "$ROOT" '{hook_event_name:"SessionStart",session_id:"session-test",cwd:$cwd}')")
	context=$(printf '%s' "$output" | jq -r '.hookSpecificOutput.additionalContext // empty')
	if [[ "$context" != *"$installed"* ]]; then
		printf 'SessionStart omitted resolved path: %s' "$installed"
		return 1
	fi
}

test_hard_stop_final_line() {
	local state="$TMP/hard-stop.json" root="$TMP/hard-stop-root"
	write_graph "$state" "$(jq -cn --argjson a "$(node hard-stop)" '{A:$a}')"
	jq '.graph.hard_stop={node:"A",reason:"retry exhaustion",evidence:"observed failure"}' "$state" >"$state.tmp"
	mv "$state.tmp" "$state"
	install_state "$state" "$root"
	if ! stop_blocked "$root" $'LOOP-STOP: waiting-on-human\nThis final line is not a declaration.'; then
		printf 'non-final LOOP-STOP marker waived the hard stop'
		return 1
	fi
	if stop_blocked "$root" $'Hard stop recorded.\n\nLOOP-STOP: waiting-on-human\n\n'; then
		printf 'valid final nonblank LOOP-STOP declaration was blocked'
		return 1
	fi
}

test_graph_error_boundary() {
	PYTHONPATH="$(dirname "$GRAPH")" python3 -c 'import argparse, graph, unittest; from graph_identity import GraphError
graph._parser = lambda: argparse.Namespace(parse_args=lambda: argparse.Namespace(command="inspect", state=None)); graph._inspect = lambda _: (_ for _ in ()).throw(GraphError("expected")); assert graph.main() == 1
graph._inspect = lambda _: (_ for _ in ()).throw(ValueError("unexpected")); unittest.TestCase().assertRaises(ValueError, graph.main)'
}

mutation_control() {
	local mutation="$TMP/mutated-production" original="$TMP/control-original.json"
	local mutated="$TMP/control-mutated.json" envelope wave
	mkdir -p "$mutation"
	cp "$PACKAGE/skills/agentic-loop/scripts/graph_evidence.py" "$mutation/graph_evidence.py"
	cp "$PACKAGE/skills/agentic-loop/scripts/graph_identity.py" "$mutation/graph_identity.py"
	sed 's/if set(results) != set(active_wave\["nodes"\]):/if False:/' "$GRAPH" >"$mutation/graph.py"
	chmod +x "$mutation/graph.py"
	if ! grep -q 'if False:' "$mutation/graph.py"; then
		printf 'MUTATION CONTROL FAIL - production result-key check was not mutated\n'
		CONTROL_FAILED=1
		return
	fi
	write_graph "$original" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$original" >/dev/null
	codex_fixture::append_wave "$original"
	cp "$original" "$mutated"
	wave=$(jq -r '.graph.active_wave.id' "$original")
	envelope=$(jq -cn --arg wave "$wave" '{wave_id:$wave,results:{}}')
	if command_rejected_unchanged "$original" python3 "$GRAPH" record-wave "$original" "$envelope" &&
		python3 "$mutation/graph.py" record-wave "$mutated" "$envelope" >/dev/null 2>&1; then
		printf 'ok   - mutation control detects disabled production active-wave result check\n'
	else
		printf 'MUTATION CONTROL FAIL - copied production mutation did not flip the contract\n'
		CONTROL_FAILED=1
	fi
}

check 'inner failed proof cannot pass through outer Script completed' test_inner_proof_failure
check 'released join requires every input terminal-success' test_released_join_inputs
check 'completed graph denies graph-named spawn and allows unrelated spawn' test_completed_dispatch_boundary
check 'stable loop evals survive begin-wave while completion stays revision-bound' test_stable_eval_identity
check 'SessionStart includes the exact resolved progress.json path' test_bootstrap_exact_path
check 'hard-stop waiver requires a final nonblank LOOP-STOP declaration' test_hard_stop_final_line
check 'CLI handles GraphError but lets unexpected ValueError escape' test_graph_error_boundary
check 'native transcript evidence rejects missing, duplicate, foreign, stale, failed, and reused records' test_transcript_evidence_rejections
check 'stored waves reject tampering and child follow-ups require the final successful completion' test_wave_tamper_and_followup
check 'worker evidence shapes are classified recursively without rejecting benign nesting' test_evidence_shape_normalization
mutation_control

if [[ "$FAILS" -eq 0 && "$CONTROL_FAILED" -eq 0 ]]; then
	printf 'PASS - native Codex graph runtime adversarial contract\n'
	exit 0
fi
printf 'FAILED - native Codex graph runtime adversarial contract (%s cases)\n' "$FAILS"
if [[ "$FAILS" -gt 0 ]]; then
	printf 'Failing cases:\n'
	printf ' - %s\n' "${FAILED_CASES[@]}"
fi
exit 1
