#!/bin/bash
# Behavioural test for the token-burn reduction gate wired into
# loop_stall_guard.sh — row 4 of the 2026-07-17 measures.
#
#   Row 4 — als_gate_inline_authoring: the orchestrator must not Write/Edit
#           deliverable files (anything outside the loop-state/memory/scratch
#           allowlist) in its own transcript.
#
# It BLOCKS (exit 2). Rows 1, 2 and 3 ship no gate — see SKILL.md and the
# report for why (row 1's compaction gate was removed 2026-07-22 as an
# undeliverable-recovery deadlock; rows 2 and 3 have no ungameable predicate).
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
t_write() { jq -cn --arg p "$2" --arg n "${3:-Write}" '{type:"assistant",message:{content:[{type:"tool_use",id:"w1",name:$n,input:{file_path:$p}}]}}' >> "$1"; }
t_text() { jq -cn --arg t "$2" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$1"; }

DECL="Paused.
LOOP-STOP: awaiting-input — waiting on the user"

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
# The inline-authoring transcript that BLOCKS with jq present (above) must
# fail OPEN when jq is missing — discriminating, not vacuous.
reset; T=$(t_start); t_write "$T" "/Users/harrison/Github/coderails/hooks/scripts/foo.sh"; t_text "$T" "$DECL"; write_file in-progress S1
nojq=$(env PATH="$NOJQ_BIN" bash -c "echo '$(payload "$T" S1)' | bash '$GUARD' >/dev/null 2>&1; echo \$?")
check "jq missing -> never blocks (fail-open)" 0 "$nojq"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
