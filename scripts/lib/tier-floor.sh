#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  tier-floor.sh │ derive a LOWER BOUND on a PR's tier from the diff itself
#═══════════════════════════════════════════════════════════════════════════════
# The tier integer carried on a PR's eval-artifact marker is SELF-DECLARED: it
# is parsed verbatim out of a marker line the same actor wrote
# (scripts/lib/eval-artifact.sh + scripts/lib/git-common.sh), and every other
# tier-keyed check downstream consumes it as a trusted value. Nothing derives
# it from the change under review, so an actor that writes a lower tier buys
# itself less scrutiny by typing a smaller digit.
#
# This library derives a floor from facts about the DIFF that the actor does
# not author: which paths changed, how many files, how many changed lines.
# Prose — a tier_justification, an eval's evidence field, a commit message —
# is never read here. There is deliberately no override token, env escape, or
# config opt-out: an escape the actor can write is the same hole one level up.
#
# The floor is a LOWER bound, not an assignment. A claim at or above the floor
# passes through untouched (claiming MORE scrutiny is never an attack, so
# there is nothing to defend against there). A claim BELOW the floor is a
# misstatement of the change's shape and blocks. The claim is NEVER silently
# rewritten to the floor — a rewrite would let the dishonest claim succeed
# under a different number and hide that the mismatch happened at all.
#
# Honest boundary — what this CANNOT do. The floor is derived from shape
# (paths, counts), so it enforces "this change is at least this big / touches
# this surface". It cannot count WORK-UNITS, which is what separates tier 1
# from tier 2 in skills/task-evals/SKILL.md's predicate. Three independent
# work-units bundled into forty ordinary-path lines derive a floor of 0 here
# and a tier-1 claim on them passes this check. That boundary is semantic and
# stays with the tier-gate daemon's model judge (scripts/tier-gate/). This is
# a deterministic, always-on complement to that judge, never a replacement.
#
# Guard-script compatible: no `set -euo pipefail` (sourced into scripts that
# intentionally don't set it).

# ─── Calibration ──────────────────────────────────────────────────────────────
# Every threshold below was measured against the real merged-PR population of
# this repo (`gh pr view <n> --json additions,deletions,changedFiles`), not
# invented. Sampled shapes:
#     1 file /    2 lines   honest tier 0
#     1 file /    3 lines   honest tier 0
#     1 file /   82 lines   over the tier-0 line cap
#     1 file /  205 lines   a dishonest tier-0 claim the caps exist to catch
#     2 files /  121 lines  honest tier 1
#     4 files /  334 lines  honest tier 1
#     5 files /  191 lines  honest tier 1
#    10 files / 1146 lines  a dishonest tier-1 claim observed live
#
# TIER_FLOOR_MAX_FILES / TIER_FLOOR_MAX_LINES mirror the tier-0 size caps the
# tier-gate daemon already uses (TIER_GATE_MAX_FILES=3 / TIER_GATE_MAX_LINES=80
# in scripts/tier-gate/tier-gate-runner.sh, calibrated there against the same
# 205-line and 3-line shapes). They are restated rather than sourced because
# the daemon runs root-owned from its own install directory and must not
# depend on this repo's lib/ being present; the values are deliberately
# identical and any change to one must change the other.
TIER_FLOOR_MAX_FILES="${TIER_FLOOR_MAX_FILES:-3}"
TIER_FLOOR_MAX_LINES="${TIER_FLOOR_MAX_LINES:-80}"

# TIER_FLOOR_TIER2_FILES / TIER_FLOOR_TIER2_LINES: the size above which a
# change is too sweeping to be a tier-1 "standard" claim. Set above the
# honest tier-1 band actually observed (max 5 files, max 334 lines) with
# margin, and below the 10-file/1146-line dishonest shape — so no PR in the
# sampled honest population is floored to 2, and a change an order of
# magnitude past that band is. Margin is deliberate on both sides: a floor
# tuned to sit just past the largest honest PR would flip on the next
# slightly-larger honest one.
TIER_FLOOR_TIER2_FILES="${TIER_FLOOR_TIER2_FILES:-8}"
TIER_FLOOR_TIER2_LINES="${TIER_FLOOR_TIER2_LINES:-600}"

# TIER_FLOOR_INFRA_PATHS: paths whose change alters the enforcement machinery
# itself — the hooks that block, the scripts that gate, the CI that runs, and
# the config that switches them on. A tier-0 claim means "single work-unit,
# no outward surface, already covered by an existing test"; granting that
# exemption to a change in the scrutiny machinery exempts the scrutiny code
# from scrutiny. Floor 1, at any size, so such a change always carries evals.
# Matched against each path in the file list as an ERE, anchored at the start
# so a path is matched by prefix and never by a substring elsewhere in it.
TIER_FLOOR_INFRA_PATHS='^(hooks/|scripts/|\.github/|\.claude/workflow\.config\.yaml)'

