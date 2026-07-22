#!/bin/bash
# Behavioural test for the token-burn reduction gates wired into
# loop_stall_guard.sh — rows 1 and 4 of the 2026-07-17 measures.
#
#   Row 1 — als_gate_compaction_per_stop: on ANY active-loop stop, manual
#           compactions must be >= successful PR merges observed so far.
#   Row 4 — als_gate_inline_authoring: the orchestrator must not Write/Edit
#           deliverable files (anything outside the loop-state/memory/scratch
#           allowlist) in its own transcript.
#
# Both BLOCK (exit 2). Rows 2 and 3 ship no gate — see SKILL.md and the report
# for why no ungameable blocking predicate is constructible for them.
#
# State lives under a temp dir, never the repo and never real ~/.claude.
set -u
GUARD="$(cd "$(dirname "$0")/.." && pwd)/loop_stall_guard.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1
CWD="/work/project"
SLUG="-work-project"
fails=0

file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }
payload() { printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","stop_hook_active":%s}' "$1" "$2" "$CWD" "${3:-false}"; }
run() { echo "$1" | bash "$GUARD" >/dev/null 2>&1; echo $?; }
# Capture the guard's STDERR only (the block message); stdout is discarded.
# Order matters: stdout must be sent to /dev/null BEFORE stderr is duped onto
# it, or stderr follows stdout into /dev/null and the message is lost.
run_msg() { { echo "$1" | bash "$GUARD" >/dev/null; } 2>&1; }
check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }
write_file() { local dir; dir=$(file_dir "$2"); mkdir -p "$dir"; printf '{"schema_version":2,"status":"%s","session_id":"%s","completed_marker":0}' "$1" "$2" > "$dir/progress.json"; }

# ── transcript builders ─────────────────────────────────────────────────────
# start a transcript with an agentic-loop invocation (makes it an active loop)
t_start() { local out="$TMP/t_${RANDOM}_$$.jsonl"; : > "$out"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
  printf '%s' "$out"; }
# a SUCCESSFUL merge: Bash tool_use + a non-error tool_result for that id
t_merge() { local f="$1" id="m_${RANDOM}_$$"
  jq -cn --arg i "$id" --arg c "gh pr merge 42 --squash --delete-branch" \
    '{type:"assistant",message:{content:[{type:"tool_use",id:$i,name:"Bash",input:{command:$c}}]}}' >> "$f"
  jq -cn --arg i "$id" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$i,is_error:false}]}}' >> "$f"; }
# a FAILED merge attempt: tool_result carries is_error true
t_merge_failed() { local f="$1" id="mf_${RANDOM}_$$"
  jq -cn --arg i "$id" --arg c "gh pr merge 99 --squash --delete-branch" \
    '{type:"assistant",message:{content:[{type:"tool_use",id:$i,name:"Bash",input:{command:$c}}]}}' >> "$f"
  jq -cn --arg i "$id" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$i,is_error:true}]}}' >> "$f"; }
# a merge QUERY (read-only) — must never count as a merge
t_merge_query() { local f="$1" id="q_${RANDOM}_$$"
  jq -cn --arg i "$id" --arg c 'gh pr view 42 --json state,mergeable,mergedAt' \
    '{type:"assistant",message:{content:[{type:"tool_use",id:$i,name:"Bash",input:{command:$c}}]}}' >> "$f"
  jq -cn --arg i "$id" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$i,is_error:false}]}}' >> "$f"; }
t_compact() { printf '%s\n' '{"type":"system","subtype":"compact_boundary","compactMetadata":{"trigger":"manual","preTokens":100,"postTokens":10}}' >> "$1"; }
t_autocompact() { printf '%s\n' '{"type":"system","subtype":"compact_boundary","compactMetadata":{"trigger":"auto","preTokens":100,"postTokens":10}}' >> "$1"; }
t_write() { jq -cn --arg p "$2" --arg n "${3:-Write}" '{type:"assistant",message:{content:[{type:"tool_use",id:"w1",name:$n,input:{file_path:$p}}]}}' >> "$1"; }
t_text() { jq -cn --arg t "$2" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$1"; }

DECL="Paused.
LOOP-STOP: awaiting-input — waiting on the user"

echo "== ROW 1: compaction-per-stop gate =="

# Baseline: an active loop with NO merges needs no compaction.
reset; T=$(t_start); t_text "$T" "$DECL"; write_file in-progress S1
check "no merges, no compaction -> allow" 0 "$(run "$(payload "$T" S1)")"

# THE CORE CASE — the exact 2026-07-17 failure: merges happened, zero compactions.
reset; T=$(t_start); t_merge "$T"; t_text "$T" "$DECL"; write_file in-progress S1
check "1 successful merge, 0 compactions -> BLOCK" 2 "$(run "$(payload "$T" S1)")"

# Doing the thing clears it — the recovery path must actually work.
reset; T=$(t_start); t_merge "$T"; t_compact "$T"; t_text "$T" "$DECL"; write_file in-progress S1
check "1 merge, 1 manual compaction -> allow" 0 "$(run "$(payload "$T" S1)")"

# Per-stop invariant: the second merge needs its own compaction.
reset; T=$(t_start); t_merge "$T"; t_compact "$T"; t_merge "$T"; t_text "$T" "$DECL"; write_file in-progress S1
check "2 merges, 1 compaction -> BLOCK" 2 "$(run "$(payload "$T" S1)")"
reset; T=$(t_start); t_merge "$T"; t_compact "$T"; t_merge "$T"; t_compact "$T"; t_text "$T" "$DECL"; write_file in-progress S1
check "2 merges, 2 compactions -> allow" 0 "$(run "$(payload "$T" S1)")"

# An AUTO compaction is not the mandated manual boundary action.
reset; T=$(t_start); t_merge "$T"; t_autocompact "$T"; t_text "$T" "$DECL"; write_file in-progress S1
check "auto compaction does not satisfy the manual mandate -> BLOCK" 2 "$(run "$(payload "$T" S1)")"

# A FAILED merge is not a merge — must not false-block.
reset; T=$(t_start); t_merge_failed "$T"; t_text "$T" "$DECL"; write_file in-progress S1
check "failed merge attempt does not demand a compaction -> allow" 0 "$(run "$(payload "$T" S1)")"

# A read-only merge QUERY is not a merge — the false-positive that would make
# this gate unusable (real transcripts are full of `gh pr view ... mergeable`).
reset; T=$(t_start); t_merge_query "$T"; t_text "$T" "$DECL"; write_file in-progress S1
check "merge query does not count as a merge -> allow" 0 "$(run "$(payload "$T" S1)")"

# The block message must name the recovery action.
reset; T=$(t_start); t_merge "$T"; t_text "$T" "$DECL"; write_file in-progress S1
msg=$(run_msg "$(payload "$T" S1)")
case "$msg" in *"/compact"*) rec=1 ;; *) rec=0 ;; esac
check "block message names the /compact recovery path" 1 "$rec"

