#!/usr/bin/env bash
# shellcheck disable=SC2016
# shellcheck disable=SC1091
source "$(dirname "$0")/destructive_bash_gate_common.sh"

# --- Q1: mention-safe hyphenated pattern_id per deny() case arm -----------
# Each deny() call now carries a hyphenated pattern_id in the jq output
# (hookSpecificOutput.patternId) alongside the existing message fields. The
# id is MESSAGE-ONLY output text — it changes nothing about which commands
# reach deny() in the first place (the matcher regexes are untouched).
#
# Per id: (a) MENTION-SAFETY — a command whose text is just the id string
# itself must NOT be denied (the id is hyphenated specifically so it never
# matches the matcher's own whitespace-based regexes, e.g. "chmod-r-777"
# does not match "chmod[[:space:]]+-R[[:space:]]+777"). (b) NEGATIVE
# CONTROL — the real blocked literal must still deny AND must carry that
# same pattern_id in its output.
assert_pattern_id() { # desc real_blocked_cmd mention_safe_cmd expected_id
    local desc="$1" real_cmd="$2" mention_cmd="$3" expected_id="$4"
    check "$desc: mention alone -> allow" ALLOW "$(run "$(payload "$mention_cmd")")"
    check "$desc: real literal -> deny" DENY "$(run "$(payload "$real_cmd")")"
    check "$desc: deny carries pattern_id" "$expected_id" "$(run_pattern_id "$(payload "$real_cmd")")"
}

assert_pattern_id "git-reset-hard" \
    "git reset --hard HEAD~1" "echo git-reset-hard" "git-reset-hard"
assert_pattern_id "rm-rf" \
    "rm -rf /tmp/x" "echo rm-rf" "rm-rf"
assert_pattern_id "git-push-force" \
    "git push --force" "echo git-push-force" "git-push-force"
assert_pattern_id "git-clean-force" \
    "git clean -fdx" "echo git-clean-force" "git-clean-force"
assert_pattern_id "find-delete" \
    "find . -name '*.tmp' -delete" "echo find-delete" "find-delete"
assert_pattern_id "truncate-size" \
    "truncate -s0 logfile.txt" "echo truncate-size" "truncate-size"
assert_pattern_id "secure-wipe-delete" \
    "shred secret.key" "echo secure-wipe-delete" "secure-wipe-delete"
assert_pattern_id "drop-table (TABLE)" \
    "DROP TABLE users;" "echo drop-table" "drop-table"
assert_pattern_id "drop-table (DATABASE)" \
    "DROP DATABASE mydb;" "echo drop-table" "drop-table"
assert_pattern_id "drop-table (SCHEMA)" \
    "DROP SCHEMA public CASCADE;" "echo drop-table" "drop-table"
assert_pattern_id "truncate-table" \
    "TRUNCATE TABLE logs;" "echo truncate-table" "truncate-table"
assert_pattern_id "dd-if" \
    "dd if=/dev/zero of=/dev/sda" "echo dd-if" "dd-if"
assert_pattern_id "mkfs-format" \
    "mkfs.ext4 /dev/sdb1" "echo mkfs-format" "mkfs-format"
assert_pattern_id "chmod-r-777" \
    "chmod -R 777 /var/www" "echo chmod-r-777" "chmod-r-777"
assert_pattern_id "git-commit-no-verify" \
    "git commit -m 'wip' --no-verify" "echo git-commit-no-verify" "git-commit-no-verify"
# dotenv-access: the id is hyphenated AND contains no ".env" substring at all
# (it is "dotenv", not ".env"), so echoing the id cannot self-trigger the
# gate's own .env matcher — which is precisely why the id was named that way.
assert_pattern_id "dotenv-access" \
    "cat .env" "echo dotenv-access" "dotenv-access"

# --- Q1: source-drift tripwire extension — every route case arm (except the
# generic "*)" fallback, exempted below) must carry a pattern_id, so a new
# arm added later without one is caught here rather than shipping silently
# routeless AND idless. Extracted the same way as extract_fixed_labels above
# (grep -vE comment lines first) but scoped to "route=" assignment lines and
# their immediately-following "pattern_id=" assignment, keyed on line number
# adjacency within the case block.
assert_every_route_arm_has_pattern_id() {
    local gate_path="$1"
    # route_lines: 1-indexed line numbers of every non-comment "route=" assignment
    # inside the deny() case block (destructive_bash_gate.sh's case "$pat_lc" in
    # ... esac). The generic "*)" fallback's route= line is excluded by name via
    # the preceding case label check below, not by line-number exclusion, so a
    # future reordering of arms doesn't silently break the exemption.
    local awk_prog='
    /^[[:space:]]*case "\$pat_lc" in/ { in_case=1 }
    /^[[:space:]]*esac/ { in_case=0 }
    in_case && /^[[:space:]]*\*\)/ { is_fallback=1; next }
    in_case && /^[[:space:]]*[^[:space:]].*\)$/ { is_fallback=0 }
    in_case && /^[[:space:]]*route=/ && !is_fallback { print NR }
  '
    local route_lines
    route_lines=$(
        grep -vE '^[[:space:]]*#' "$gate_path" >/dev/null
        awk "$awk_prog" "$gate_path"
    )
    local missing=0
    local ln
    for ln in $route_lines; do
        # A pattern_id= assignment must appear within the same case arm — check
        # the next non-blank line after route= (the arms in this file set
        # pattern_id immediately adjacent to route, per the task's pinned shape).
        local next_line
        next_line=$(sed -n "$((ln + 1))p" "$gate_path")
        if ! printf '%s' "$next_line" | grep -qE '^[[:space:]]*pattern_id='; then
            missing=1
            printf '     MISSING pattern_id on the arm ending at route= line %s\n' "$ln"
        fi
    done
    [ "$missing" -eq 0 ]
}

