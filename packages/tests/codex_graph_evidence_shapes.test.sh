#!/usr/bin/env bash
# Focused recursive worker-evidence shape and reuse contracts.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GRAPH="$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py"
TMP="$(mktemp -d)"
trap 'rm -r "$TMP"' EXIT
export HOME="$TMP/home"
# shellcheck source=packages/tests/lib/codex_transcript_fixture.sh
source "$ROOT/packages/tests/lib/codex_transcript_fixture.sh"

node() {
	local status="${1:-pending}"
	jq -cn --arg status "$status" \
		'{status:$status,outcome:$status,retry:{attempts:0,max:2},evidence:[]}'
}

write_graph() {
	local path="$1" nodes="$2"
	jq -n --argjson nodes "$nodes" '{
      schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:1,status:"in-progress",
      graph:{nodes:$nodes,edges:[],joins:{},active_wave:null,hard_stop:null}
    }' >"$path"
}

record_payload() {
	local state="$1" node_id="${2:-A}" outcome="${3:-done}" wave
	wave=$(jq -r '.graph.active_wave.id' "$state")
	jq -cn --arg wave "$wave" --arg node "$node_id" --arg outcome "$outcome" \
		'{wave_id:$wave,results:{($node):{outcome:$outcome,evidence:"checked"}}}'
}

validate_worker_refs() {
	PYTHONPATH="$(dirname "$GRAPH")" python3 -c \
		'import json,sys; from graph_evidence import validate_worker_evidence; validate_worker_evidence(json.load(open(sys.argv[1], encoding="utf-8")))' "$1"
}

classifier_contract() {
	PYTHONPATH="$(dirname "$GRAPH")" python3 -c '
import json
from graph_identity import GraphError, classify_worker_evidence as classify
assert classify("codеx_agent") == (True, set())
assert classify({"spаwn_call_id": "call"}) == (True, {"call"})
assert classify({"spawn_call_id": "123"}) == (True, {"123"})
for token in ("kind", "attempt", "wave_id", "spawn_call_id", "agent_thread_id", "task_complete_turn_id"):
    assert classify(token) == (False, set())
assert classify("codex_agent") == (True, set())
for identifier in ("call-1", "thread-1", "turn-1"):
    assert classify(identifier, {identifier}) == (True, {identifier})
encoded = {"spawn_call_id": "call"}
for _ in range(12):
    encoded = json.dumps(encoded)
assert classify(encoded) == (True, {"call"})
benign = "checked"
for _ in range(12):
    benign = json.dumps(benign)
assert classify({"note": [benign]}) == (False, set())
assert classify(json.dumps(json.dumps("agent_thread_id"))) == (False, set())
assert classify("γειά σου") == (False, set())
assert classify({"ключ": "значение"}) == (False, set())
try:
    classify("x" * ((1 << 20) + 1))
except GraphError:
    pass
else:
    raise AssertionError("oversized evidence was accepted")
'
}

attack_rows() {
	python3 - "$1" <<'PY'
import base64
import json
import sys

reference = json.loads(sys.argv[1])

def encoded(value, depth=4):
    for _ in range(depth):
        value = json.dumps(value, ensure_ascii=False)
    return value

attacks = [
    ("repeated JSON", encoded(reference, 12)),
    ("nested arrays and values", {"note": [[encoded({"inner": [encoded(reference)]})]]}),
    ("reference hidden in key", {encoded(reference): "checked"}),
    ("encoded marker key", {encoded("spawn_call_id"): reference["spawn_call_id"]}),
    ("Unicode partial field", {"spаwn_call_id": encoded(reference["spawn_call_id"])}),
    ("whitespace encoding", encoded(f"  {json.dumps(reference)}  \n")),
]
attacks.extend(
    (f"isolated reused {key}", encoded({key: reference[key]}))
    for key in ("spawn_call_id", "agent_thread_id", "task_complete_turn_id")
)
for key in ("spawn_call_id", "agent_thread_id", "task_complete_turn_id"):
    identifier = reference[key]
    attacks.extend((
        (f"{key} naked identifier", identifier),
        (f"{key} arbitrary key", {identifier: "ordinary"}),
        (f"{key} arbitrary value", {"note": identifier}),
    ))
for name, attack in attacks:
    payload = base64.b64encode(json.dumps(attack, ensure_ascii=False).encode()).decode()
    print(f"{name}\t{payload}")
PY
}

