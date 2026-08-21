#!/usr/bin/env bash
# Sourced test helper: builds a Claude Code transcript fixture.
# The caller owns shell options, $HOME/CLAUDE_PROJECTS_DIR and cleanup.
#
# Mirrors the REAL on-disk shape verified against a live session transcript
# (~/.claude/projects/<munged-cwd>/<session-id>.jsonl):
#   {"type":"assistant","uuid":...,"parentUuid":...,"sessionId":...,
#    "isSidechain":false,
#    "message":{"content":[{"type":"tool_use","id":"toolu_...","name":"Agent",
#                           "input":{"subagent_type":...,"prompt":"CODERAILS_GRAPH_DISPATCH={...}\n..."}}]}}
# The Agent tool name, the toolu_ id prefix and the untruncated .input.prompt
# carrying the dispatch envelope were all confirmed by inspection, not assumed.

claude_fixture::transcript() { # projects_dir session_id
	printf '%s/fixture-project/%s.jsonl' "$1" "$2"
}

claude_fixture::init() { # projects_dir session_id
	local path
	path=$(claude_fixture::transcript "$1" "$2")
	mkdir -p "$(dirname "$path")"
	: >"$path"
}

# Append one genuine Agent spawn carrying a CODERAILS_GRAPH_DISPATCH envelope.
# Prints the tool_use id it wrote so callers can cite (or mis-cite) it.
claude_fixture::append_spawn() { # projects_dir session_id node_id wave_id [tool_use_id] [loop_id] [revision]
	local projects="$1" session="$2" node="$3" wave="$4"
	local tool_use_id="${5:-}" loop="${6:-loop-fixture}" revision="${7:-1}"
	local path envelope
	path=$(claude_fixture::transcript "$projects" "$session")
	if [[ -z "$tool_use_id" ]]; then
		tool_use_id="toolu_$(printf '%s:%s:%s' "$node" "$wave" "$(wc -l <"$path")" |
			shasum -a 256 | awk '{print substr($1,1,24)}')"
	fi
	envelope=$(jq -cn --arg session "$session" --arg loop "$loop" \
		--argjson revision "$revision" --arg wave "$wave" --arg node "$node" \
		'{session_id:$session,loop_id:$loop,revision:$revision,wave_id:$wave,node_id:$node}')
	jq -cn --arg session "$session" --arg id "$tool_use_id" --arg node "$node" \
		--arg envelope "$envelope" '{
          type:"assistant",
          uuid:("uuid-" + $id),
          parentUuid:("parent-" + $id),
          sessionId:$session,
          isSidechain:false,
          message:{content:[{
            type:"tool_use",id:$id,name:"Agent",
            input:{description:("dispatch " + $node),
                   subagent_type:"coderails:loop-worker",
                   prompt:("CODERAILS_GRAPH_DISPATCH=" + $envelope + "\nwork unit body")}}]}
        }' >>"$path"
	printf '%s\n' "$tool_use_id"
}

# Append an unrelated non-Agent record, so cursor/offset arithmetic is exercised
# against a transcript that is not purely spawns (the real one is ~80% Bash).
claude_fixture::append_noise() { # projects_dir session_id
	local path
	path=$(claude_fixture::transcript "$1" "$2")
	jq -cn --arg session "$2" '{
          type:"assistant",uuid:("noise-" + ($session)),parentUuid:null,
          sessionId:$session,isSidechain:false,
          message:{content:[{type:"tool_use",id:"toolu_noise",name:"Bash",
                             input:{command:"true"}}]}}' >>"$path"
}

# Current transcript length — what graph_dispatch_begin_wave records as the
# wave's transcript cursor.
claude_fixture::cursor() { # projects_dir session_id
	local path
	path=$(claude_fixture::transcript "$1" "$2")
	wc -l <"$path" | tr -d ' '
}
