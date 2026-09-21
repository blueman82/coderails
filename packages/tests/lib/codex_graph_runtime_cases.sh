#!/usr/bin/env bash
# Sourced by codex_graph_runtime_adversarial.test.sh after its fixtures are configured.

test_native_transcript_evidence() {
	local state reference parent child payload

	reset_transcript
	state="$TMP/native-success.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	command_rejected_unchanged "$state" python3 "$GRAPH" cancel-unspawned-wave "$state" --session session-test
	python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")" >/dev/null
	validate_worker_refs "$state"

	reset_transcript
	state="$TMP/native-call-id.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2)
	parent=$(codex_fixture::parent session-test)
	jq -c 'if .type == "event_msg" then .payload.item.id="foreign-call" else . end' "$parent" >"$parent.tmp"
	mv "$parent.tmp" "$parent"
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"

	reset_transcript
	state="$TMP/native-type.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	parent=$(codex_fixture::parent session-test)
	jq -c 'if .type == "response_item" then .payload.arguments=(.payload.arguments|fromjson|.agent_type="source-auditor"|tojson) else . end' "$parent" >"$parent.tmp"
	mv "$parent.tmp" "$parent"
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"

	reset_transcript
	state="$TMP/native-task.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	parent=$(codex_fixture::parent session-test)
	jq -c 'if .type == "response_item" then .payload.arguments=(.payload.arguments|fromjson|.task_name="loop_worker_42"|tojson) else . end' "$parent" >"$parent.tmp"
	mv "$parent.tmp" "$parent"
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"

	reset_transcript
	state="$TMP/native-path.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2)
	child="$(dirname "$(codex_fixture::parent session-test)")/rollout-fixture-$(jq -r '.agent_thread_id' <<<"$reference").jsonl"
	jq -c 'if .type == "session_meta" then .payload.source.subagent.thread_spawn.agent_path="/root/foreign" else . end' "$child" >"$child.tmp"
	mv "$child.tmp" "$child"
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"

	reset_transcript
	state="$TMP/native-foreign.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2)
	child="$(dirname "$(codex_fixture::parent session-test)")/rollout-fixture-$(jq -r '.agent_thread_id' <<<"$reference").jsonl"
	jq -c 'if .type == "session_meta" then .payload.parent_thread_id="foreign" else . end' "$child" >"$child.tmp"
	mv "$child.tmp" "$child"
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"

	reset_transcript
	state="$TMP/native-failed.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	reference=$(codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2)
	child="$(dirname "$(codex_fixture::parent session-test)")/rollout-fixture-$(jq -r '.agent_thread_id' <<<"$reference").jsonl"
	jq -c 'if .payload.type == "task_complete" then .payload.type="turn_aborted" else . end' "$child" >"$child.tmp"
	mv "$child.tmp" "$child"
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"

	reset_transcript
	state="$TMP/native-duplicate.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"

	reset_transcript
	state="$TMP/native-stale.json"
	write_graph "$state" "$(jq -cn --argjson a "$(node)" '{A:$a}')"
	codex_fixture::append_native_attempt session-test loop_worker_41 1 wave-2 >/dev/null
	python3 "$GRAPH" begin-wave "$state" >/dev/null
	command_rejected_unchanged "$state" python3 "$GRAPH" record-wave "$state" "$(record_payload "$state")"
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