# TIER_FLOOR_GATE_PATHS: the gate machinery's OWN source — the tier-gate
# daemon and this floor library. Automation editing its own leash is the
# maximal-scrutiny case: a change here can disable every other check, so it
# floors at 2 and can never be claimed as anything less. This mirrors (and
# deliberately overlaps) the daemon's own self-edit denylist
# (TIER_GATE_PATH_DENYLIST) — two independent layers refusing the same class
# of change, so neither one being absent or inactive leaves it unguarded.
TIER_FLOOR_GATE_PATHS='^(scripts/tier-gate/|scripts/lib/tier-floor\.sh)'

# tier_floor::derive <filelist> <file_count> <line_count>
# Echoes the derived floor: 0, 1 or 2. Always rc 0 — this reports a floor, it
# does not decide anything; tier_floor::check_claim is what blocks.
# <filelist> is newline-separated paths (as from `gh pr diff --name-only` or
# the daemon's own /pulls/{n}/files fetch). Counts are passed in rather than
# recomputed so the caller controls the source of truth for both, and so this
# function stays pure (no forks, no network, testable in isolation).
#
# Highest floor wins: the checks are ordered most-severe first and return on
# the first match, so a gate-source path in a one-line diff still derives 2.
tier_floor::derive() {
    local filelist="$1" file_count="$2" line_count="$3"

    # Non-numeric counts are treated as 0 rather than erroring: this function
    # has no error channel (it always echoes a floor), and check_claim below
    # rejects unusable evidence before it ever gets here. A malformed count
    # therefore cannot RAISE a floor spuriously; the path checks still apply.
    [[ "$file_count" =~ ^[0-9]+$ ]] || file_count=0
    [[ "$line_count" =~ ^[0-9]+$ ]] || line_count=0

    # Floor 2 — the gate's own source.
    if printf '%s\n' "$filelist" | grep -Eq "$TIER_FLOOR_GATE_PATHS"; then
        printf '2'
        return 0
    fi

    # Floor 2 — a change too sweeping to be "standard" work.
    if [[ "$file_count" -gt "$TIER_FLOOR_TIER2_FILES" || "$line_count" -gt "$TIER_FLOOR_TIER2_LINES" ]]; then
        printf '2'
        return 0
    fi

    # Floor 1 — the enforcement machinery.
    if printf '%s\n' "$filelist" | grep -Eq "$TIER_FLOOR_INFRA_PATHS"; then
        printf '1'
        return 0
    fi

    # Floor 1 — past the tier-0 size caps. Tier 0 means a single self-
    # contained work-unit, and a single work-unit is small; past the cap it
    # is not tier-0 work by the predicate's own definition.
    if [[ "$file_count" -gt "$TIER_FLOOR_MAX_FILES" || "$line_count" -gt "$TIER_FLOOR_MAX_LINES" ]]; then
        printf '1'
        return 0
    fi

    printf '0'
    return 0
}