if assert_every_route_arm_has_pattern_id "$HOOK"; then
    check "every non-fallback deny() case arm sets a pattern_id" DENY DENY
else
    fails=$((fails + 1))
    printf 'FAIL - every non-fallback deny() case arm sets a pattern_id\n'
fi

# --- Deliverable B: source-drift tripwire ---------------------------------
# Extracts the gate's blockable set (the 5 fixed-label `deny "..."` call
# sites, plus the monolithic `pattern=` regex line verbatim) and compares it
# against a committed expected snapshot below. This must FAIL the instant
# someone adds a new blockable pattern to the gate without also updating this
# file's EXPECTED_* snapshot — which is exactly the moment a new pattern
# would otherwise ship with no safe route and no test (the routeless
# pattern-#14 gap this whole task exists to close).
#
# Extraction reads the gate source with grep/awk only — never executes it as
# a command whose *string content* matches the gate's own blocklist (the
# extraction regexes below, e.g. 'deny "[^"$]*"' or '^pattern=', contain no
# blocklisted literal themselves, so this is safe to run directly).
#
# Comment lines are excluded (grep -vE '^[[:space:]]*#') so a *prose mention*
# of `deny "..."` in a comment (e.g. this file's own strategy comment above
# the git-clean block) is not mistaken for a real call site — confirmed this
# matters: the naive extraction (no comment filter) picked up a spurious
# 6th "label" from exactly such a comment during this file's own development.
#
# Scope: sync is enforced for the deny()-routed patterns only (the 5 fixed
# labels + the pattern= alternatives) — NOT the cp/mv/dd, sed/perl/tee, or
# command-substitution blocks further down the gate, which build their own
# jq JSON directly and never call deny(). Those three already carry their
# own specific messages and are outside this tripwire's scope by design.

extract_fixed_labels() { # gate_path -> sorted unique "deny "..."" call sites
    grep -vE '^[[:space:]]*#' "$1" | grep -oE 'deny "[^"$]*"' | sort -u
}

extract_pattern_line() { # gate_path -> the pattern= line verbatim
    grep -E '^pattern=' "$1"
}

# Committed expected snapshot — the blockable set as of this PR. Update BOTH
# this snapshot AND (deny() route arm + a behavioural test case above) in the
# SAME commit whenever a new deny() call site or pattern= alternative is
# added — that is the "one-line update with an obvious diff" the drift check
# exists to force.
EXPECTED_FIXED_LABELS='deny ".env access"
deny "find -delete"
deny "git clean (force)"
deny "git push --force"
deny "shred"
deny "truncate -s/--size"'

EXPECTED_PATTERN_LINE='pattern='"'"'\brm[[:space:]]+(-[rRfF]+|--recursive|--force)|\bgit[[:space:]]+reset[[:space:]]+--hard|\bDROP[[:space:]]+(TABLE|DATABASE|SCHEMA)\b|\bTRUNCATE[[:space:]]+TABLE\b|\bdd[[:space:]]+if=|\bmkfs\.|\bchmod[[:space:]]+-R[[:space:]]+777|\bgit[[:space:]]+commit[[:space:]]+.*--no-verify'"'"

actual_fixed_labels=$(extract_fixed_labels "$HOOK")
actual_pattern_line=$(extract_pattern_line "$HOOK")

if [ "$actual_fixed_labels" = "$EXPECTED_FIXED_LABELS" ]; then
    check "gate's fixed-label deny() call sites match the committed snapshot" DENY DENY
else
    fails=$((fails + 1))
    printf 'FAIL - gate'"'"'s fixed-label deny() call sites match the committed snapshot\n'
    printf '     the blockable set changed. Expected:\n%s\n     Actual (live gate):\n%s\n' \
        "$EXPECTED_FIXED_LABELS" "$actual_fixed_labels"
    printf '     ACTION: for each new/removed deny "<label>" call site, add a matching\n'
    printf '     lowercase case arm in deny() (destructive_bash_gate.sh) with a real safe\n'
    printf '     route (or an honest "no safe equivalent" route), add a behavioural test\n'
    printf '     case for it above, THEN update EXPECTED_FIXED_LABELS in this file to match.\n'
fi

if [ "$actual_pattern_line" = "$EXPECTED_PATTERN_LINE" ]; then
    check "gate's monolithic pattern= line matches the committed snapshot" DENY DENY
else
    fails=$((fails + 1))
    printf 'FAIL - gate'"'"'s monolithic pattern= line matches the committed snapshot\n'
    printf '     the pattern= regex changed. Expected:\n%s\n     Actual (live gate):\n%s\n' \
        "$EXPECTED_PATTERN_LINE" "$actual_pattern_line"
    printf '     ACTION: for each new alternative added to pattern=, add a matching\n'
    printf '     lowercase case arm in deny() keyed on the MATCHED SUBSTRING (not a\n'
    printf '     friendly label) with a real safe route (or an honest "no safe\n'
    printf '     equivalent" route), add a behavioural test case for it above, THEN\n'
    printf '     update EXPECTED_PATTERN_LINE in this file to match.\n'
fi

finish
