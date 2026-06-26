#!/bin/bash
# Behavioural test for enforce_pr_workflow.sh — feeds synthetic PreToolUse Bash
# payloads with fixture transcripts and asserts allow (ALLOW) vs deny (DENY).
# All state lives under a temp dir; no network or git repo needed.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/enforce_pr_workflow.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
REPO="$TMP/repo"
mkdir -p "$REPO/.claude"

# Initialize a minimal git repo so the hook can resolve git_root.
git -C "$TMP" init -q repo
git -C "$REPO" config user.email t@t.t
git -C "$REPO" config user.name t
git -C "$REPO" commit -q --allow-empty -m init

# Create workflow.config.yaml so the opt-in gate passes for DENY cases.
printf 'jira: null\n' > "$REPO/.claude/workflow.config.yaml"

# REPO_NO_CONFIG has no workflow.config.yaml — used for Case 7 (NO_CONFIG -> ALLOW).
REPO_NO_CONFIG="$TMP/repo_noconfig"
mkdir -p "$REPO_NO_CONFIG"
git -C "$TMP" init -q repo_noconfig
git -C "$REPO_NO_CONFIG" config user.email t@t.t
git -C "$REPO_NO_CONFIG" config user.name t
git -C "$REPO_NO_CONFIG" commit -q --allow-empty -m init

fails=0

# Helper: build a minimal transcript line for a Skill tool_use.
mk_skill_line() {  # skill_name -> jsonl line
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"%s"}}]}}\n' "$1"
}

# Helper: build a Bash tool_use line (for push.sh detection).
mk_bash_line() {  # command -> jsonl line
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"%s"}}]}}\n' "$1"
}

# Build a transcript file containing given lines.
mk_transcript() {  # lines... -> path written to stdout
  local out="$TMP/t_$RANDOM.jsonl"
  : > "$out"
  for line in "$@"; do
    printf '%s\n' "$line" >> "$out"
  done
  printf '%s' "$out"
}

# Build a PreToolUse Bash payload.
payload() {  # command [transcript_path] [cwd_override]
  local cmd="$1" tp="${2:-}" cwd_dir="${3:-$REPO}"
  printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s","transcript_path":"%s"}' \
    "$cmd" "$cwd_dir" "$tp"
}

# Run the hook, return DENY or ALLOW.
run() {
  local out
  out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision"[[:space:]]*:[[:space:]]*"deny"'; then
    echo DENY
  else
    echo ALLOW
  fi
}

check() {  # desc expected actual
  if [ "$2" = "$3" ]; then
    printf 'ok   - %s\n' "$1"
  else
    printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"
    fails=$((fails + 1))
  fi
}

# ── Case 1: no transcript_path / file missing → ALLOW ────────────────────────
check "no transcript -> allow" ALLOW \
  "$(run "$(payload "gh pr create --title foo")")"

check "missing transcript file -> allow" ALLOW \
  "$(run "$(payload "gh pr create --title foo" "$TMP/nope.jsonl")")"

# ── Case 2: gh pr create, no push step in transcript → DENY ──────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "gh pr create, no push step -> deny" DENY \
  "$(run "$(payload "gh pr create --title foo" "$T")")"

# ── Case 3: gh pr create, push Skill in transcript → ALLOW ───────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "gh pr create, coderails:push skill present -> allow" ALLOW \
  "$(run "$(payload "gh pr create --title foo" "$T")")"

# Also accept the bare skill name form.
T=$(mk_transcript "$(mk_skill_line "push")")
check "gh pr create, bare push skill present -> allow" ALLOW \
  "$(run "$(payload "gh pr create --title foo" "$T")")"

# Also accept a Bash tool_use running push.sh.
T=$(mk_transcript "$(mk_bash_line "bash scripts\/push.sh main")")
check "gh pr create, push.sh Bash present -> allow" ALLOW \
  "$(run "$(payload "gh pr create --title foo" "$T")")"