write_completion_evidence() {
	local state="$1" evals="$2" proof="$3" retro="$4" transcript="$5" revision
	revision=$(jq -r '.revision' "$state")
	jq -n --argjson revision "$revision" --arg sha "$(git -C "$ROOT" rev-parse HEAD)" '{
      schema_version:1,scope:"loop",task_ref:"loop-test",verification_level:0,
      verification_justification:"worker evidence shape fixture",frozen_at:"2026-08-24T00:00:00Z",
      frozen_sha:$sha,head_sha:$sha,session_id:"session-test",loop_id:"loop-test",revision:$revision,
      evals:[],amendments:[],result:"VERIFICATION_LEVEL0",graded_at:"2026-08-24T00:00:01Z",
      grading:{by:"post_evals.sh grade-loop",checksum:"0e7a6c2b4c5698e9b454f904a01cca76c7e02ff4bc77ffa030a72ce24a65dde3",amendments_at_grade:0}
    }' >"$evals"
	jq -n '{schema_version:1,session_id:"session-test",loop_id:"loop-test",proofs:[{
      id:"P1",claim:"fixture",cmd:"true",expect:"exit 0",status:"pass",evidence:"observed"
    }]}' >"$proof"
	jq -n '{schema_version:2,session_id:"session-test",loop_id:"loop-test",status:"complete"}' >"$retro"
	jq -cn '{type:"turn_context",payload:{session_id:"session-test",loop_id:"loop-test"}}' >"$transcript"
	jq -cn '{type:"response_item",payload:{type:"function_call",name:"exec_command",call_id:"proof-call",arguments:"{\"cmd\":\"true\"}"}}' >>"$transcript"
	jq -cn '{type:"response_item",payload:{type:"function_call_output",call_id:"proof-call",output:"{\"exit_code\":0}"}}' >>"$transcript"
}

reject_unchanged() {
	local name="$1" state="$2" before="$TMP/before.$RANDOM" output="$TMP/output.$RANDOM"
	shift 2
	cp "$state" "$before"
	if "$@" >"$output" 2>&1; then
		printf 'unexpected success for %s: %s\n' "$name" "$(tr '\n' ' ' <"$output")"
		return 1
	fi
	if ! cmp -s "$before" "$state"; then
		printf 'rejection changed graph state for %s\n' "$name"
		return 1
	fi
}

join_completion_contract() {
	local clean="$1" candidate="$2" evals="$3" proof="$4" retro="$5" transcript="$6" reference="$7"
	local name encoded shape
	jq --argjson j "$(node done)" \
		'.graph.nodes.J=$j | .graph.nodes.J.evidence=[{note:"ordinary join evidence"}] |
		 .graph.joins.J={mode:"all",inputs:["A","B"],released:true}' "$clean" >"$candidate"
	python3 "$GRAPH" complete "$candidate" --session session-test --evals "$evals" \
		--proof "$proof" --retro "$retro" --transcript "$transcript" >/dev/null
	IFS=$'\t' read -r name encoded < <(attack_rows "$reference" | head -1)
	shape=$(printf '%s' "$encoded" | base64 --decode)
	jq --argjson j "$(node done)" --argjson shape "$shape" \
		'.graph.nodes.J=$j | .graph.nodes.J.evidence=[$shape] |
		 .graph.joins.J={mode:"all",inputs:["A","B"],released:true}' "$clean" >"$candidate"
	reject_unchanged "join completion mutation $name" "$candidate" \
		python3 "$GRAPH" complete "$candidate" --session session-test --evals "$evals" \
		--proof "$proof" --retro "$retro" --transcript "$transcript"
}

duplicate_terminal_contract() {
	local state="$TMP/evidence-duplicate-terminal.json" reference child terminal payload
	rm -r "$HOME/.codex/sessions"
	codex_fixture::init session-test
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	child="$(dirname "$(codex_fixture::parent session-test)")/rollout-fixture-$(jq -r '.agent_thread_id' <<<"$reference").jsonl"
	terminal=$(jq -c 'select(.payload.type == "task_complete")' "$child")
	printf '%s\n' "$terminal" >>"$child"
	payload=$(record_payload "$state")
	reject_unchanged "duplicate final terminal" "$state" python3 "$GRAPH" record-wave "$state" "$payload"
}

