#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GRAPH="$ROOT/packages/codex/skills/agentic-loop/scripts/graph.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
state="$TMP/progress.json"
evals="$TMP/evals.json"

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