# ── Case 4: gh pr merge, no review-pr in transcript → DENY ───────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "gh pr merge, no review-pr -> deny" DENY \
  "$(run "$(payload "gh pr merge 42 --squash" "$T")")"

# ── Case 5: gh pr merge 42, review-pr Skill with matching args → ALLOW ────────
# CHANGE B: per-PR check — review-pr must reference the same PR number.
# mk_skill_line_with_args is defined later; duplicate the inline form here so
# the test file remains self-contained (helpers are defined before they're used).
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"pr-review-toolkit:review-pr","args":"42"}}]}}\n')")
check "gh pr merge 42, review-pr with matching args -> allow" ALLOW \
  "$(run "$(payload "gh pr merge 42 --squash" "$T")")"

# ── Case 6: non-matching gh pr subcommand → ALLOW ────────────────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "gh pr view -> allow" ALLOW \
  "$(run "$(payload "gh pr view 5" "$T")")"

check "gh pr list -> allow" ALLOW \
  "$(run "$(payload "gh pr list" "$T")")"

check "gh pr status -> allow" ALLOW \
  "$(run "$(payload "gh pr status" "$T")")"

# ── Case 7: no workflow.config.yaml (NO_CONFIG) → ALLOW ──────────────────────
# REPO_NO_CONFIG has no .claude/workflow.config.yaml — hook should be a no-op.
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "no workflow.config.yaml -> allow" ALLOW \
  "$(run "$(payload "gh pr create --title foo" "$T" "$REPO_NO_CONFIG")")"

# ── Case 8: --help / --dry-run passthrough → ALLOW ───────────────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "gh pr create --help -> allow" ALLOW \
  "$(run "$(payload "gh pr create --help" "$T")")"

check "gh pr merge --dry-run -> allow" ALLOW \
  "$(run "$(payload "gh pr merge 1 --dry-run" "$T")")"

# ── Case 9: git merge on main WITH review-pr evidence → ALLOW ────────────────
# Set up a repo on main branch.
REPO_MAIN="$TMP/repo_main"
git -C "$TMP" init -q repo_main
git -C "$REPO_MAIN" config user.email t@t.t
git -C "$REPO_MAIN" config user.name t
git -C "$REPO_MAIN" commit -q --allow-empty -m init
# Rename default branch to main (in case git defaulted to master).
current_branch=$(git -C "$REPO_MAIN" branch --show-current)
[ "$current_branch" != "main" ] && git -C "$REPO_MAIN" branch -m "$current_branch" main
mkdir -p "$REPO_MAIN/.claude"
printf 'jira: null\n' > "$REPO_MAIN/.claude/workflow.config.yaml"

T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "git merge feature on main WITH review-pr evidence -> allow" ALLOW \
  "$(run "$(payload "git merge feature-branch" "$T" "$REPO_MAIN")")"

# ── Case 10: git merge on main WITHOUT review-pr evidence → DENY ─────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git merge feature on main WITHOUT review-pr evidence -> deny" DENY \
  "$(run "$(payload "git merge feature-branch" "$T" "$REPO_MAIN")")"

# ── Case 11: git merge on a FEATURE branch → ALLOW regardless of evidence ────
REPO_FEAT="$TMP/repo_feat"
git -C "$TMP" init -q repo_feat
git -C "$REPO_FEAT" config user.email t@t.t
git -C "$REPO_FEAT" config user.name t
git -C "$REPO_FEAT" commit -q --allow-empty -m init
git -C "$REPO_FEAT" checkout -q -b feature/my-thing
mkdir -p "$REPO_FEAT/.claude"
printf 'jira: null\n' > "$REPO_FEAT/.claude/workflow.config.yaml"

T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git merge on feature branch -> allow regardless of evidence" ALLOW \
  "$(run "$(payload "git merge main" "$T" "$REPO_FEAT")")"

# ── Case 12: git merge --abort on main WITHOUT evidence → ALLOW (exemption) ──
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "git merge --abort on main without evidence -> allow" ALLOW \
  "$(run "$(payload "git merge --abort" "$T" "$REPO_MAIN")")"

