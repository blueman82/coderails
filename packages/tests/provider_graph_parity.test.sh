#!/usr/bin/env bash
# Frozen provider-parity acceptance test. Both adapters below drive independent
# provider-owned implementations through the same behavioural cases.
#
# Codex's provider-local CLI contract is intentionally small and stable:
#   graph.py begin-wave STATE
#   graph.py record-wave STATE RESULTS_JSON
#   graph.py inspect STATE
#   graph.py complete STATE --session ID --evals FILE --proof FILE --retro FILE
# Claude keeps its shell implementation; this test's adapter maps those same
# behaviours to provider-local functions without sharing code between providers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -r "$TMP"' EXIT
FAILS=0 CURRENT_PROVIDER=""
pass() { printf 'ok   - %s: %s\n' "$CURRENT_PROVIDER" "$1"; }
fail() {
    printf 'FAIL - %s: %s\n      %s\n' "$CURRENT_PROVIDER" "$1" "$2"
    FAILS=$((FAILS + 1))
}
expect_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
        pass "$name"
    else
        fail "$name" "expected=$expected actual=$actual"
    fi
}
expect_rejected_unchanged() {
    local name="$1" state="$2"
    shift 2
    local before="$TMP/before.$CURRENT_PROVIDER.$RANDOM.json" output
    cp "$state" "$before"
    if output=$("$@" 2>&1); then
        fail "$name" "command unexpectedly succeeded; output=$output"
    elif cmp -s "$before" "$state"; then
        pass "$name"
    else
        fail "$name" "rejection changed durable state; output=$output"
    fi
}
write_graph() {
    local path="$1" nodes="$2" edges="$3" joins="$4"
    jq -n \
        --arg session_id "session-$CURRENT_PROVIDER" \
        --arg loop_id "loop-$CURRENT_PROVIDER-1" \
        --argjson nodes "$nodes" \
        --argjson edges "$edges" \
        --argjson joins "$joins" '
        {
          schema_version: 2,
          session_id: $session_id,
          loop_id: $loop_id,
          revision: 1,
          status: "in-progress",
          graph: {
            nodes: $nodes,
            edges: $edges,
            joins: $joins,
            active_wave: null,
            hard_stop: null
          }
        }
    ' >"$path"
}
node() {
    local status="${1:-pending}" attempts="${2:-0}" max="${3:-2}"
    jq -cn --arg status "$status" --argjson attempts "$attempts" --argjson max "$max" '
      {status:$status,outcome:$status,retry:{attempts:$attempts,max:$max},evidence:[]}'
}
CLAUDE_GRAPH="$ROOT/hooks/scripts/lib/graph_dispatch.sh"
CLAUDE_GUARD="$ROOT/hooks/scripts/loop_dispatch_guard.sh"
CODEX_GRAPH="$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py"
CODEX_GUARD="$ROOT/packages/codex/hooks/scripts/loop_dispatch_guard.sh"
claude_graph_call() {
    local operation="$1"
    shift
    [[ -f "$CLAUDE_GRAPH" ]] || return 127
    # shellcheck disable=SC1090  # fixed provider-local path
    source "$CLAUDE_GRAPH"
    "$operation" "$@"
}
codex_graph_call() {
    local operation="$1"
    shift
    [[ -f "$CODEX_GRAPH" ]] || return 127
    python3 "$CODEX_GRAPH" "$operation" "$@"
}
provider_begin_wave() {
    local state="$1"
    if [[ "$CURRENT_PROVIDER" == "claude" ]]; then
        claude_graph_call graph_dispatch_begin_wave "$state"
    else
        codex_graph_call begin-wave "$state"
    fi
}
provider_record_wave() {
    local state="$1" results="$2"
    if [[ "$CURRENT_PROVIDER" == "claude" ]]; then
        claude_graph_call graph_dispatch_record "$state" "$results"
    else
        codex_graph_call record-wave "$state" "$results"
    fi
}
provider_inspect() {
    local state="$1"
    if [[ "$CURRENT_PROVIDER" == "claude" ]]; then
        claude_graph_call graph_dispatch_inspect "$state"
    else
        codex_graph_call inspect "$state"
    fi
}
provider_can_complete() {
    local state="$1" evals="$2" proof="$3" retro="$4" session
    session=$(jq -r '.session_id' "$state")
    if [[ "$CURRENT_PROVIDER" == "claude" ]]; then
        claude_graph_call graph_dispatch_complete "$state" \
            --session "$session" --evals "$evals" --proof "$proof" --retro "$retro"
    else
        codex_graph_call complete "$state" \
            --session "$session" --evals "$evals" --proof "$proof" --retro "$retro"
    fi
}
provider_authorize_dispatch() {
    local state="$1" evals="$2" session="$3" mode="$4"
    local guard input guard_root state_dir output
    guard_root="$TMP/guard.$CURRENT_PROVIDER.$RANDOM"
    state_dir="$guard_root/fixture/$session"
    mkdir -p "$state_dir"
    [[ -f "$state" ]] && ln -s "$state" "$state_dir/progress.json"
    [[ -f "$evals" ]] && ln -s "$evals" "$state_dir/evals.json"
    if [[ "$CURRENT_PROVIDER" == "claude" ]]; then
        guard="$CLAUDE_GUARD"
        if [[ "$mode" == "sandbox" ]]; then
            input=$(jq -cn --arg session "$session" --arg cwd "$ROOT" \
                '{tool_name:"Bash",session_id:$session,cwd:$cwd,tool_input:{command:"scripts/sandbox/spawn-sandboxed-worker.sh worktree prompt model"}}')
        else
            input=$(jq -cn --arg session "$session" --arg cwd "$ROOT" \
                '{tool_name:"Agent",session_id:$session,cwd:$cwd,tool_input:{subagent_type:"coderails:loop-worker"}}')
        fi
    else
        [[ "$mode" != "sandbox" ]] || return 1
        guard="$CODEX_GUARD"
        input=$(jq -cn --arg session "$session" --arg cwd "$ROOT" \
            '{tool_name:"spawn_agent",session_id:$session,cwd:$cwd,tool_input:{task_name:"loop-worker",message:"Implement graph work unit"}}')
    fi
    [[ -x "$guard" ]] || return 127
    output=$(printf '%s' "$input" | \
        CLAUDE_AGENTIC_LOOP_DIR="$guard_root" \
        CODERAILS_AGENTIC_LOOP_DIR="$guard_root" \
        CLAUDE_DISCIPLINE_LOG="$TMP/guard.log" \
        CODERAILS_DISCIPLINE_LOG="$TMP/guard.log" \
        "$guard" 2>&1) || return 1
    ! printf '%s' "$output" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}