main() {
	local state="$TMP/evidence-shapes.json" candidate="$TMP/evidence-shape.json"
	local reference retry_reference name encoded shape benign duplicate reuse wave call envelope
	local clean control evals proof retro transcript token

	classifier_contract
	codex_fixture::init session-test
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	control="$TMP/evidence-plain-token.json"
	for token in kind attempt wave_id spawn_call_id agent_thread_id task_complete_turn_id; do
		cp "$state" "$control"
		wave=$(jq -r '.graph.active_wave.id' "$control")
		envelope=$(jq -cn --arg wave "$wave" --arg token "$token" \
			'{wave_id:$wave,results:{A:{outcome:"done",evidence:$token}}}')
		python3 "$GRAPH" record-wave "$control" "$envelope" >/dev/null
	done
	python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")" >/dev/null
	validate_worker_refs "$state"

	benign="$TMP/evidence-benign.json"
	jq '.graph.nodes.A.evidence += [{note:{message:"checked",values:[1,2,"{\"nested\":\"ordinary\"}"]}}]' "$state" >"$benign"
	validate_worker_refs "$benign"

	while IFS=$'\t' read -r name encoded; do
		shape=$(printf '%s' "$encoded" | base64 --decode)
		jq --argjson shape "$shape" '.graph.nodes.A.evidence=[$shape]' "$state" >"$candidate"
		reject_unchanged "$name" "$candidate" validate_worker_refs "$candidate"
	done < <(jq -rn --argjson ref "$reference" '[
      ["array",[$ref]], ["nested",{note:$ref}], ["whitespace",($ref+{kind:"codex_agent "})],
      ["partial",{spawn_call_id:$ref.spawn_call_id}], ["unicode reference",($ref+{kind:"codеx_agent"})],
      ["json string",($ref|tojson)]][] | [.[0],(.[1]|tojson|@base64)] | @tsv')

	reuse="$TMP/evidence-retry-binding.json"
	jq --argjson b "$(node)" '.graph.nodes.B=$b' "$state" >"$reuse"
	python3 "$GRAPH" begin-wave "$reuse" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_42 1 wave-4)
	python3 "$GRAPH" record-wave "$reuse" "$(record_payload "$reuse" B failed)" >/dev/null
	python3 "$GRAPH" begin-wave "$reuse" >/dev/null
	retry_reference=$(codex_fixture::append_attempt session-test loop_worker_42_a2 2 wave-6)
	clean="$TMP/evidence-clean-retry.json"
	cp "$reuse" "$clean"
	python3 "$GRAPH" record-wave "$clean" "$(record_payload "$clean" B)" >/dev/null

	wave=$(jq -r '.graph.active_wave.id' "$reuse")
	while IFS=$'\t' read -r name encoded; do
		shape=$(printf '%s' "$encoded" | base64 --decode)
		envelope=$(jq -cn --arg wave "$wave" --argjson shape "$shape" \
			'{wave_id:$wave,results:{B:{outcome:"done",evidence:$shape}}}')
		reject_unchanged "current result $name" "$reuse" \
			python3 "$GRAPH" record-wave "$reuse" "$envelope"
	done < <(attack_rows "$retry_reference")

	while IFS=$'\t' read -r name encoded; do
		shape=$(printf '%s' "$encoded" | base64 --decode)
		jq --argjson shape "$shape" '.graph.nodes.A.evidence += [$shape]' "$reuse" >"$candidate"
		reject_unchanged "initial binding $name" "$candidate" \
			python3 "$GRAPH" record-wave "$candidate" "$(record_payload "$candidate" B)"
	done < <(attack_rows "$retry_reference")

	evals="$TMP/evals.json"
	proof="$TMP/proof.json"
	retro="$TMP/retro.json"
	transcript="$TMP/proof.jsonl"
	write_completion_evidence "$clean" "$evals" "$proof" "$retro" "$transcript"
	candidate="$TMP/evidence-completion-control.json"
	cp "$clean" "$candidate"
	python3 "$GRAPH" complete "$candidate" --session session-test --evals "$evals" \
		--proof "$proof" --retro "$retro" --transcript "$transcript" >/dev/null
	join_completion_contract "$clean" "$candidate" "$evals" "$proof" "$retro" "$transcript" "$retry_reference"
	while IFS=$'\t' read -r name encoded; do
		shape=$(printf '%s' "$encoded" | base64 --decode)
		jq --argjson shape "$shape" '.graph.nodes.A.evidence += [$shape]' "$clean" >"$candidate"
		reject_unchanged "completion mutation $name" "$candidate" \
			python3 "$GRAPH" complete "$candidate" --session session-test --evals "$evals" \
			--proof "$proof" --retro "$retro" --transcript "$transcript"
	done < <(attack_rows "$retry_reference")

	duplicate="$TMP/evidence-exact-duplicate.json"
	jq '.graph.nodes.B=.graph.nodes.A' "$state" >"$duplicate"
	reject_unchanged "exact duplicate" "$duplicate" validate_worker_refs "$duplicate"

	reuse="$TMP/evidence-nested-reuse.json"
	jq --argjson b "$(node)" '.graph.nodes.B=$b' "$state" >"$reuse"
	python3 "$GRAPH" begin-wave "$reuse" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_42 1 wave-4)
	call=$(jq -r '.spawn_call_id' <<<"$reference")
	jq --arg call "$call" '.graph.nodes.A.evidence += [{note:{spawn_call_id:$call}}]' "$reuse" >"$reuse.tmp"
	mv "$reuse.tmp" "$reuse"
	wave=$(jq -r '.graph.active_wave.id' "$reuse")
	envelope=$(jq -cn --arg wave "$wave" '{wave_id:$wave,results:{B:{outcome:"done",evidence:"checked"}}}')
	reject_unchanged "nested reuse" "$reuse" python3 "$GRAPH" record-wave "$reuse" "$envelope"
	duplicate_terminal_contract

	printf 'PASS - native Codex recursive worker-evidence shapes\n'
}

main "$@"