# ── Case 13: git merge on master WITHOUT review-pr evidence → DENY ───────────
# Exercises the master arm — mirrors Case 10 but uses a repo whose default
# branch is named master rather than main.
REPO_MASTER="$TMP/repo_master"
git -C "$TMP" init -q repo_master
git -C "$REPO_MASTER" config user.email t@t.t
git -C "$REPO_MASTER" config user.name t
git -C "$REPO_MASTER" commit -q --allow-empty -m init
# Rename to master (init may have created main or master depending on git config).
current_branch=$(git -C "$REPO_MASTER" branch --show-current)
[ "$current_branch" != "master" ] && git -C "$REPO_MASTER" branch -m "$current_branch" master
mkdir -p "$REPO_MASTER/.claude"
printf 'jira: null\n' > "$REPO_MASTER/.claude/workflow.config.yaml"

T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git merge on master WITHOUT review-pr evidence -> deny" DENY \
  "$(run "$(payload "git merge topic" "$T" "$REPO_MASTER")")"

# ── Case 14: git merge-base (read-only plumbing) → ALLOW always ──────────────
# merge-base is a read-only ancestry query, never a branch integration command.
# The gate regex must NOT match it. Test on REPO_MAIN (config present, on main,
# no review-pr evidence) — the harshest context; should still allow.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git merge-base HEAD main on main without evidence -> allow" ALLOW \
  "$(run "$(payload "git merge-base HEAD main" "$T" "$REPO_MAIN")")"

# ── Case 15: git push on main WITHOUT review-pr evidence → DENY ──────────────
# A direct push to main bypasses the PR flow; gate it like git merge on main.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push on main WITHOUT review-pr evidence -> deny" DENY \
  "$(run "$(payload "git push origin main" "$T" "$REPO_MAIN")")"

# ── Case 16: git push on main WITH review-pr evidence → ALLOW ────────────────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "git push on main WITH review-pr evidence -> allow" ALLOW \
  "$(run "$(payload "git push origin main" "$T" "$REPO_MAIN")")"

# ── Case 17: git push on a FEATURE branch → ALLOW regardless of evidence ─────
# The PR flow REQUIRES pushing feature branches; this gate must never touch them.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push on feature branch -> allow regardless of evidence" ALLOW \
  "$(run "$(payload "git push origin feature-x" "$T" "$REPO_FEAT")")"

# ── Case 18: git push on master WITHOUT review-pr evidence → DENY ────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push on master WITHOUT review-pr evidence -> deny" DENY \
  "$(run "$(payload "git push origin master" "$T" "$REPO_MASTER")")"

# ── Case 19: git push --dry-run on main → ALLOW (gate_safe_passthrough) ──────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push --dry-run on main -> allow" ALLOW \
  "$(run "$(payload "git push --dry-run origin main" "$T" "$REPO_MAIN")")"

# ── Case 20: refspec push to main FROM A FEATURE BRANCH, no evidence → DENY ──
# gate_targets_main: keys off DESTINATION, not the checked-out branch: a
# `HEAD:main` refspec writes to remote main even while on a feature branch.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push HEAD:main from feature branch WITHOUT evidence -> deny" DENY \
  "$(run "$(payload "git push origin HEAD:main" "$T" "$REPO_FEAT")")"

# ── Case 21: same refspec push to main, WITH review-pr evidence → ALLOW ──────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "git push HEAD:main from feature branch WITH evidence -> allow" ALLOW \
  "$(run "$(payload "git push origin HEAD:main" "$T" "$REPO_FEAT")")"

# ── Case 22: refspec push to master (feature:master) from feature → DENY ─────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push feature:master from feature branch WITHOUT evidence -> deny" DENY \
  "$(run "$(payload "git push origin feature:master" "$T" "$REPO_FEAT")")"