test_malformed_and_unknown() {
    local malformed="$TMP/$CURRENT_PROVIDER.malformed.json"
    local unknown="$TMP/$CURRENT_PROVIDER.unknown.json"
    printf '%s\n' 'not-json' >"$malformed"
    write_graph "$unknown" "$(jq -cn --argjson a "$(node)" '{A:$a}')" \
        '[{"from":"NO_SUCH_NODE","to":"A"}]' '{}'

    expect_rejected_unchanged "malformed graph fails closed without state change" \
        "$malformed" provider_begin_wave "$malformed"
    expect_rejected_unchanged "unknown node fails closed without state change" \
        "$unknown" provider_begin_wave "$unknown"
}
test_fanout_join() {
    local state="$TMP/$CURRENT_PROVIDER.fanout.json" wave first second
    local nodes
    nodes=$(jq -cn \
        --argjson a "$(node)" --argjson b "$(node)" \
        --argjson j "$(node)" --argjson c "$(node)" \
        '{A:$a,B:$b,J:$j,C:$c}')
    write_graph "$state" "$nodes" '[{"from":"J","to":"C"}]' \
        '{"J":{"mode":"all","inputs":["A","B"],"released":false}}'

    if wave=$(provider_begin_wave "$state" 2>&1); then
        first=$(printf '%s' "$wave" | jq -c '.nodes')
        expect_eq "A || B starts as one deterministic wave" '["A","B"]' "$first"
        expect_eq "started wave is durable and both nodes are running" \
            'true' "$(jq -r '(.graph.active_wave.nodes == ["A","B"]) and ([.graph.nodes.A.status,.graph.nodes.B.status] | all(. == "running"))' "$state")"
    else
        fail "A || B starts as one deterministic wave" "$wave"
    fi

    if provider_record_wave "$state" \
        '{"A":{"outcome":"done","evidence":"A proof"},"B":{"outcome":"done","evidence":"B proof"}}' >/dev/null 2>&1; then
        expect_eq "all-input join releases after both inputs succeed" \
            'true' "$(jq -r '.graph.joins.J.released == true and .graph.nodes.J.status == "done" and .graph.active_wave == null' "$state")"
    else
        fail "all-input join releases after both inputs succeed" "record-wave rejected the exact active wave"
    fi

    if wave=$(provider_begin_wave "$state" 2>&1); then
        second=$(printf '%s' "$wave" | jq -c '.nodes')
        expect_eq "join releases C as the next deterministic wave" '["C"]' "$second"
    else
        fail "join releases C as the next deterministic wave" "$wave"
    fi
}
test_active_wave_atomicity() {
    local state="$TMP/$CURRENT_PROVIDER.atomic.json" nodes
    nodes=$(jq -cn --argjson a "$(node)" --argjson b "$(node)" '{A:$a,B:$b}')
    write_graph "$state" "$nodes" '[]' '{}'

    if ! provider_begin_wave "$state" >/dev/null 2>&1; then
        fail "active wave is recorded before results" "start-wave failed"
        return
    fi
    expect_rejected_unchanged "partial active-wave results are rejected atomically" \
        "$state" provider_record_wave "$state" '{"A":{"outcome":"done","evidence":"A proof"}}'
    expect_rejected_unchanged "extra active-wave result keys are rejected atomically" \
        "$state" provider_record_wave "$state" \
        '{"A":{"outcome":"done","evidence":"A proof"},"B":{"outcome":"done","evidence":"B proof"},"C":{"outcome":"done","evidence":"C proof"}}'
}
test_retry_and_hard_stop() {
    local state="$TMP/$CURRENT_PROVIDER.retry.json" nodes resume
    nodes=$(jq -cn --argjson a "$(node pending 0 2)" '{A:$a}')
    write_graph "$state" "$nodes" '[]' '{}'

    if provider_begin_wave "$state" >/dev/null 2>&1 &&
       provider_record_wave "$state" '{"A":{"outcome":"failed","evidence":"attempt one failed"}}' >/dev/null 2>&1; then
        expect_eq "retryable failure returns to pending with evidence" \
            'true' "$(jq -r '.graph.nodes.A.status == "pending" and .graph.nodes.A.retry.attempts == 1 and (.graph.nodes.A.evidence | index("attempt one failed") != null)' "$state")"
    else
        fail "retryable failure returns to pending with evidence" "start or record failed"
    fi

    if provider_begin_wave "$state" >/dev/null 2>&1 &&
       provider_record_wave "$state" '{"A":{"outcome":"failed","evidence":"attempt two failed"}}' >/dev/null 2>&1; then
        expect_eq "retry exhaustion becomes a hard-stop with evidence" \
            'true' "$(jq -r '.graph.nodes.A.status == "hard-stop" and .graph.nodes.A.retry.attempts == 2 and .graph.hard_stop != null and (.graph.nodes.A.evidence | length) == 2' "$state")"
    else
        fail "retry exhaustion becomes a hard-stop with evidence" "start or record failed"
    fi

    if resume=$(provider_inspect "$state" 2>&1); then
        expect_eq "resume reports identity, revision, active wave, ready work and hard-stop" \
            'true' "$(printf '%s' "$resume" | jq -r --arg session "session-$CURRENT_PROVIDER" --arg loop "loop-$CURRENT_PROVIDER-1" '
                .session_id == $session and .loop_id == $loop and
                (.revision | type == "number") and has("active_wave") and
                (.ready | type == "array") and (.hard_stop != null)')"
    else
        fail "resume reports identity, revision, active wave, ready work and hard-stop" "$resume"
    fi
}
write_completion_artifacts() {
    local state="$1" evals="$2" proof="$3" retro="$4"
    local session loop revision
    session=$(jq -r '.session_id' "$state")
    loop=$(jq -r '.loop_id' "$state")
    revision=$(jq -r '.revision' "$state")
    jq -n --arg session "$session" --arg loop "$loop" --argjson revision "$revision" \
        --arg sha "$(git -C "$ROOT" rev-parse HEAD)" '
        {
          schema_version:1,scope:"loop",task_ref:$loop,
          verification_level:0,
          verification_justification:"Acceptance fixture with no executable task output",
          frozen_at:"2026-08-20T00:00:00Z",frozen_sha:$sha,
          session_id:$session,loop_id:$loop,revision:$revision,
          evals:[],amendments:[],result:null,graded_at:null,head_sha:$sha
        }' >"$evals"
    "$ROOT/scripts/post_evals.sh" grade-loop "$evals" >/dev/null
    jq -n --arg session "$session" --arg loop "$loop" \
        '{session_id:$session,loop_id:$loop,proofs:[{id:"P1",status:"pass",evidence:"ran"}]}' >"$proof"
    jq -n --arg session "$session" --arg loop "$loop" \
        '{schema_version:2,session_id:$session,loop_id:$loop,status:"complete"}' >"$retro"
}
test_completion_guards() {
    local state="$TMP/$CURRENT_PROVIDER.complete.json"
    local evals="$TMP/$CURRENT_PROVIDER.evals.json"
    local proof="$TMP/$CURRENT_PROVIDER.proof.json"
    local retro="$TMP/$CURRENT_PROVIDER.retro.json"
    local nodes
    nodes=$(jq -cn --argjson a "$(node 'done' 0 2)" --argjson j "$(node 'done' 0 2)" --argjson c "$(node 'done' 0 2)" '{A:$a,J:$j,C:$c}')
    write_graph "$state" "$nodes" '[{"from":"J","to":"C"}]' \
        '{"J":{"mode":"all","inputs":["A"],"released":true}}'
    write_completion_artifacts "$state" "$evals" "$proof" "$retro"

    if provider_can_complete "$state" "$evals" "$proof" "$retro" >/dev/null 2>&1; then
        pass "complete graph with matching evidence may complete"
    else
        fail "complete graph with matching evidence may complete" "valid completion fixture was rejected"
    fi

    jq '.graph.nodes.C.status="pending" | .graph.nodes.C.outcome="pending"' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
    expect_rejected_unchanged "completion blocks unfinished graph nodes" \
        "$state" provider_can_complete "$state" "$evals" "$proof" "$retro"
    jq '.graph.nodes.C.status="done" | .graph.nodes.C.outcome="done" | .graph.joins.J.released=false' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
    expect_rejected_unchanged "completion blocks unreleased joins" \
        "$state" provider_can_complete "$state" "$evals" "$proof" "$retro"
    jq '.graph.joins.J.released=true' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
    jq '.loop_id="stale-loop"' "$evals" >"$evals.tmp" && mv "$evals.tmp" "$evals"
    expect_rejected_unchanged "completion blocks stale loop-eval identity" \
        "$state" provider_can_complete "$state" "$evals" "$proof" "$retro"
    write_completion_artifacts "$state" "$evals" "$proof" "$retro"
    : >"$retro"
    expect_rejected_unchanged "completion marker cannot bypass missing teardown evidence" \
        "$state" provider_can_complete "$state" "$evals" "$proof" "$retro"
}
test_dispatch_guards() {
    local state="$TMP/$CURRENT_PROVIDER.dispatch.json" evals="$TMP/$CURRENT_PROVIDER.dispatch-evals.json" nodes
    nodes=$(jq -cn --argjson a "$(node)" '{A:$a}')
    write_graph "$state" "$nodes" '[]' '{}'
    jq '.work_units={one:{status:"pending"},two:{status:"pending"},three:{status:"pending"}}' \
        "$state" >"$state.tmp" && mv "$state.tmp" "$state"
    write_completion_artifacts "$state" "$evals" \
        "$TMP/$CURRENT_PROVIDER.dispatch-proof.json" "$TMP/$CURRENT_PROVIDER.dispatch-retro.json"

    if provider_authorize_dispatch "$state" "$evals" "session-$CURRENT_PROVIDER" native >/dev/null 2>&1; then
        pass "owned native dispatch with matching loop evidence is allowed"
    else
        fail "owned native dispatch with matching loop evidence is allowed" "valid dispatch fixture was rejected"
    fi
    expect_rejected_unchanged "worker dispatch blocks missing loop state" \
        "$state" provider_authorize_dispatch "$TMP/missing-progress.json" "$evals" "session-$CURRENT_PROVIDER" native
    expect_rejected_unchanged "worker dispatch blocks foreign loop state" \
        "$state" provider_authorize_dispatch "$state" "$evals" foreign-session native
    : >"$evals"
    expect_rejected_unchanged "sandbox dispatch cannot bypass the same evidence gate" \
        "$state" provider_authorize_dispatch "$state" "$evals" "session-$CURRENT_PROVIDER" sandbox
}
run_provider() {
    CURRENT_PROVIDER="$1"
    test_malformed_and_unknown
    test_fanout_join
    test_active_wave_atomicity
    test_retry_and_hard_stop
    test_completion_guards
    test_dispatch_guards
}
test_provider_boundaries() {
    CURRENT_PROVIDER="boundaries"
    if rg -q '(^|[^[:alnum:]_])Agent([^[:alnum:]_]|$)' "$ROOT/skills/agentic-loop/SKILL.md" &&
       ! rg -q 'spawn_agent|codex exec' "$ROOT/skills/agentic-loop/SKILL.md"; then
        pass "Claude graph dispatch stays on native Agent"
    else
        fail "Claude graph dispatch stays on native Agent" "missing Agent or found a Codex/nested-provider dispatch"
    fi
    if rg -q 'spawn_agent' "$ROOT/packages/codex/skills/agentic-loop/SKILL.md" &&
       ! rg -q 'claude -p|codex exec' "$ROOT/packages/codex/skills/agentic-loop/SKILL.md"; then
        pass "Codex graph dispatch stays on native spawn_agent"
    else
        fail "Codex graph dispatch stays on native spawn_agent" "missing spawn_agent or found a nested provider session"
    fi

    local forbidden path found=""
    forbidden=(
        "skills/index.yaml"
        "packages/codex/runtime"
        "packages/codex/skills/agentic-loop/scripts/scheduler.sh"
        "packages/codex/skills/agentic-loop/scripts/daemon.sh"
    )
    for path in "${forbidden[@]}"; do
        [[ ! -e "$ROOT/$path" ]] || found="${found}${path} "
    done
    if [[ -z "$found" ]]; then
        pass "shared routing, custom runtime and background scheduler paths stay absent"
    else
        fail "shared routing, custom runtime and background scheduler paths stay absent" "found=$found"
    fi
}
negative_control() {
    CURRENT_PROVIDER="negative-control"
    local fixture='{"nodes":["A"]}'
    if [[ "$(printf '%s' "$fixture" | jq -c '.nodes')" == '["A","B"]' ]]; then
        printf 'FAIL - negative-control: deliberate bad wave was not detected\n'
        return 0
    fi
    printf 'NEGATIVE CONTROL - deliberate incomplete wave detected\n'
    return 1
}

if [[ "${1:-}" == "--negative-control" ]]; then
    negative_control
fi

run_provider claude
run_provider codex
test_provider_boundaries

if [[ "$FAILS" -eq 0 ]]; then
    printf 'PASS - provider graph parity\n'
    exit 0
fi
printf 'FAILED - provider graph parity (%s cases)\n' "$FAILS"
exit 1
