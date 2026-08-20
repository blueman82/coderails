#!/usr/bin/env bash
# Frozen adversarial graph cases from the exact-head review of PR #428.
# shellcheck disable=SC2329 # Assertion callbacks are invoked through "$@".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -r "$TMP"' EXIT
FAILS=0
PROVIDER=""

pass() { printf 'ok   - %s: %s\n' "$PROVIDER" "$1"; }
fail() {
	printf 'FAIL - %s: %s\n      %s\n' "$PROVIDER" "$1" "$2"
	FAILS=$((FAILS + 1))
}
expect_rejected() {
	local name="$1" state="$2" before="$TMP/before.$RANDOM" output
	shift 2
	cp "$state" "$before"
	if output=$("$@" 2>&1); then
		fail "$name" "unexpected success: $output"
	elif cmp -s "$before" "$state"; then
		pass "$name"
	else
		fail "$name" "rejection changed state: $output"
	fi
}
expect_allowed() {
	local name="$1"
	shift
	if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name" "unexpected rejection"; fi
}

node() {
	local status="${1:-pending}" outcome="${2:-${1:-pending}}"
	jq -cn --arg status "$status" --arg outcome "$outcome" \
		'{status:$status,outcome:$outcome,retry:{attempts:0,max:2},evidence:[]}'
}
write_graph() {
	local path="$1" nodes="$2" edges="${3:-[]}" hard_stop="${4:-null}"
	jq -n --argjson nodes "$nodes" --argjson edges "$edges" --argjson stop "$hard_stop" '{
      schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:1,status:"in-progress",
      graph:{nodes:$nodes,edges:$edges,joins:{},active_wave:null,hard_stop:$stop}
    }' >"$path"
}
graph_call() {
	local operation="$1"
	shift
	if [[ "$PROVIDER" == "claude" ]]; then
		# shellcheck disable=SC1091
		source "$ROOT/hooks/scripts/lib/graph_dispatch.sh"
		case "$operation" in
		begin-wave) graph_dispatch_begin_wave "$@" ;;
		record-wave) graph_dispatch_record "$@" ;;
		esac
	else
		python3 "$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py" "$operation" "$@"
	fi
}

test_graph_validation() {
	local state="$TMP/$PROVIDER.validation.json" nodes
	nodes=$(jq -cn --argjson a "$(node hard-stop)" --argjson b "$(node)" '{A:$a,B:$b}')
	write_graph "$state" "$nodes" '[]' '{"node":"A","reason":"stop"}'
	expect_rejected "hard-stop refuses every new wave" "$state" graph_call begin-wave "$state"

	nodes=$(jq -cn --argjson a "$(node)" --argjson b "$(node)" --argjson c "$(node)" '{A:$a,B:$b,C:$c}')
	write_graph "$state" "$nodes" '[{"from":"A","to":"B"},{"from":"B","to":"A"}]'
	expect_rejected "cycle fails closed despite unrelated ready work" "$state" graph_call begin-wave "$state"

	nodes=$(jq -cn --argjson a "$(node running)" --argjson b "$(node)" '{A:$a,B:$b}')
	write_graph "$state" "$nodes"
	expect_rejected "running node outside active wave fails closed" "$state" graph_call begin-wave "$state"

	nodes=$(jq -cn --argjson a "$(node pending "done")" '{A:$a}')
	write_graph "$state" "$nodes"
	expect_rejected "contradictory status and outcome fail closed" "$state" graph_call begin-wave "$state"
}

fresh_wave() {
	local state="$1" output
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	output=$(graph_call begin-wave "$state")
	printf '%s' "$output" | jq -r '.wave_id // ("wave-" + (.revision | tostring))'
}
record_case() {
	local name="$1" payload_kind="$2" state="$TMP/$PROVIDER.wave.$RANDOM.json" wave payload
	wave=$(fresh_wave "$state")
	case "$payload_kind" in
	missing) payload='{"A":{"outcome":"done","evidence":"proof"}}' ;;
	stale) payload='{"wave_id":"wave-1","results":{"A":{"outcome":"done","evidence":"proof"}}}' ;;
	wrong) payload='{"wave_id":"not-this-wave","results":{"A":{"outcome":"done","evidence":"proof"}}}' ;;
	correct) payload=$(jq -cn --arg wave "$wave" '{wave_id:$wave,results:{A:{outcome:"done",evidence:"proof"}}}') ;;
	esac
	if [[ "$payload_kind" == "correct" ]]; then
		expect_allowed "$name" graph_call record-wave "$state" "$payload"
	else
		expect_rejected "$name" "$state" graph_call record-wave "$state" "$payload"
	fi
}
test_result_envelope() {
	record_case "results require a wave id" missing
	record_case "stale wave id is rejected atomically" stale
	record_case "wrong wave id is rejected atomically" wrong
	record_case "matching wave envelope is accepted" correct
}