# ── Case 23: refspec push to a NON-default branch from feature → ALLOW ───────
# The destination check must not over-match: HEAD:my-feature is not main/master.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push HEAD:my-feature from feature branch -> allow" ALLOW \
  "$(run "$(payload "git push origin HEAD:my-feature" "$T" "$REPO_FEAT")")"

# ── Case 24: bare `git push` on main, no evidence → DENY (locks the |$ anchor)
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "bare git push on main WITHOUT evidence -> deny" DENY \
  "$(run "$(payload "git push" "$T" "$REPO_MAIN")")"

# ── Case 25: refspec to main abutted by a shell metachar (no space) → DENY ──
# `HEAD:main;echo` / `HEAD:main&&x` must still gate — the destination anchor must
# accept shell separators, not only whitespace/EOL, or the gate is trivially evaded.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push HEAD:main;echo from feature WITHOUT evidence -> deny" DENY \
  "$(run "$(payload "git push origin HEAD:main;echo hi" "$T" "$REPO_FEAT")")"

check "git push HEAD:main&&x from feature WITHOUT evidence -> deny" DENY \
  "$(run "$(payload "git push origin HEAD:main&&echo hi" "$T" "$REPO_FEAT")")"

# ── Case 26: metachar must not cause over-match on a non-default destination ──
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push HEAD:maintenance;echo from feature -> allow" ALLOW \
  "$(run "$(payload "git push origin HEAD:maintenance;echo hi" "$T" "$REPO_FEAT")")"

# ── Case 27: a command that only MENTIONS a gated command in a string → ALLOW ─
# `printf 'gh pr create' > f` writes text; it does not RUN gh pr create. The scope
# match must key off the command being run, not a substring, or it false-blocks.
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "printf mentioning gh pr create -> allow" ALLOW \
  "$(run "$(payload "printf 'gh pr create' > /tmp/x" "$T")")"

# ── Case 28: prose mentioning a gated command (echo) → ALLOW ─────────────────
check "echo mentioning gh pr create -> allow" ALLOW \
  "$(run "$(payload "echo remember to gh pr create later" "$T")")"

# ── Case 29: a gated command CHAINED after another still gates → DENY ────────
# The fix must not over-correct into a false negative: `cd x && gh pr create` is
# really running gh pr create and must remain gated.
check "cd dir && gh pr create (no evidence) -> deny" DENY \
  "$(run "$(payload "cd sub && gh pr create --title foo" "$T")")"

# ── Case 30: git push chained after cd, on main, no evidence → DENY ──────────
check "cd dir && git push on main (no evidence) -> deny" DENY \
  "$(run "$(payload "cd sub && git push" "$T" "$REPO_MAIN")")"


# ────────────────────────────────────────────────────────────────────────────
# CHANGE A: subagent transcript — scan agent_transcript_path when present
# ────────────────────────────────────────────────────────────────────────────

# Helper: build a PreToolUse payload with both transcript paths.
# parent_transcript_path is a real file (has no evidence); agent_transcript_path
# is the subagent's own transcript.
payload_both_transcripts() {  # command parent_transcript agent_transcript cwd_override
  local cmd="$1" ptp="$2" atp="$3" cwd_dir="${4:-$REPO}"
  printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s","transcript_path":"%s","agent_transcript_path":"%s"}' \
    "$cmd" "$cwd_dir" "$ptp" "$atp"
}

# Parent transcript with NO push evidence (only prep step).
PARENT_NO_EVIDENCE=$(mk_transcript "$(mk_skill_line "coderails:prep")")

# ── Case 31: subagent: push.sh evidence ONLY in agent_transcript_path → ALLOW
# transcript_path (parent) has no push evidence; agent_transcript_path does.
# Currently FALSE-BLOCKS because only transcript_path is scanned.
SUBAGENT_T=$(mk_transcript "$(mk_bash_line "bash scripts\/push.sh main")")
check "subagent: push.sh only in agent_transcript_path -> allow" ALLOW \
  "$(run "$(payload_both_transcripts "gh pr create --title foo" "$PARENT_NO_EVIDENCE" "$SUBAGENT_T")")"

