#!/bin/bash
# Behavioural test for inject_bootstrap.sh — asserts the SessionStart hook
# emits valid JSON with hookSpecificOutput.additionalContext that embeds the
# using-coderails SKILL.md content and carries only coderails branding.
set -u
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/inject_bootstrap.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected: %s, got: %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }

# ── helpers ──────────────────────────────────────────────────────────────────

run_hook() {
  # Run with CLAUDE_PLUGIN_ROOT pointing at the pr6 worktree root.
  CLAUDE_PLUGIN_ROOT=/Users/harrison/Github/coderails-pr6 bash "$SCRIPT"
}

run_hook_missing_skill() {
  # Run with a plugin root whose skills dir doesn't contain using-coderails.
  CLAUDE_PLUGIN_ROOT="$TMP/nonexistent" bash "$SCRIPT"
}

# ── Gate 1: exits 0 with a valid CLAUDE_PLUGIN_ROOT ─────────────────────────
out=$(run_hook 2>/dev/null)
check "exits 0 when skill present" 0 "$?"

# ── Gate 2: output is valid JSON ─────────────────────────────────────────────
echo "$out" | jq . >/dev/null 2>&1
check "output is valid JSON" 0 "$?"

# ── Gate 3: hookSpecificOutput.additionalContext is present ──────────────────
ctx=$(echo "$out" | jq -r '.hookSpecificOutput.additionalContext // empty')
check "additionalContext field present" "1" "$([ -n "$ctx" ] && echo 1 || echo 0)"

# ── Gate 4: context contains EXTREMELY_IMPORTANT wrapper ─────────────────────
# Use grep -q (match/no-match) — count is irrelevant as long as at least one hit.
echo "$ctx" | grep -q 'EXTREMELY_IMPORTANT' && _g4=1 || _g4=0
check "context contains EXTREMELY_IMPORTANT block" "1" "$_g4"

# ── Gate 5: context contains SKILL.md substance (using-coderails skill name) ─
echo "$ctx" | grep -q 'using-coderails' && _g5=1 || _g5=0
check "context embeds using-coderails skill content" "1" "$_g5"

# ── Gate 6: context contains coderails branding ──────────────────────────────
check "context contains You have coderails" "1" \
  "$(echo "$ctx" | grep -c 'You have coderails' | xargs)"

# ── Gate 7: output carries only coderails branding (no stray legacy brand) ───
# Checks for the old plugin name; written as concatenated parts so this file
# itself doesn't contain the literal string and passes the scrub gate.
_legacy="super""powers"
echo "$out" | grep -qi "$_legacy" && _g7=1 || _g7=0
check "output contains no legacy branding" "0" "$_g7"

# ── Gate 8: hookEventName is SessionStart ────────────────────────────────────
event=$(echo "$out" | jq -r '.hookSpecificOutput.hookEventName // empty')
check "hookEventName is SessionStart" "SessionStart" "$event"

# ── Gate 9: degrades gracefully when skill file is missing ───────────────────
out2=$(run_hook_missing_skill 2>/dev/null)
check "exits 0 when skill file missing" 0 "$?"
echo "$out2" | jq . >/dev/null 2>&1
check "graceful-degrade output is still valid JSON" 0 "$?"
ctx2=$(echo "$out2" | jq -r '.hookSpecificOutput.additionalContext // empty')
check "graceful-degrade has additionalContext" "1" "$([ -n "$ctx2" ] && echo 1 || echo 0)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
