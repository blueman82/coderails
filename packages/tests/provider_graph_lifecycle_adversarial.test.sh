#!/usr/bin/env bash
# Frozen lifecycle gaps from the second exact-head graph-parity review.
# The providers are driven only through their independent production adapters.
# shellcheck disable=SC2329 # Test callbacks are invoked indirectly through "$@".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -r "$TMP"' EXIT
export HOME="$TMP/home"
# shellcheck source=packages/tests/lib/codex_transcript_fixture.sh
source "$ROOT/packages/tests/lib/codex_transcript_fixture.sh"
codex_fixture::init session-test
FAILS=0
PROVIDER=""
CODEX_GRAPH="${CODEX_GRAPH_OVERRIDE:-$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py}"

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
	local status="${1:-pending}" maximum="${2:-2}"
	jq -cn --arg status "$status" --argjson maximum "$maximum" \
		'{status:$status,outcome:$status,retry:{attempts:0,max:$maximum},evidence:[]}'
}
write_graph() {
	local path="$1" nodes="$2" edges="${3:-[]}" joins="${4:-}"
	[[ -n "$joins" ]] || joins='{}'
	jq -n --argjson nodes "$nodes" --argjson edges "$edges" --argjson joins "$joins" '{
      schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:1,status:"in-progress",
      work_units:{one:{status:"pending"},two:{status:"pending"},three:{status:"pending"}},
      graph:{nodes:$nodes,edges:$edges,joins:$joins,active_wave:null,hard_stop:null}
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
		inspect) graph_dispatch_inspect "$@" ;;
		esac
	else
		python3 "$CODEX_GRAPH" "$operation" "$@"
	fi
}
fresh_wave() {
	local state="$1"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	graph_call begin-wave "$state"
}

test_claude_record_requires_wave() {
	local state="$TMP/claude.no-wave.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	expect_rejected "record-wave rejects when active_wave is null" "$state" graph_call record-wave "$state" \
		'{"wave_id":"wave-1","results":{"A":{"outcome":"done","evidence":"proof"}}}'
}

test_claude_root_and_wave_identity() {
	local field state
	for field in session_id loop_id revision; do
		state="$TMP/claude.missing-$field.json"
		write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
		jq --arg field "$field" 'del(.[$field])' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
		expect_rejected "begin-wave rejects missing root $field" "$state" graph_call begin-wave "$state"
	done

	state="$TMP/claude.wave-revision.json"
	fresh_wave "$state" >/dev/null
	jq '.graph.active_wave.revision=(.revision - 1)' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
	expect_rejected "active-wave revision binds to root revision" "$state" graph_call inspect "$state"

	state="$TMP/claude.wave-id.json"
	fresh_wave "$state" >/dev/null
	jq '.graph.active_wave.wave_id="wave-999"' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
	expect_rejected "active-wave id binds to root revision" "$state" graph_call inspect "$state"
}

test_claude_join_agreement() {
	local state nodes joins
	nodes=$(jq -cn --argjson a "$(node "done")" --argjson j "$(node "done")" --argjson c "$(node)" '{A:$a,J:$j,C:$c}')
	joins='{"J":{"mode":"all","inputs":["A"],"released":false}}'
	state="$TMP/claude.join-done.json"
	write_graph "$state" "$nodes" '[{"from":"J","to":"C"}]' "$joins"
	expect_rejected "completed join with released=false fails closed" "$state" graph_call begin-wave "$state"
	if [[ $(jq -r '.graph.nodes.C.status' "$state") == "pending" ]]; then
		pass "join disagreement cannot release downstream C"
	else
		fail "join disagreement cannot release downstream C" "C changed despite rejected graph"
	fi

}

test_retry_domain() {
	local maximum state
	for maximum in 0 1 5; do
		state="$TMP/$PROVIDER.retry-$maximum.json"
		write_graph "$state" "$(jq -cn --argjson a "$(node pending "$maximum")" '{A:$a}')"
		if [[ "$maximum" -eq 0 ]]; then
			expect_rejected "retry.max=0 is outside the agreed 1..5 domain" "$state" graph_call begin-wave "$state"
		else
			expect_allowed "retry.max=$maximum is inside the agreed 1..5 domain" graph_call begin-wave "$state"
		fi
	done
}

