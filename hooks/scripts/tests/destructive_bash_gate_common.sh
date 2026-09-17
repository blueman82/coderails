#!/bin/bash
# Behavioural test for destructive_bash_gate.sh — feeds synthetic PreToolUse Bash
# payloads and asserts allow (no deny JSON) vs deny (permissionDecision=deny).
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/destructive_bash_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0
# shellcheck disable=SC2034
TAB=$(printf '\t')

payload() { # command -> json
    jq -n --arg cmd "$1" '{"tool_name":"Bash","tool_input":{"command":$cmd}}'
}

# payload_with_cwd <command> <cwd> -> json (for branch-aware tests)
payload_with_cwd() {
    jq -n --arg cmd "$1" --arg cwd "$2" '{"tool_name":"Bash","tool_input":{"command":$cmd},"cwd":$cwd}'
}

run() { # json -> DENY|ALLOW
    local out
    out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
    if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}

run_cwd() { # payload_json cwd -> DENY|ALLOW
    local out
    out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
    if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}

# run_reason: json -> the permissionDecisionReason text (empty if allowed)
run_reason() {
    printf '%s' "$1" | bash "$HOOK" 2>/dev/null | jq -r '.hookSpecificOutput.permissionDecisionReason // ""'
}

# run_pattern_id: json -> the hookSpecificOutput.patternId field (empty if allowed/absent)
run_pattern_id() {
    printf '%s' "$1" | bash "$HOOK" 2>/dev/null | jq -r '.hookSpecificOutput.patternId // ""'
}

check() { # desc expected actual
    if [ "$2" = "$3" ]; then
        printf 'ok   - %s\n' "$1"
    else
        printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"
        fails=$((fails + 1))
    fi
}

finish() {
    if [ "$fails" -eq 0 ]; then
        echo "PASS"
        exit 0
    fi
    echo "FAILED ($fails)"
    exit 1
}

MAIN_REPO="$TMP/main_repo"
FEAT_REPO="$TMP/feat_repo"
git init "$MAIN_REPO" -q
git -C "$MAIN_REPO" checkout -b main -q 2>/dev/null || true
git init "$FEAT_REPO" -q
git -C "$FEAT_REPO" checkout -b feat/my-feature -q 2>/dev/null || git -C "$FEAT_REPO" checkout -b feat/my-feature -q 2>/dev/null || true