# tier_floor::check_claim <claimed_tier> <filelist> <file_count> <line_count>
# The decision function. Exit codes:
#   0 = the claim is at or above the derived floor. Nothing printed.
#   1 = the claim is BELOW the derived floor. A named reason is printed on
#       stdout, including the claimed tier, the derived floor, why the floor
#       is what it is, and the recovery path.
#   2 = the evidence is unusable (the claimed tier is not a single digit, or
#       the file list is empty). Fail-closed on evidence: an empty file list
#       would zero every count and sail through every size cap, so it is
#       never treated as "nothing to see". Callers distinguish rc 2 from rc 1
#       because they mean different things — rc 1 is a lie about a diff that
#       WAS read, rc 2 is a diff that could not be read. A caller whose diff
#       fetch failed for infrastructure reasons (network, gh error) must not
#       call this at all; see the call sites for that split.
tier_floor::check_claim() {
    local claimed_tier="$1" filelist="$2" file_count="$3" line_count="$4"

    if ! [[ "$claimed_tier" =~ ^[0-9]$ ]]; then
        printf 'tier-floor: unusable claimed tier (%s) — expected a single digit.\n' "$claimed_tier"
        return 2
    fi

    # An empty file list is unusable evidence, not an empty diff: every count
    # derived from it is zero, which passes every cap below vacuously.
    if [[ -z "${filelist//[[:space:]]/}" ]]; then
        printf 'tier-floor: unusable evidence — the changed-file list is empty, so no floor can be derived. Do not treat this as a pass.\n'
        return 2
    fi

    local floor
    floor=$(tier_floor::derive "$filelist" "$file_count" "$line_count")

    if [[ "$claimed_tier" -ge "$floor" ]]; then
        return 0
    fi

    # Below the floor — block, and say exactly which fact forced the floor so
    # the reader can check it against the diff themselves.
    local why gate_path infra_path
    gate_path=$(printf '%s\n' "$filelist" | grep -E "$TIER_FLOOR_GATE_PATHS" | head -1)
    infra_path=$(printf '%s\n' "$filelist" | grep -E "$TIER_FLOOR_INFRA_PATHS" | head -1)
    if [[ -n "$gate_path" ]]; then
        why="it changes the gate's own source ($gate_path)"
    elif [[ "$file_count" -gt "$TIER_FLOOR_TIER2_FILES" || "$line_count" -gt "$TIER_FLOOR_TIER2_LINES" ]]; then
        why="it changes $file_count files / $line_count lines, past the tier-2 threshold of $TIER_FLOOR_TIER2_FILES files / $TIER_FLOOR_TIER2_LINES lines"
    elif [[ -n "$infra_path" ]]; then
        why="it changes enforcement infrastructure ($infra_path)"
    else
        why="it changes $file_count files / $line_count lines, past the tier-0 cap of $TIER_FLOOR_MAX_FILES files / $TIER_FLOOR_MAX_LINES lines"
    fi

    printf 'tier-floor: claimed tier %s is below the floor %s derived from this diff — %s. The claim understates the change. Raise the claimed tier to %s or higher (which means MORE evals, not fewer) and re-run /coderails:post-evals; the claim is never rewritten for you.\n' \
        "$claimed_tier" "$floor" "$why" "$floor"
    return 1
}

# tier_floor::gate_pr <claimed_tier> <pr_number>
# The call-site wrapper both enforcement points share. Fetches the changed
# files for <pr_number> from GitHub — an independent source, never the
# artifact the actor wrote — and runs tier_floor::check_claim against them.
#
# The infra-vs-evidence split lives HERE, and getting it right is the whole
# point of this function existing rather than being inlined twice:
#
#   * The `gh` command itself exiting non-zero is INFRASTRUCTURE (no network,
#     bad auth, API down). The diff could not be read at all, so there is no
#     evidence to contradict the claim, and blocking every merge in the repo
#     on a network blip is not a defensible posture. rc 3 — the caller
#     proceeds and the other gates (eval GO/NO-GO, review artifact, and the
#     tier-review status when configured) still apply.
#
#   * A SUCCESSFUL fetch that yields an empty or unusable file list is
#     EVIDENCE, and it fails closed. This is the important half: every count
#     derived from an empty list is zero, and zero passes every size cap
#     vacuously, so treating "fetched fine, got nothing" as a pass would hand
#     back the exact bypass this library exists to close. The tier-gate
#     daemon takes the identical posture on its own fetch (an empty file list
#     is a hard error there, not a skip).
#
# Exit codes:
#   0 = claim is at or above the derived floor (pass)
#   1 = claim is below the floor (block) + reason on stdout
#   2 = fetch succeeded but the evidence is unusable (block) + reason
#   3 = the fetch itself failed — infrastructure, do NOT block; a diagnostic
#       is printed on stdout for the caller to log
tier_floor::gate_pr() {
    local claimed_tier="$1" num="$2"

    local filelist
    if ! filelist=$(gh pr diff "$num" --name-only 2>/dev/null); then
        printf 'tier-floor: could not fetch the changed-file list for PR %s (gh exited non-zero) — infrastructure failure, the tier floor was not evaluated for this merge.\n' "$num"
        return 3
    fi

    # Counts come from the same fetch family, never from the artifact. A
    # failed --stat is NOT fatal on its own: the path-keyed floors (infra,
    # gate-source) still hold without it, and check_claim treats a
    # non-numeric count as 0 so a missing count can only ever LOWER a
    # derived floor, never raise one spuriously.
    local file_count line_count
    file_count=$(printf '%s\n' "$filelist" | grep -c .)
    line_count=$(gh pr view "$num" --json additions,deletions \
        -q '.additions + .deletions' 2>/dev/null) || line_count=0

    local out rc=0
    out=$(tier_floor::check_claim "$claimed_tier" "$filelist" "$file_count" "$line_count") || rc=$?
    [[ -n "$out" ]] && printf '%s\n' "$out"
    return $rc
}
