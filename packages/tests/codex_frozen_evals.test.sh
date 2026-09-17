#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GRAPH="$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
# shellcheck source=packages/tests/lib/codex_transcript_fixture.sh
source "$ROOT/packages/tests/lib/codex_transcript_fixture.sh"
codex_fixture::init session-test
state="$TMP/progress.json"
evals="$TMP/evals.json"

mkdir "$TMP/no-evals"
jq -n '{
  schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:2,status:"in-progress",
  graph:{nodes:{A:{status:"running",outcome:"running",retry:{attempts:0,max:1},evidence:[]}},
         edges:[],joins:{},active_wave:{id:"wave-2",revision:2,nodes:["A"],transcript_cursor:1},hard_stop:null}
}' >"$state"
jq -n --arg sha "$(git -C "$ROOT" rev-parse HEAD)" '{
  schema_version:1,scope:"loop",task_ref:"loop-test",verification_level:1,
  verification_justification:"frozen dispatch contract",frozen_sha:$sha,
  session_id:"session-test",loop_id:"loop-test",revision:1,
  evals:[{id:"E1",priority:"P0",mode:"agent-run",status:"pending",evidence:""}],
  amendments:[],result:null,grading:null
}' >"$evals"

python3 "$GRAPH" authorize-dispatch "$state" --session session-test --task loop_worker_41 --evals "$evals" >/dev/null

jq -n '{
  schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:1,status:"in-progress",
  graph:{nodes:{A:{status:"pending",outcome:"pending",retry:{attempts:0,max:1},evidence:[]}},
         edges:[],joins:{},active_wave:null,hard_stop:null}
}' >"$TMP/no-evals/begin.json"
if python3 "$GRAPH" begin-wave "$TMP/no-evals/begin.json" >/dev/null 2>&1; then
  printf 'FAIL - begin-wave accepted missing dispatch evals\n' >&2
  exit 1
fi

jq -n '{
  schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:1,status:"in-progress",
  graph:{nodes:{A:{status:"pending",outcome:"pending",retry:{attempts:0,max:1},evidence:[]}},
         edges:[],joins:{},active_wave:null,hard_stop:null}
}' >"$TMP/cancel.json"
python3 "$GRAPH" begin-wave "$TMP/cancel.json" >/dev/null
python3 "$GRAPH" cancel-unspawned-wave "$TMP/cancel.json" --session session-test >/dev/null
jq -e '.graph.cancelled_waves == [{"id":"wave-2","revision":2}]' "$TMP/cancel.json" >/dev/null
python3 "$GRAPH" begin-wave "$TMP/cancel.json" >/dev/null
codex_fixture::append_attempt session-test loop_worker_41 1 wave-4 >/dev/null
if python3 "$GRAPH" cancel-unspawned-wave "$TMP/cancel.json" --session session-test >/dev/null 2>&1; then
  printf 'FAIL - cancel-unspawned-wave accepted a spawned worker\n' >&2
  exit 1
fi

jq -n '{
  schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:4,status:"in-progress",
  graph:{nodes:{A:{status:"running",outcome:"running",retry:{attempts:0,max:1},evidence:[]}},
         edges:[],joins:{},active_wave:{id:"wave-4",revision:4,nodes:["A"],transcript_cursor:1},hard_stop:null}
}' >"$TMP/legacy-cancel.json"
python3 "$GRAPH" acknowledge-cancelled-wave "$TMP/legacy-cancel.json" --session session-test --wave wave-2 >/dev/null
jq -e '.graph.cancelled_waves == [{"id":"wave-2","revision":2}]' "$TMP/legacy-cancel.json" >/dev/null
if python3 "$GRAPH" acknowledge-cancelled-wave "$TMP/legacy-cancel.json" --session session-test --wave wave-2 >/dev/null 2>&1; then
	printf 'FAIL - acknowledge-cancelled-wave accepted a duplicate repair\n' >&2
	exit 1
fi

jq -n '{
  schema_version:2,session_id:"session-test",loop_id:"loop-test",revision:4,status:"in-progress",
  graph:{nodes:{A:{status:"done",outcome:"done",retry:{attempts:0,max:1},evidence:[]},B:{status:"hard-stop",outcome:"hard-stop",retry:{attempts:1,max:1},evidence:["failed"]},C:{status:"pending",outcome:"pending",retry:{attempts:0,max:1},evidence:[]}},
         edges:[{from:"A",to:"B"},{from:"B",to:"C"}],joins:{},active_wave:null,hard_stop:{node:"B",reason:"retry exhaustion",evidence:"failed"}}
}' >"$TMP/remediation.json"
python3 "$GRAPH" add-remediation-node "$TMP/remediation.json" --session session-test --source B --node B-remediation >/dev/null
jq -e '.graph.nodes.B.status == "failed" and .graph.nodes["B-remediation"].status == "pending" and .graph.edges == [{"from":"A","to":"B-remediation"},{"from":"B-remediation","to":"C"}] and .graph.hard_stop == null' "$TMP/remediation.json" >/dev/null

PYTHONPATH="$(dirname "$GRAPH")" python3 - <<'PY'
from pathlib import Path

import graph_evidence

reference = {
    "kind": "codex_agent",
    "attempt": 1,
    "spawn_call_id": "spawn",
    "agent_thread_id": "thread",
    "task_complete_turn_id": "turn",
}
state = {
    "session_id": "session-test",
    "revision": 7,
    "status": "in-progress",
    "graph": {
        "active_wave": None,
        "cancelled_waves": [{"id": "wave-4", "revision": 4}],
        "joins": {},
        "nodes": {
            "A": {"status": "done", "retry": {"attempts": 0}, "evidence": [{**reference, "wave_id": "wave-2"}]},
            "B": {"status": "done", "retry": {"attempts": 0}, "evidence": [{**reference, "spawn_call_id": "spawn-b", "agent_thread_id": "thread-b", "task_complete_turn_id": "turn-b", "wave_id": "wave-6"}]},
        },
    },
}
graph_evidence._thread_transcript = lambda _: Path("unused")
graph_evidence._records = lambda *_: []
graph_evidence._verify_reference = lambda *_: 1
assert graph_evidence._stored_references(state, False) == {"spawn", "thread", "turn", "spawn-b", "thread-b", "turn-b"}
PY

jq '.frozen_sha = ""' "$evals" >"$evals.tmp" && mv "$evals.tmp" "$evals"
if python3 "$GRAPH" authorize-dispatch "$state" --session session-test --task loop_worker_41 --evals "$evals" >/dev/null 2>&1; then
  printf 'FAIL - malformed frozen suite authorized dispatch\n' >&2
  exit 1
fi

jq '.frozen_sha = "valid-frozen-sha"' "$evals" >"$evals.tmp" && mv "$evals.tmp" "$evals"
if PYTHONPATH="$(dirname "$GRAPH")" python3 - "$state" "$evals" <<'PY' >/dev/null 2>&1
import json
import sys
from pathlib import Path
from graph_evidence import validate_evals

with open(sys.argv[1], encoding="utf-8") as handle:
    validate_evals(json.load(handle), 2, Path(sys.argv[2]))
PY
then
  printf 'FAIL - frozen suite satisfied completion validation\n' >&2
  exit 1
fi

printf 'PASS - frozen evals authorize dispatch but never completion\n'