# ── Case 32: subagent: evidence only in PARENT transcript_path → ALLOW ────────
# Push evidence is in parent transcript; agent transcript has none. Should allow.
PARENT_PUSH=$(mk_transcript "$(mk_bash_line "bash scripts\/push.sh main")")
AGENT_NO_EVIDENCE=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "subagent: push.sh only in parent transcript_path -> allow" ALLOW \
  "$(run "$(payload_both_transcripts "gh pr create --title foo" "$PARENT_PUSH" "$AGENT_NO_EVIDENCE")")"

# ── Case 33: subagent: review-pr only in agent_transcript → ALLOW (gh pr merge)
# transcript_path (parent) has no review-pr; agent_transcript_path does.
SUBAGENT_REVIEW=$(mk_transcript "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "subagent: review-pr only in agent_transcript_path -> allow (gh pr merge)" ALLOW \
  "$(run "$(payload_both_transcripts "gh pr merge --squash" "$PARENT_NO_EVIDENCE" "$SUBAGENT_REVIEW")")"

# ── Case 34: subagent: no evidence in either transcript → DENY ───────────────
AGENT_NO_EVIDENCE2=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "subagent: no evidence in either transcript -> deny (gh pr create)" DENY \
  "$(run "$(payload_both_transcripts "gh pr create --title foo" "$PARENT_NO_EVIDENCE" "$AGENT_NO_EVIDENCE2")")"

# ────────────────────────────────────────────────────────────────────────────
# CHANGE B: per-PR consume-on-use review
# ────────────────────────────────────────────────────────────────────────────

# Helper: build a Skill line with args (for review-pr with PR number).
mk_skill_line_with_args() {  # skill_name args -> jsonl line
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"%s","args":"%s"}}]}}\n' "$1" "$2"
}

# Helper: build a Bash tool_use that represents a past git merge (for consume-on-use).
mk_bash_git_merge_line() {  # command -> jsonl line
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"%s"}}]}}\n' "$1"
}

# ── Case 35: gh pr merge 42, review-pr with args "42" → ALLOW ────────────────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "42")")
check "gh pr merge 42, review-pr with args 42 -> allow" ALLOW \
  "$(run "$(payload "gh pr merge 42 --squash" "$T")")"

# ── Case 36: gh pr merge 42, review-pr with args "43" (wrong PR) → DENY ─────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "43")")
check "gh pr merge 42, review-pr for PR 43 (wrong PR) -> deny" DENY \
  "$(run "$(payload "gh pr merge 42 --squash" "$T")")"

# ── Case 37: gh pr merge 42, review-pr with no args (legacy, no PR ref) → DENY
# A plain /review-pr with no PR number does NOT satisfy per-PR requirement.
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "gh pr merge 42, review-pr with no args -> deny" DENY \
  "$(run "$(payload "gh pr merge 42 --squash" "$T")")"

# ── Case 38: git merge on main, review-pr ran after last git merge → ALLOW ───
# consume-on-use: review-pr must appear AFTER the last git merge in the transcript.
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_bash_git_merge_line "git merge old-feature")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "git merge on main, review-pr after last git merge -> allow" ALLOW \
  "$(run "$(payload "git merge new-feature" "$T" "$REPO_MAIN")")"

# ── Case 39: git merge on main, review-pr BEFORE last git merge → DENY ───────
# review-pr ran, then git merge ran — the review is "consumed"; a fresh review needed.
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")" \
  "$(mk_bash_git_merge_line "git merge old-feature")")
check "git merge on main, review-pr before last git merge (consumed) -> deny" DENY \
  "$(run "$(payload "git merge new-feature" "$T" "$REPO_MAIN")")"