write_evals() {
	local path="$1" revision="$2" scope="${3:-loop}"
	jq -n --arg scope "$scope" --argjson revision "$revision" --arg sha "$(git -C "$ROOT" rev-parse HEAD)" '{
      schema_version:1,scope:$scope,task_ref:"loop-test",verification_level:0,
      verification_justification:"adversarial fixture",frozen_at:"2026-08-20T00:00:00Z",
      frozen_sha:$sha,head_sha:$sha,session_id:"session-test",loop_id:"loop-test",
      revision:$revision,evals:[],amendments:[],result:null,graded_at:null
    }' >"$path"
	"$ROOT/scripts/post_evals.sh" grade-loop "$path" >/dev/null
}
write_completion_evidence() {
	local state="$1" evals="$2" proof="$3" retro="$4"
	write_evals "$evals" "$(jq -r '.revision' "$state")"
	jq -n '{session_id:"session-test",loop_id:"loop-test",proofs:[{id:"P1",status:"pass",evidence:"observed"}]}' >"$proof"
	jq -n '{schema_version:2,session_id:"session-test",loop_id:"loop-test",status:"complete"}' >"$retro"
}
codex_complete() {
	python3 "$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py" complete "$1" \
		--session session-test --evals "$2" --proof "$3" --retro "$4"
}
test_codex_completion_evidence() {
	local state="$TMP/codex.complete.$RANDOM.json" evals="$TMP/evals.$RANDOM" proof="$TMP/proof.$RANDOM" retro="$TMP/retro.$RANDOM"
	write_graph "$state" "$(jq -cn --argjson a "$(node "done")" '{A:$a}')"
	write_completion_evidence "$state" "$evals" "$proof" "$retro"
	jq '.grading.checksum="forged"' "$evals" >"$evals.tmp" && mv "$evals.tmp" "$evals"
	expect_rejected "completion rejects forged grading checksum" "$state" codex_complete "$state" "$evals" "$proof" "$retro"

	write_completion_evidence "$state" "$evals" "$proof" "$retro"
	jq '.proofs[0].evidence="   "' "$proof" >"$proof.tmp" && mv "$proof.tmp" "$proof"
	expect_rejected "completion rejects passing proof without evidence" "$state" codex_complete "$state" "$evals" "$proof" "$retro"
}

install_hook_state() {
	local source="$1" root="$2" session="${3:-session-test}"
	mkdir -p "$root/fixture/$session"
	cp "$source" "$root/fixture/$session/progress.json"
}
hook_output() {
	local hook="$1" root="$2" input="$3"
	printf '%s' "$input" | CODERAILS_AGENTIC_LOOP_DIR="$root" PLUGIN_ROOT="$ROOT/packages/codex" \
		CODERAILS_DISCIPLINE_LOG="$TMP/discipline.log" "$hook"
}
hook_denied() {
	local hook="$1" root="$2" input="$3" output
	output=$(hook_output "$hook" "$root" "$input")
	printf '%s' "$output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}
expect_denied() {
	local name="$1"
	shift
	if "$@"; then pass "$name"; else fail "$name" "guard allowed the bypass"; fi
}
expect_hook_allowed() {
	local name="$1"
	shift
	if "$@"; then fail "$name" "guard blocked an allowed stop"; else pass "$name"; fi
}
dispatch_input() {
	local tool="$1" task="$2"
	jq -cn --arg tool "$tool" --arg task "$task" --arg cwd "$ROOT" '{
      tool_name:$tool,session_id:"session-test",cwd:$cwd,
      tool_input:{task_name:$task,message:"node=A wave_id=wave-2"}
    }'
}
dispatch_fixture() {
	local root="$1" active="${2:-yes}" scope="${3:-loop}" stamp="${4:-valid}" state="$TMP/dispatch.$RANDOM.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	if [[ "$active" == "yes" ]]; then
		PROVIDER=codex graph_call begin-wave "$state" >/dev/null
	fi
	install_hook_state "$state" "$root"
	write_evals "$root/fixture/session-test/evals.json" "$(jq -r '.revision' "$state")" "$scope"
	if [[ "$stamp" != "valid" ]]; then
		jq '.grading.checksum="forged"' "$root/fixture/session-test/evals.json" >"$TMP/e"
		mv "$TMP/e" "$root/fixture/session-test/evals.json"
	fi
}
test_codex_dispatch_guard() {
	local guard="$ROOT/packages/codex/hooks/scripts/loop_dispatch_guard.sh" root input
	root="$TMP/dispatch.valid"
	dispatch_fixture "$root"
	input=$(dispatch_input spawn_agent loop-worker-A)
	expect_hook_allowed "canonical owned spawn_agent is allowed" hook_denied "$guard" "$root" "$input"
	expect_denied "Claude Agent is never a Codex matcher alias" hook_denied "$guard" "$root" "$(dispatch_input Agent loop-worker-A)"

	root="$TMP/dispatch.no-wave"
	dispatch_fixture "$root" no
	expect_denied "dispatch requires an active wave" hook_denied "$guard" "$root" "$input"
	root="$TMP/dispatch.task"
	dispatch_fixture "$root"
	expect_denied "caller-chosen task name cannot bypass node ownership" hook_denied "$guard" "$root" "$(dispatch_input spawn_agent loop-worker-BYPASS)"
	root="$TMP/dispatch.pr"
	dispatch_fixture "$root" yes pr
	expect_denied "PR-scope evals do not authorize loop dispatch" hook_denied "$guard" "$root" "$input"
	root="$TMP/dispatch.forged"
	dispatch_fixture "$root" yes loop forged
	expect_denied "forged grading does not authorize dispatch" hook_denied "$guard" "$root" "$input"
	root="$TMP/dispatch.missing"
	expect_denied "missing state does not authorize dispatch" hook_denied "$guard" "$root" "$input"
	root="$TMP/dispatch.foreign"
	dispatch_fixture "$root"
	input=$(printf '%s' "$input" | jq '.session_id="foreign"')
	expect_denied "foreign state does not authorize dispatch" hook_denied "$guard" "$root" "$input"
}

