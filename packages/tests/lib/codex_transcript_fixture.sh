#!/usr/bin/env bash
# Sourced test helper; the caller owns shell options and cleanup.

codex_fixture::parent() {
	local session="$1"
	printf '%s/.codex/sessions/fixture/rollout-fixture-%s.jsonl' "$HOME" "$session"
}

codex_fixture::init() {
	local session="$1" parent
	parent=$(codex_fixture::parent "$session")
	mkdir -p "$(dirname "$parent")"
	[[ -f "$parent" ]] && return
	jq -cn --arg session "$session" '{
      timestamp:"2026-08-21T00:00:00Z",type:"session_meta",
      payload:{id:$session,thread_source:"user"}
    }' >"$parent"
}

codex_fixture::append_attempt() {
	local session="$1" task="$2" attempt="$3" wave="$4"
	local parent token call agent turn child path
	parent=$(codex_fixture::parent "$session")
	token=$(printf '%s:%s:%s' "$task" "$attempt" "$(wc -l <"$parent")" | shasum -a 256 | awk '{print substr($1,1,16)}')
	call="call_fixture_$token"
	agent="agent-fixture-$token"
	turn="turn-fixture-$token"
	path="/root/$task"
	{
		jq -cn --arg task "$task" --arg call "$call" '{
          type:"response_item",payload:{type:"function_call",name:"spawn_agent",
          arguments:({task_name:$task}|tojson),call_id:$call}}
        '
		jq -cn --arg path "$path" --arg call "$call" '{
          type:"response_item",payload:{type:"function_call_output",call_id:$call,
          output:({task_name:$path}|tojson)}}
        '
		jq -cn --arg path "$path" --arg call "$call" --arg agent "$agent" '{
          type:"event_msg",payload:{item:{type:"SubAgentActivity",id:$call,kind:"started",
          agent_thread_id:$agent,agent_path:$path}}}
        '
	} >>"$parent"
	child="$(dirname "$parent")/rollout-fixture-$agent.jsonl"
	jq -cn --arg session "$session" --arg agent "$agent" --arg path "$path" '{
      timestamp:"2026-08-21T00:00:01Z",type:"session_meta",
      payload:{id:$agent,session_id:$session,parent_thread_id:$session,
      thread_source:"subagent",agent_path:$path}
    }' >"$child"
	jq -cn --arg turn "$turn" '{
      timestamp:"2026-08-21T00:00:02Z",type:"event_msg",
      payload:{type:"task_started",turn_id:$turn}
    }' >>"$child"
	jq -cn --arg turn "$turn" '{
      timestamp:"2026-08-21T00:00:03Z",type:"event_msg",
      payload:{type:"task_complete",turn_id:$turn}
    }' >>"$child"
	jq -cn --argjson attempt "$attempt" --arg wave "$wave" --arg call "$call" \
		--arg agent "$agent" --arg turn "$turn" '{kind:"codex_agent",attempt:$attempt,
      wave_id:$wave,spawn_call_id:$call,agent_thread_id:$agent,task_complete_turn_id:$turn}'
}

codex_fixture::append_wave() {
	local state="$1" session node task attempt wave
	session=$(jq -r '.session_id' "$state")
	wave=$(jq -r '.graph.active_wave.id' "$state")
	while IFS= read -r node; do
		task="loop_worker_$(printf '%s' "$node" | od -An -tx1 | tr -d ' \n')"
		attempt=$(( $(jq -r --arg node "$node" '.graph.nodes[$node].retry.attempts' "$state") + 1 ))
		codex_fixture::append_attempt "$session" "$task" "$attempt" "$wave" >/dev/null
	done < <(jq -r '.graph.active_wave.nodes[]' "$state")
}

codex_fixture::bind_done_nodes() {
	local state="$1" session node task attempt reference temporary
	session=$(jq -r '.session_id' "$state")
	while IFS= read -r node; do
		task="loop_worker_$(printf '%s' "$node" | od -An -tx1 | tr -d ' \n')"
		attempt=$(( $(jq -r --arg node "$node" '.graph.nodes[$node].retry.attempts' "$state") + 1 ))
		reference=$(codex_fixture::append_attempt "$session" "$task" "$attempt" "wave-fixture-$attempt")
		temporary="$state.tmp"
		jq --arg node "$node" --argjson reference "$reference" \
			'.graph.nodes[$node].evidence += ["fixture evidence",$reference]' "$state" >"$temporary"
		mv "$temporary" "$state"
	done < <(jq -r '.graph.nodes as $nodes | .graph.joins as $joins |
      $nodes | to_entries[] | select(.value.status == "done" or .value.status == "skipped") |
      select($joins[.key] == null) | .key' "$state")
}