# ── Case 40: gh pr merge without number (bare) — no number, review-pr no args → ALLOW
# When gh pr merge is called without an explicit PR number, old behaviour (any review-pr) applies.
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "gh pr merge (bare, no number), review-pr no args -> allow" ALLOW \
  "$(run "$(payload "gh pr merge --squash" "$T")")"

# ────────────────────────────────────────────────────────────────────────────
# CHANGE C: positional `git push origin main` from off-main branch
# ────────────────────────────────────────────────────────────────────────────

# ── Case 41: git push origin main from FEATURE branch, no evidence → DENY ───
# `git push origin main` is positional (no colon refspec) but targets main.
# gate_targets_main must parse positional args when not on main.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin main from feature branch, no evidence -> deny" DENY \
  "$(run "$(payload "git push origin main" "$T" "$REPO_FEAT")")"

# ── Case 42: git push origin main from FEATURE branch, with evidence → ALLOW ─
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "git push origin main from feature branch, with evidence -> allow" ALLOW \
  "$(run "$(payload "git push origin main" "$T" "$REPO_FEAT")")"

# ── Case 43: git push origin master from FEATURE branch, no evidence → DENY ──
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin master from feature branch, no evidence -> deny" DENY \
  "$(run "$(payload "git push origin master" "$T" "$REPO_FEAT")")"

# ── Case 44: git push origin feature-x (non-main) from main → ALLOW ──────────
# Positional push to a non-main branch target must NOT be gated.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin feature-x from feature branch -> allow" ALLOW \
  "$(run "$(payload "git push origin feature-x" "$T" "$REPO_FEAT")")"

# ── Case 45: git push someremote main from feature branch, no evidence → DENY
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push someremote main from feature branch, no evidence -> deny" DENY \
  "$(run "$(payload "git push someremote main" "$T" "$REPO_FEAT")")"

# ────────────────────────────────────────────────────────────────────────────
# CHANGE D: flag boundary tightening — --dry-run / --help as word boundaries
# ────────────────────────────────────────────────────────────────────────────

# ── Case 46: command with --dry-run-data (not --dry-run flag) → DENY ─────────
# A flag named "--dry-run-data" is NOT --dry-run; current loose match would ALLOW.
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "gh pr merge 1 --dry-run-data (not --dry-run flag) -> deny" DENY \
  "$(run "$(payload "gh pr merge 1 --dry-run-data" "$T")")"

# ── Case 47: command with --helpfulness (not --help flag) → DENY ─────────────
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "gh pr create --helpfulness (not --help flag) -> deny" DENY \
  "$(run "$(payload "gh pr create --helpfulness" "$T")")"

# ── Case 48: actual --dry-run flag still passes through → ALLOW ──────────────
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "gh pr merge 1 --dry-run (actual flag) -> allow" ALLOW \
  "$(run "$(payload "gh pr merge 1 --dry-run" "$T")")"

# ── Case 49: actual --help flag still passes through → ALLOW ─────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:prep")")
check "gh pr create --help (actual flag) -> allow" ALLOW \
  "$(run "$(payload "gh pr create --help" "$T")")"


# ────────────────────────────────────────────────────────────────────────────
# FINDING C1: push-to-main misses flag/refspec/extra-positional forms
# ────────────────────────────────────────────────────────────────────────────

# ── Case 50: git push -u origin main → DENY ──────────────────────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push -u origin main, no evidence -> deny" DENY \
  "$(run "$(payload "git push -u origin main" "$T" "$REPO_FEAT")")"

# ── Case 51: git push --set-upstream origin main → DENY ─────────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push --set-upstream origin main, no evidence -> deny" DENY \
  "$(run "$(payload "git push --set-upstream origin main" "$T" "$REPO_FEAT")")"

# ── Case 52: git push -f origin main → DENY ──────────────────────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push -f origin main, no evidence -> deny" DENY \
  "$(run "$(payload "git push -f origin main" "$T" "$REPO_FEAT")")"

# ── Case 53: git push --force origin main → DENY ─────────────────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push --force origin main, no evidence -> deny" DENY \
  "$(run "$(payload "git push --force origin main" "$T" "$REPO_FEAT")")"

