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
	local state="$1" wave
	wave=$(jq -r '.graph.active_wave.id' "$state")
	jq -cn --arg wave "$wave" \
		'{wave_id:$wave,results:{A:{outcome:"done",evidence:"checked"}}}'
}

validate_worker_refs() {
	PYTHONPATH="$(dirname "$GRAPH")" python3 -c \
		'import json,sys; from graph_evidence import validate_worker_evidence; validate_worker_evidence(json.load(open(sys.argv[1], encoding="utf-8")))' "$1"
}

classifier_contract() {
	PYTHONPATH="$(dirname "$GRAPH")" python3 -c '
from graph_identity import classify_worker_evidence as classify
assert classify("codеx_agent") == (True, set())
assert classify({"spаwn_call_id": "call"}) == (True, {"call"})
assert classify("γειά σου") == (False, set())
assert classify({"ключ": "значение"}) == (False, set())
'
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

main() {
	local state="$TMP/evidence-shapes.json" candidate="$TMP/evidence-shape.json"
	local reference name encoded shape benign duplicate reuse wave call envelope

	classifier_contract
	codex_fixture::init session-test
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_attempt session-test loop_worker_41 1 wave-2)
	python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")" >/dev/null
	validate_worker_refs "$state"

	benign="$TMP/evidence-benign.json"
	jq '.graph.nodes.A.evidence += [{note:{message:"checked",values:[1,2]}}]' "$state" >"$benign"
	validate_worker_refs "$benign"

	while IFS=$'\t' read -r name encoded; do
		shape=$(printf '%s' "$encoded" | base64 --decode)
		jq --argjson shape "$shape" '.graph.nodes.A.evidence=[$shape]' "$state" >"$candidate"
		reject_unchanged "$name" "$candidate" validate_worker_refs "$candidate"
	done < <(jq -rn --argjson ref "$reference" '[
      ["array",[$ref]], ["nested",{note:$ref}], ["whitespace",($ref+{kind:"codex_agent "})],
      ["partial",{spawn_call_id:$ref.spawn_call_id}], ["unicode reference",($ref+{kind:"codеx_agent"})],
      ["json string",($ref|tojson)]][] | [.[0],(.[1]|tojson|@base64)] | @tsv')

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

	printf 'PASS - native Codex recursive worker-evidence shapes\n'
}

main "$@"
