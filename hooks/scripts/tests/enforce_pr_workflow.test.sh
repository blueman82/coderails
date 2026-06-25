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

# ── Case 5: gh pr merge, review-pr Skill in transcript → ALLOW ───────────────
T=$(mk_transcript \
  "$(mk_skill_line "coderails:push")" \
  "$(mk_skill_line "pr-review-toolkit:review-pr")")
check "gh pr merge, review-pr skill present -> allow" ALLOW \
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

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