# ── Case 54: git push origin +main (force-refspec, no colon) → DENY ──────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin +main (force-refspec), no evidence -> deny" DENY \
  "$(run "$(payload "git push origin +main" "$T" "$REPO_FEAT")")"

# ── Case 55: git push origin refs/heads/main (bare ref) → DENY ───────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin refs/heads/main, no evidence -> deny" DENY \
  "$(run "$(payload "git push origin refs/heads/main" "$T" "$REPO_FEAT")")"

# ── Case 56: git push origin tag v1 main (extra positional) → DENY ───────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin tag v1 main (extra positional), no evidence -> deny" DENY \
  "$(run "$(payload "git push origin tag v1 main" "$T" "$REPO_FEAT")")"

# ── Case 57: over-match guard: git push origin main-fix → ALLOW ──────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin main-fix -> allow (over-match guard)" ALLOW \
  "$(run "$(payload "git push origin main-fix" "$T" "$REPO_FEAT")")"

# ── Case 58: over-match guard: git push origin maintenance → ALLOW ───────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin maintenance -> allow (over-match guard)" ALLOW \
  "$(run "$(payload "git push origin maintenance" "$T" "$REPO_FEAT")")"

# ── Case 59: over-match guard: git push origin feature → ALLOW ───────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin feature -> allow (over-match guard)" ALLOW \
  "$(run "$(payload "git push origin feature" "$T" "$REPO_FEAT")")"

# ── Case 60: git push +master (force-refspec master) → DENY ──────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin +master (force-refspec), no evidence -> deny" DENY \
  "$(run "$(payload "git push origin +master" "$T" "$REPO_FEAT")")"

# ── Case 61: git push refs/heads/master → DENY ───────────────────────────────
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push origin refs/heads/master, no evidence -> deny" DENY \
  "$(run "$(payload "git push origin refs/heads/master" "$T" "$REPO_FEAT")")"

# ────────────────────────────────────────────────────────────────────────────
# FINDING B1: PR number extraction skips flags before the number
# ────────────────────────────────────────────────────────────────────────────

# ── Case 62: gh pr merge --squash 42, review-pr for 42 → ALLOW ───────────────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "42")")
check "gh pr merge --squash 42, review-pr for 42 -> allow" ALLOW \
  "$(run "$(payload "gh pr merge --squash 42" "$T")")"

# ── Case 63: gh pr merge --squash 42, review-pr for 99 only → DENY ───────────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "99")")
check "gh pr merge --squash 42, review-pr for 99 only -> deny" DENY \
  "$(run "$(payload "gh pr merge --squash 42" "$T")")"

# ── Case 64: gh pr merge --auto 42, review-pr for 42 → ALLOW ─────────────────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "42")")
check "gh pr merge --auto 42, review-pr for 42 -> allow" ALLOW \
  "$(run "$(payload "gh pr merge --auto 42" "$T")")"

# ── Case 65: gh pr merge --squash --merge 42, review-pr for 42 → ALLOW ───────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "42")")
check "gh pr merge --squash --merge 42, review-pr for 42 -> allow" ALLOW \
  "$(run "$(payload "gh pr merge --squash --merge 42" "$T")")"

# ────────────────────────────────────────────────────────────────────────────
# FINDING B2: Per-PR match must not match incidental number in args
# ────────────────────────────────────────────────────────────────────────────

# ── Case 66: gh pr merge 12, review-pr args "fixed 12 bugs" → DENY ───────────
# "12" is an incidental word in a sentence, not the PR number argument.
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "fixed 12 bugs")")
check "gh pr merge 12, review-pr args 'fixed 12 bugs' (incidental) -> deny" DENY \
  "$(run "$(payload "gh pr merge 12" "$T")")"

# ── Case 67: gh pr merge 12, review-pr args "12" (leading token) → ALLOW ─────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "12")")
check "gh pr merge 12, review-pr args '12' (leading token) -> allow" ALLOW \
  "$(run "$(payload "gh pr merge 12" "$T")")"