# Fires on the `complete` declaration too — the loop cannot exit past it.
# Asserts on the MESSAGE, not just exit 2: a bare exit-code check here passes
# even with no compaction gate at all, because the sibling retro/proof gates
# also block a `complete` stop. Keying on this gate's own text is what makes
# the assertion discriminate.
reset; T=$(t_start); t_merge "$T"; t_text "$T" "All done.
LOOP-STOP: complete — merged"; write_file in-progress S1
mkdir -p "$(file_dir S1)"; printf '%s' '{"schema_version":1}' > "$(file_dir S1)/retro.json"
printf '%s' '{"schema_version":2,"status":"in-progress","session_id":"S1","completed_marker":0,"proof_disposition":"none: n/a"}' > "$(file_dir S1)/progress.json"
cmsg=$(run_msg "$(payload "$T" S1)")
case "$cmsg" in *"compact"*) cblk=1 ;; *) cblk=0 ;; esac
check "complete declaration with unbalanced merges -> BLOCK on compaction" 1 "$cblk"

echo "== ROW 4: inline-authoring gate =="

# Loop-state writes are the orchestrator's legitimate output.
reset; T=$(t_start); t_write "$T" "$CLAUDE_AGENTIC_LOOP_DIR/$SLUG/S1/progress.json"; t_text "$T" "$DECL"; write_file in-progress S1
check "loop-state progress.json write -> allow" 0 "$(run "$(payload "$T" S1)")"
reset; T=$(t_start); t_write "$T" "$CLAUDE_AGENTIC_LOOP_DIR/$SLUG/S1/spec.md"; t_text "$T" "$DECL"; write_file in-progress S1
check "loop-state spec.md write -> allow" 0 "$(run "$(payload "$T" S1)")"

# Memory + scratchpad are legitimate orchestrator surfaces.
reset; T=$(t_start); t_write "$T" "$HOME/.claude/projects/-Users-x/memory/MEMORY.md"; t_text "$T" "$DECL"; write_file in-progress S1
check "memory write -> allow" 0 "$(run "$(payload "$T" S1)")"
reset; T=$(t_start); t_write "$T" "/private/tmp/claude-501/x/scratchpad/notes.md"; t_text "$T" "$DECL"; write_file in-progress S1
check "scratchpad write -> allow" 0 "$(run "$(payload "$T" S1)")"

# THE VIOLATION: orchestrator authoring a deliverable in the repo.
reset; T=$(t_start); t_write "$T" "/Users/harrison/Github/coderails/hooks/scripts/foo.sh"; t_text "$T" "$DECL"; write_file in-progress S1
check "repo source file written inline -> BLOCK" 2 "$(run "$(payload "$T" S1)")"
reset; T=$(t_start); t_write "$T" "/Users/harrison/Github/coderails/docs/design.md" Edit; t_text "$T" "$DECL"; write_file in-progress S1
check "repo doc edited inline -> BLOCK" 2 "$(run "$(payload "$T" S1)")"

# The block message must name the recovery action (delegate).
reset; T=$(t_start); t_write "$T" "/Users/harrison/Github/coderails/docs/design.md"; t_text "$T" "$DECL"; write_file in-progress S1
msg=$(run_msg "$(payload "$T" S1)")
case "$msg" in *"worker"*|*"delegate"*) rec4=1 ;; *) rec4=0 ;; esac
check "row 4 block message names the delegate recovery path" 1 "$rec4"

echo "== fail-open on infrastructure =="
NOJQ_BIN="$TMP/nojq-bin"; mkdir -p "$NOJQ_BIN"
for _t in bash sh dirname grep sleep tail printf mv rm cat sed awk date mkdir env basename cut tr paste stat find; do
  _p=$(command -v "$_t" 2>/dev/null); [ -n "$_p" ] && ln -sf "$_p" "$NOJQ_BIN/$_t"
done
reset; T=$(t_start); t_merge "$T"; t_text "$T" "$DECL"; write_file in-progress S1
nojq=$(env PATH="$NOJQ_BIN" bash -c "echo '$(payload "$T" S1)' | bash '$GUARD' >/dev/null 2>&1; echo \$?")
check "jq missing -> never blocks (fail-open)" 0 "$nojq"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