stop_blocked() {
	local root="$1" message="$2" output
	output=$(hook_output "$ROOT/packages/codex/hooks/scripts/graph_completion_guard.sh" "$root" \
		"$(jq -cn --arg cwd "$ROOT" --arg msg "$message" '{session_id:"session-test",cwd:$cwd,hook_event_name:"Stop",last_assistant_message:$msg}')")
	printf '%s' "$output" | jq -e '.decision == "block"' >/dev/null 2>&1
}
test_codex_lifecycle_hooks() {
	local state="$TMP/stop.$RANDOM.json" root="$TMP/stop.root" output
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	jq '.status="complete"' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
	install_hook_state "$state" "$root"
	expect_denied "Stop distrusts hand-written complete status" stop_blocked "$root" "complete"

	write_graph "$state" "$(jq -cn --argjson a "$(node hard-stop)" '{A:$a}')" '[]' '{"node":"A","reason":"owner decision"}'
	install_hook_state "$state" "$root"
	expect_hook_allowed "hard-stop report-and-wait may stop without fake completion" stop_blocked "$root" \
		"LOOP-STOP: waiting-on-human — hard-stop recorded; report and wait"
	output=$(hook_output "$ROOT/packages/codex/hooks/scripts/inject_bootstrap.sh" "$root" \
		"$(jq -cn --arg cwd "$ROOT" '{session_id:"session-test",cwd:$cwd,hook_event_name:"SessionStart"}')")
	if printf '%s' "$output" | jq -e '.hookSpecificOutput.additionalContext | contains("loop-test") and contains("hard_stop")' >/dev/null; then
		pass "SessionStart exposes provider-local hard-stop resume state"
	else
		fail "SessionStart exposes provider-local hard-stop resume state" "bootstrap omitted graph inspection"
	fi
}

test_codex_matcher_boundary() {
	if jq -e '([.hooks.PreToolUse[] | select(.matcher | contains("spawn_agent")) | .matcher] | length == 1) and
        ([.hooks.PreToolUse[] | .matcher] | all(contains("Agent") | not))' "$ROOT/packages/codex/hooks/hooks.json" >/dev/null &&
		! rg -q '(^|[^[:alnum:]_])Agent([^[:alnum:]_]|$)' "$ROOT/packages/codex/skills/agentic-loop"; then
		pass "Codex package names only spawn_agent"
	else
		fail "Codex package names only spawn_agent" "Agent remains in Codex skill or hook matching"
	fi
}

negative_control() {
	local fake="$TMP/permissive-guard.sh" root="$TMP/negative"
	printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$fake"
	chmod +x "$fake"
	expect_denied "permissive fake guard is detected" hook_denied "$fake" "$root" "$(dispatch_input spawn_agent loop-worker-A)"
}

if [[ "${1:-}" == "--negative-control" ]]; then
	PROVIDER=negative-control
	negative_control
else
	for PROVIDER in claude codex; do
		test_graph_validation
		test_result_envelope
	done
	PROVIDER=codex
	test_codex_completion_evidence
	test_codex_dispatch_guard
	test_codex_lifecycle_hooks
	test_codex_matcher_boundary
fi

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS - provider graph adversarial contract\n'
	exit 0
fi
printf 'FAILED - provider graph adversarial contract (%s cases)\n' "$FAILS"
exit 1