# ── Case 68: gh pr merge 12, review-pr args "12 --squash" → ALLOW ─────────────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "12 --squash")")
check "gh pr merge 12, review-pr args '12 --squash' (leading token) -> allow" ALLOW \
  "$(run "$(payload "gh pr merge 12" "$T")")"

# ── Case 69: boundary: review-pr args "420" must NOT satisfy PR 42 → DENY ────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "420")")
check "gh pr merge 42, review-pr args '420' (boundary check) -> deny" DENY \
  "$(run "$(payload "gh pr merge 42" "$T")")"

# ── Case 70: boundary: review-pr args "142" must NOT satisfy PR 42 → DENY ────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line_with_args "pr-review-toolkit:review-pr" "142")")
check "gh pr merge 42, review-pr args '142' (boundary check) -> deny" DENY \
  "$(run "$(payload "gh pr merge 42" "$T")")"


# ────────────────────────────────────────────────────────────────────────────
# ADDITION: cross-transcript timestamp ordering (B ordering fix)
# ────────────────────────────────────────────────────────────────────────────

# Helper: build a timestamped assistant entry.
# Timestamps are ISO-8601; order matters for the security fix.
mk_bash_line_ts() {  # command timestamp -> jsonl line
  printf '{"type":"assistant","timestamp":"%s","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"%s"}}]}}\n' "$2" "$1"
}
mk_skill_line_ts() {  # skill_name timestamp -> jsonl line
  printf '{"type":"assistant","timestamp":"%s","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"%s"}}]}}\n' "$2" "$1"
}

# ── Case 71: cross-transcript stale review — review-pr timestamp BEFORE git merge → DENY
# Scenario: parent transcript has git merge at T2; agent transcript has review-pr at T1 (T1 < T2).
# By array-concatenation order (parent-first), review-pr lands at a higher index than the merge
# and the old code would ALLOW. With timestamp sorting, review-pr is before the merge → DENY.
PARENT_MERGE=$(mk_transcript \
  "$(mk_bash_line_ts "git merge feature-branch" "2026-01-01T10:00:00Z")")
AGENT_STALE_REVIEW=$(mk_transcript \
  "$(mk_skill_line_ts "pr-review-toolkit:review-pr" "2026-01-01T09:00:00Z")")
check "cross-transcript: review-pr timestamp BEFORE git merge -> deny" DENY \
  "$(run "$(payload_both_transcripts "git merge new-feature" "$PARENT_MERGE" "$AGENT_STALE_REVIEW" "$REPO_MAIN")")"

# ── Case 72: cross-transcript fresh review — review-pr timestamp AFTER git merge → ALLOW
PARENT_MERGE2=$(mk_transcript \
  "$(mk_bash_line_ts "git merge feature-branch" "2026-01-01T10:00:00Z")")
AGENT_FRESH_REVIEW=$(mk_transcript \
  "$(mk_skill_line_ts "pr-review-toolkit:review-pr" "2026-01-01T11:00:00Z")")
check "cross-transcript: review-pr timestamp AFTER git merge -> allow" ALLOW \
  "$(run "$(payload_both_transcripts "git merge new-feature" "$PARENT_MERGE2" "$AGENT_FRESH_REVIEW" "$REPO_MAIN")")"

# ────────────────────────────────────────────────────────────────────────────
# ADDITION: over-match guard for flagged push to non-main branch
# ────────────────────────────────────────────────────────────────────────────

# ── Case 73: git push -u origin feature-x → ALLOW (flagged push, non-main target)
# The C1 token-scan must not gate a flag-bearing push to a non-main destination.
T=$(mk_transcript "$(mk_skill_line "coderails:push")")
check "git push -u origin feature-x -> allow (flagged push, non-main target)" ALLOW \
  "$(run "$(payload "git push -u origin feature-x" "$T" "$REPO_FEAT")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
