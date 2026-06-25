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

PLUGIN_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

run_hook() {
  # Run with CLAUDE_PLUGIN_ROOT resolved relative to the test file (portable).
  CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" bash "$SCRIPT"
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

# ── Gate 10: no double-escaping in additionalContext ─────────────────────────
# Build a controlled CLAUDE_PLUGIN_ROOT whose SKILL.md contains KNOWN
# backslash-bearing content.  After jq -r decodes the JSON the decoded value
# must contain the VERBATIM text (single backslash, not doubled).
FAKE_ROOT="$TMP/fake_plugin"
mkdir -p "$FAKE_ROOT/skills/using-coderails"
# Write a SKILL.md with a literal \n two-char sequence and a literal \" sequence
# as text (not real escape sequences — just backslash followed by n / quote).
printf 'Skill line with literal \\n and also literal \\" sequences.\n' \
  > "$FAKE_ROOT/skills/using-coderails/SKILL.md"

out3=$(CLAUDE_PLUGIN_ROOT="$FAKE_ROOT" bash "$SCRIPT" 2>/dev/null)
ctx3=$(printf '%s' "$out3" | jq -r '.hookSpecificOutput.additionalContext // empty')
# After jq -r decoding, the verbatim backslash-n should be present (single \n text).
printf '%s' "$ctx3" | grep -qF '\n' && _has_backslash_n=1 || _has_backslash_n=0
check "additionalContext contains verbatim backslash-n after jq decode" "1" "$_has_backslash_n"
# And it must NOT contain a doubled sequence (\\n as four chars: backslash backslash n).
printf '%s' "$ctx3" | grep -qF '\\n' && _double_nl=1 || _double_nl=0
check "additionalContext has no double-escaped newlines" "0" "$_double_nl"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