write_evals() {
	local path="$1" revision="$2"
	jq -n --argjson revision "$revision" --arg sha "$(git -C "$ROOT" rev-parse HEAD)" '{
      schema_version:1,scope:"loop",task_ref:"loop-test",verification_level:0,
      verification_justification:"lifecycle adversarial fixture",frozen_at:"2026-08-20T00:00:00Z",
      frozen_sha:$sha,head_sha:$sha,session_id:"session-test",loop_id:"loop-test",
      revision:$revision,evals:[],amendments:[],result:null,graded_at:null
    }' >"$path"
	"$ROOT/scripts/post_evals.sh" grade-loop "$path" >/dev/null
}
install_hook_state() {
	local source="$1" root="$2"
	mkdir -p "$root/fixture/session-test"
	cp "$source" "$root/fixture/session-test/progress.json"
	write_evals "$root/fixture/session-test/evals.json" "$(jq -r '.revision' "$source")"
}
claude_dispatch_input() {
	local node="$1" wave="$2" revision="$3"
	jq -cn --arg cwd "$ROOT" --arg node "$node" --arg wave "$wave" --argjson revision "$revision" '{
      tool_name:"Agent",session_id:"session-test",cwd:$cwd,
      tool_input:{subagent_type:"coderails:loop-worker",prompt:("CODERAILS_GRAPH_DISPATCH=" + ({session_id:"session-test",loop_id:"loop-test",revision:$revision,wave_id:$wave,node_id:$node}|tojson))}
    }'
}
hook_denied() {
	local hook="$1" root="$2" input="$3" output
	output=$(printf '%s' "$input" | CLAUDE_AGENTIC_LOOP_DIR="$root" CLAUDE_DISCIPLINE_LOG="$TMP/claude.log" "$hook")
	printf '%s' "$output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}
expect_denied() {
	local name="$1"
	shift
	if "$@"; then pass "$name"; else fail "$name" "guard allowed the bypass"; fi
}
expect_not_denied() {
	local name="$1"
	shift
	if "$@"; then fail "$name" "guard rejected the owned dispatch"; else pass "$name"; fi
}

test_claude_dispatch_ownership() {
	local guard="$ROOT/hooks/scripts/loop_dispatch_guard.sh" state root wave revision
	state="$TMP/claude.dispatch.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	root="$TMP/claude-dispatch.no-wave"
	install_hook_state "$state" "$root"
	expect_denied "dispatch guard rejects no active wave" hook_denied "$guard" "$root" \
		"$(claude_dispatch_input A wave-1 1)"

	fresh_wave "$state" >/dev/null
	wave=$(jq -r '.graph.active_wave.wave_id' "$state")
	revision=$(jq -r '.revision' "$state")
	root="$TMP/claude-dispatch.active"
	install_hook_state "$state" "$root"
	expect_denied "dispatch guard rejects a foreign node" hook_denied "$guard" "$root" \
		"$(claude_dispatch_input B "$wave" "$revision")"
	expect_denied "dispatch guard rejects stale wave ownership" hook_denied "$guard" "$root" \
		"$(claude_dispatch_input A wave-1 "$revision")"
	expect_denied "dispatch guard rejects wrong revision ownership" hook_denied "$guard" "$root" \
		"$(claude_dispatch_input A "$wave" "$((revision - 1))")"
	expect_not_denied "dispatch guard allows exact active-wave ownership" hook_denied "$guard" "$root" \
		"$(claude_dispatch_input A "$wave" "$revision")"
}

codex_dispatch_input() {
	local task="$1"
	jq -cn --arg cwd "$ROOT" --arg task "$task" '{
      tool_name:"spawn_agent",session_id:"session-test",cwd:$cwd,
      tool_input:{task_name:$task,message:"graph work"}
    }'
}
codex_hook_denied() {
	local root="$1" input="$2" output
	output=$(printf '%s' "$input" | CODERAILS_AGENTIC_LOOP_DIR="$root" PLUGIN_ROOT="$ROOT/packages/codex" \
		CODERAILS_DISCIPLINE_LOG="$TMP/codex.log" "$ROOT/packages/codex/hooks/scripts/loop_dispatch_guard.sh")
	printf '%s' "$output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}
test_codex_dispatch_names() {
	local state="$TMP/codex.dispatch.json" root="$TMP/codex-dispatch" evals
	fresh_wave "$state" >/dev/null
	install_hook_state "$state" "$root"
	evals="$root/fixture/session-test/evals.json"
	expect_allowed "lowercase reversible task name binds to node A" python3 "$CODEX_GRAPH" authorize-dispatch "$state" \
		--session session-test --task loop_worker_41 --evals "$evals"
	expect_rejected "hyphen/uppercase task name is not native-canonical" "$state" python3 "$CODEX_GRAPH" authorize-dispatch "$state" \
		--session session-test --task loop-worker-A --evals "$evals"
	expect_denied "arbitrary renamed spawn_agent cannot bypass an active graph" codex_hook_denied "$root" \
		"$(codex_dispatch_input harmless_reviewer)"
}

test_codex_wave_identity() {
	local state="$TMP/codex.wave.json"
	fresh_wave "$state" >/dev/null
	if jq -e '.graph.active_wave.revision == .revision and .graph.active_wave.id == ("wave-" + (.revision|tostring))' \
		"$state" >/dev/null; then
		pass "active-wave id and revision bind to root revision"
	else
		fail "active-wave id and revision bind to root revision" "active_wave lacks the bound revision identity"
	fi
	jq '.graph.active_wave.revision=(.revision - 1)' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
	expect_rejected "stale active-wave revision fails closed" "$state" graph_call inspect "$state"
}

write_completion_fixture() {
	local state="$1" evals="$2" proof="$3" retro="$4"
	write_graph "$state" "$(jq -cn --argjson a "$(node "done")" '{A:$a}')"
	write_evals "$evals" 1
	jq -n '{schema_version:1,session_id:"session-test",loop_id:"loop-test",proofs:[{id:"P1",claim:"check",cmd:"true",expect:"exit 0",status:"pass",evidence:"typed claim"}]}' >"$proof"
	jq -n '{schema_version:2,session_id:"session-test",loop_id:"loop-test",status:"complete"}' >"$retro"
}
test_codex_proof_observation() {
	local state="$TMP/codex.complete.json" evals="$TMP/codex.evals.json" proof="$TMP/codex.proof.json" retro="$TMP/codex.retro.json"
	local root="$TMP/codex-stop"
	write_completion_fixture "$state" "$evals" "$proof" "$retro"
	expect_rejected "completion rejects proof with no current-session observed result" "$state" \
		python3 "$CODEX_GRAPH" complete "$state" --session session-test --evals "$evals" --proof "$proof" --retro "$retro"

	jq '.status="complete" | .revision=2 | .completion={revision:1}' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
	install_hook_state "$state" "$root"
	cp "$evals" "$root/fixture/session-test/evals.json"
	cp "$proof" "$root/fixture/session-test/proof.json"
	cp "$retro" "$root/fixture/session-test/retro.json"
	local output
	output=$(printf '%s' "$(jq -cn --arg cwd "$ROOT" '{session_id:"session-test",cwd:$cwd,hook_event_name:"Stop",last_assistant_message:"complete"}')" |
		CODERAILS_AGENTIC_LOOP_DIR="$root" PLUGIN_ROOT="$ROOT/packages/codex" \
			"$ROOT/packages/codex/hooks/scripts/graph_completion_guard.sh")
	if printf '%s' "$output" | jq -e '.decision == "block"' >/dev/null 2>&1; then
		pass "Stop rejects proof with no current-session observed result"
	else
		fail "Stop rejects proof with no current-session observed result" "Stop trusted status/evidence text"
	fi
}

test_empty_home_installer() {
	local home="$TMP/empty-home" fake_bin="$TMP/install-bin" output="$TMP/install.out"
	mkdir -p "$home" "$fake_bin"
	printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$fake_bin/gh"
	chmod +x "$fake_bin/gh"
	if HOME="$home" PATH="$fake_bin:$PATH" bash "$ROOT/install.sh" --no-integrity-gate </dev/null >"$output" 2>&1 &&
		[[ -d "$home/.claude" && ! -e "$home/.codex" ]] &&
		jq -e --arg root "$ROOT" '.extraKnownMarketplaces.coderails.source.path == $root' \
			"$home/.claude/settings.json" >/dev/null 2>&1; then
		pass "Claude install succeeds in genuinely empty HOME without Codex writes"
	else
		fail "Claude install succeeds in genuinely empty HOME without Codex writes" "$(tail -n 1 "$output")"
	fi
}

negative_control() {
	local mutation_dir="$TMP/mutated-codex"
	mkdir -p "$mutation_dir"
	cp "$ROOT/packages/codex/skills/agentic-loop/scripts/graph_evidence.py" "$mutation_dir/graph_evidence.py"
	cp "$ROOT/packages/codex/skills/agentic-loop/scripts/graph_identity.py" "$mutation_dir/graph_identity.py"
	sed 's/not 1 <= maximum <= 5/not 0 <= maximum <= 5/' \
		"$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py" >"$mutation_dir/graph.py"
	chmod +x "$mutation_dir/graph.py"
	CODEX_GRAPH="$mutation_dir/graph.py"
	PROVIDER=codex
	test_retry_domain
}

if [[ "${1:-}" == "--negative-control" ]]; then
	negative_control
else
	PROVIDER=claude
	test_claude_record_requires_wave
	test_claude_root_and_wave_identity
	test_claude_join_agreement
	test_retry_domain
	test_claude_dispatch_ownership
	PROVIDER=codex
	test_retry_domain
	test_codex_dispatch_names
	test_codex_wave_identity
	test_codex_proof_observation
	PROVIDER=installer
	test_empty_home_installer
fi

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS - provider graph lifecycle adversarial contract\n'
	exit 0
fi
printf 'FAILED - provider graph lifecycle adversarial contract (%s cases)\n' "$FAILS"
exit 1
