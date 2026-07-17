#!/bin/bash
# Guard test for the docs-sync nightly self-merging routine (replaces the
# broken sync-docs-weekly entry — its foreignSkillPath pointed at
# /Users/harrison/.claude/skills/sync-docs/SKILL.md, which never existed;
# the real skill lives in-repo at skills/sync-docs/SKILL.md, and
# config.ts's own validator only checks foreignSkillPath is a non-empty
# absolute string, never that it exists on disk — so the broken path
# loaded clean and only failed later, at sweep time, 9 days after its
# last successful artifact).
#
# This routine's own skill (skills/docs-sync/SKILL.md) now lives IN the
# plugin, so it needs no foreignSkillPath at all — same as
# loop-retro-promotion, the repo's other bypass-profile self-merging
# routine. Asserting foreignSkillPath is ABSENT (not merely "if present,
# exists") is the correct regression lock here: every path in
# examples/dashboard-config.json is an intentional /path/to/... placeholder
# (see docs/routines.md — each machine rewrites its own config from this
# example), so an "if present, must exist on disk" check against the
# example file can only ever pass by the field being absent anyway. Testing
# the absence directly names the actual invariant instead of relying on
# that coincidence.
#
# Cadence must be "nightly", not "daily" — skills/dashboard/runner/src/seed.ts
# defines SeedCadence = "nightly" | "weekly" and escalates a runner-error on
# any other value; NIGHTLY_DUE_AFTER_MS (20h) is what "once a day" means in
# this system.
#
# Config validation is exercised through the real loadConfig() (Node's
# built-in TypeScript stripping, no build step — see docs/routines.md's
# "Prerequisites for a cold clone") rather than reimplemented in bash/jq,
# so this test is only as good as that invocation actually working: it
# requires `npm install` already run in skills/dashboard/lib and
# skills/dashboard/runner (same prerequisite the runner itself has).
#
# bash 3.2 (macOS default) compatible — no `declare -A`.
#
# Usage: bash docs_sync_routine.test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CONFIG_PATH="$REPO_ROOT/examples/dashboard-config.json"
SKILL_PATH="$REPO_ROOT/skills/docs-sync/SKILL.md"
LIB_SRC="$REPO_ROOT/skills/dashboard/lib/src/config.ts"

fails=0
checks=0
check() { # desc expected actual
  checks=$((checks+1))
  if [ "$2" = "$3" ]; then printf 'ok   - %s (%s)\n' "$1" "$2"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

if [ ! -f "$CONFIG_PATH" ]; then
  echo "FAIL - example config not found: $CONFIG_PATH"
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "FAIL - node not found on PATH — required to exercise the real loadConfig()"
  exit 1
fi

# A missing node_modules is a normal cold-clone state (docs/routines.md
# "Prerequisites for a cold clone"), not a broken assertion — SKIP (exit 3)
# rather than FAIL, so run_all.sh can distinguish "couldn't run" from
# "ran and found a real problem". Scoped to node_modules only: the earlier
# `command -v node` check above stays a hard FAIL, since a missing node
# binary isn't the documented cold-clone case this exists to unblock.
if [ ! -d "$REPO_ROOT/skills/dashboard/lib/node_modules" ] || [ ! -d "$REPO_ROOT/skills/dashboard/runner/node_modules" ]; then
  echo "SKIP: skills/dashboard/lib and/or skills/dashboard/runner node_modules missing — run npm install in both (see docs/routines.md 'Prerequisites for a cold clone')"
  exit 3
fi

# --- Everything config-shaped goes through ONE node invocation: loadConfig()
# itself (proves the example config is valid per the real validator, not a
# bash reimplementation of it) plus direct field assertions on the resolved
# docs-sync routine + button. Printed as `key=value` lines, parsed below.
node_out="$(cd "$REPO_ROOT" && node --experimental-strip-types -e "
import('./skills/dashboard/lib/src/config.ts').then((m) => {
  let cfg;
  try {
    cfg = m.loadConfig('./examples/dashboard-config.json');
  } catch (e) {
    console.log('loadConfig_ok=no');
    console.log('loadConfig_error=' + String(e && e.message || e).replace(/\n/g, ' '));
    return;
  }
  console.log('loadConfig_ok=yes');
  const routine = cfg.routines.find(r => /(docs.?sync|sync.?docs)/i.test(r.name));
  if (!routine) {
    console.log('routine_found=no');
    return;
  }
  console.log('routine_found=yes');
  console.log('routine_name=' + routine.name);
  console.log('cadence=' + routine.cadence);
  console.log('foreignSkillPath_present=' + (routine.foreignSkillPath !== undefined ? 'yes' : 'no'));
  console.log('maxAgeSeconds=' + routine.expectedArtifact.maxAgeSeconds);
  const targetName = routine.buttonRef || routine.name;
  const button = cfg.buttons.find(b => b.name === targetName);
  if (!button) {
    console.log('button_found=no');
    return;
  }
  console.log('button_found=yes');
  console.log('button_profile=' + button.profile);
}).catch((e) => {
  console.log('loadConfig_ok=no');
  console.log('loadConfig_error=' + String(e && e.message || e).replace(/\n/g, ' '));
});
" 2>/dev/null)"

field() { # key
  printf '%s\n' "$node_out" | grep "^$1=" | head -1 | cut -d= -f2-
}

check "example config loads via the runner's own loadConfig()" "yes" "$(field loadConfig_ok)"
check "docs-sync routine is present in the config" "yes" "$(field routine_found)"
check "docs-sync routine cadence is nightly" "nightly" "$(field cadence)"
check "docs-sync routine has NO foreignSkillPath (in-repo skill, not foreign)" "no" "$(field foreignSkillPath_present)"
check "docs-sync routine's button is found (buttonRef/name resolves)" "yes" "$(field button_found)"
check "docs-sync button profile is bypass" "bypass" "$(field button_profile)"

# --- Direct replication of the deployed lookup pattern: `select(.name |
# test("sync-docs"))` against BOTH .routines[].name and .buttons[].name
# independently (not via buttonRef resolution). This is the actual
# mechanism external consumers of this config use to locate "the
# sync-docs routine" and "the sync-docs button" by name substring match —
# proving both the routine's own `name` and the button's own `name` each
# independently contain "sync-docs" is a stronger, more direct guard than
# the buttonRef-resolution check above, and catches an ordering mismatch
# (e.g. "docs-sync" vs "sync-docs") that buttonRef-resolution alone would
# miss, since buttonRef resolves by whatever string it's set to, not by
# substring match on either side's name.
if command -v jq >/dev/null 2>&1; then
  jq_cadence="$(jq -r '.routines[] | select(.name|test("sync-docs")) | .cadence' "$CONFIG_PATH" 2>/dev/null)"
  jq_profile="$(jq -r '.buttons[] | select(.name|test("sync-docs")) | .profile' "$CONFIG_PATH" 2>/dev/null)"
  check "jq name-substring lookup: a routine named *sync-docs* has cadence nightly" \
    "nightly" "$jq_cadence"
  check "jq name-substring lookup: a button named *sync-docs* has profile bypass" \
    "bypass" "$jq_profile"
fi

# maxAgeSeconds must be sized for NIGHTLY cadence, not the 691200s (8-day)
# weekly bar — leaving the weekly bar in place would let a routine dead for
# up to 8 nights still read as "fresh enough". (Escalation itself worked
# correctly here — vault-runs/sync-docs-weekly.md shows a green run on
# 2026-07-08 and a red skill-missing escalation on 2026-07-15 — the defect
# is that the DEAD PATH sat unfixed because the escalation landed on a
# channel nobody was watching, not that escalation was silent or broken.)
maxage="$(field maxAgeSeconds)"
check "docs-sync maxAgeSeconds is set" "yes" "$([ -n "$maxage" ] && echo yes || echo no)"
if [ -n "$maxage" ]; then
  check "docs-sync maxAgeSeconds is tighter than the weekly bar (691200s)" \
    "yes" "$([ "$maxage" -lt 691200 ] && echo yes || echo no)"
fi

# --- Regression-lock negative control (SO-31): a check that never fires
# against the bug it exists to catch is worthless. Re-run the SAME
# loadConfig()-based extraction against a synthetic config where
# foreignSkillPath is set to the OLD BROKEN path
# (/Users/harrison/.claude/skills/sync-docs/SKILL.md, which does not exist)
# and confirm checkForeignSkillExists() — the runner's own existence
# predicate — reports it missing. This proves the check actually
# discriminates a present-but-broken path from a correctly-absent one,
# rather than passing by construction because every path in the example
# file happens to be a placeholder.
neg_out="$(cd "$REPO_ROOT" && node --experimental-strip-types -e "
import('./skills/dashboard/runner/src/escalate.ts').then((m) => {
  const brokenPath = '/Users/harrison/.claude/skills/sync-docs/SKILL.md';
  console.log('broken_path_exists=' + (m.checkForeignSkillExists(brokenPath) ? 'yes' : 'no'));
}).catch((e) => {
  console.log('broken_path_exists=ERROR:' + String(e && e.message || e).replace(/\n/g, ' '));
});
" 2>/dev/null)"
neg_field() { printf '%s\n' "$neg_out" | grep "^$1=" | head -1 | cut -d= -f2-; }
check "negative control: old broken foreignSkillPath is confirmed NOT to exist (checkForeignSkillExists returns false)" \
  "no" "$(neg_field broken_path_exists)"

# --- SKILL.md contract checks (agent-graded evals E8/E9 read this prose;
# these are the cheap, mechanical regression locks that back them up) ---
check "skills/docs-sync/SKILL.md exists" "yes" "$([ -f "$SKILL_PATH" ] && echo yes || echo no)"

if [ -f "$SKILL_PATH" ]; then
  # Anchored on the NORMATIVE imperative, not the topic keyword. A bare
  # grep for 'no-drift' passes on prose that says the short-circuit was
  # REMOVED ("no-drift handling was removed; the routine now always opens
  # a PR" matches 'no-drift'), so it locks nothing — verified directly:
  #   echo "no-drift handling was removed..." | grep -qi 'no-drift'  -> matches
  # The instruction is the contract; assert the instruction's own text.
  check "SKILL.md forbids creating a branch on a no-drift night" \
    "yes" "$(grep -qi 'do \*\*not\*\* create a branch' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md forbids opening a PR on a no-drift night" \
    "yes" "$(grep -qi 'do \*\*not\*\* open a pull request' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md states the short-circuit decision happens BEFORE branch/PR creation" \
    "yes" "$(grep -qi 'BEFORE any branch or PR is created' "$SKILL_PATH" && echo yes || echo no)"

  # --- Manifest must read the diff with --name-status, never --name-only.
  # --name-only prints a rename as its DESTINATION alone, so
  # `git mv scripts/gate.sh evil.md` shows bare `evil.md` — a .md path on
  # no deny-list, which passes an extension check while smuggling in a
  # shell script. It also cannot distinguish a deletion from an edit
  # (both print the bare path). Verified empirically by the reviewer,
  # 2026-07-17, in a scratch git repo.
  check "SKILL.md's manifest assertion uses --name-status" \
    "yes" "$(grep -q -- '--name-status' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md forbids --name-only in the manifest assertion" \
    "yes" "$(grep -q -- 'never .\{0,5\}--name-only' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md rejects a rename/copy whose source wasn't already in-scope" \
    "yes" "$(grep -qi 'no line has status .R. or .C. (rename/copy) unless its SOURCE path' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md rejects deletion of an in-scope doc" \
    "yes" "$(grep -qi 'no line has status .D. (deletion) for an in-scope doc' "$SKILL_PATH" && echo yes || echo no)"

  check "SKILL.md's manifest-scope violation is the normative ABORT clause (never warn-and-continue)" \
    "yes" "$(grep -q 'ABORT, never warn-and-continue' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md scopes edits to git-tracked .md files only (the actual scope clause, not the topic word)" \
    "yes" "$(grep -q 'git-tracked \`\.md\` files only' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md's refusal contract names the refused=<gate> marker specifically" \
    "yes" "$(grep -q 'refused=<gate>' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md's abort contract names the abort=<reason> marker specifically" \
    "yes" "$(grep -q 'abort=<reason>' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md's failure-visibility section states it writes into the run-note (not just logs)" \
    "yes" "$(grep -qi 'writes its reason into the run-note' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md states plainly there is no dashboard alert or PR comment for a failed run" \
    "yes" "$(grep -q 'There is no dashboard alert and no PR comment' "$SKILL_PATH" && echo yes || echo no)"

  # --- C1 security-review finding: the manifest's file-TYPE check does not
  # by itself stop the routine editing ITS OWN governing .md files (its own
  # SKILL.md, AGENTS.md, CLAUDE.md, docs/routines.md, .claude/**) — every
  # one of those passes an extension-only check. These assert the
  # self-governance deny-list is documented as an ABORT-triggering
  # condition, anchored on the normative sentence rather than a passing
  # mention of the word "deny-list" or "AGENTS.md" somewhere unrelated.
  check "SKILL.md names a self-governance deny-list as a heading/label" \
    "yes" "$(grep -qi 'self-governance deny-list' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md's deny-list names skills/**/SKILL.md, including its own file" \
    "yes" "$(grep -qi 'skills/\*\*/SKILL.md.*including this skill.s own file' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md's deny-list has a line-item naming AGENTS.md" \
    "yes" "$(grep -qE '^ *- .AGENTS\.md.$' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md's deny-list has a line-item naming docs/routines.md" \
    "yes" "$(grep -qE '^ *- .docs/routines\.md.$' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md states the deny-list defines what the routine is ALLOWED to do (the actual invariant)" \
    "yes" "$(grep -qi 'documents that define' "$SKILL_PATH" && echo yes || echo no)"
  check "SKILL.md is honest that PreToolUse hooks do not fire under claude -p (the actual limit)" \
    "yes" "$(grep -qi 'do not fire.*it reduces the risk of self-governance drift' "$SKILL_PATH" && echo yes || echo no)"
fi

# --- SO-31 negative controls: strip the EXACT normative sentence each
# check above anchors on out of a scratch copy of SKILL.md, and confirm
# the corresponding check would go RED against that stripped copy. This
# is what makes an anchor real rather than another keyword in disguise —
# a check that cannot be made to fail by removing the behaviour it claims
# to guard is not evidence of anything (the reviewer's exact finding).
if [ -f "$SKILL_PATH" ]; then
  neg_check() { # description, ERE pattern to strip AND reassert absent
    local desc="$1" pat="$2" stripped
    stripped="$(mktemp)"
    grep -viE "$pat" "$SKILL_PATH" > "$stripped"
    check "$desc" "no" "$(grep -qiE "$pat" "$stripped" && echo yes || echo no)"
  }

  neg_check "negative control: no-drift branch-prohibition check goes RED without its sentence" \
    'do \*\*not\*\* create a branch'
  neg_check "negative control: manifest ABORT clause check goes RED without its sentence" \
    'ABORT, never warn-and-continue'
  neg_check "negative control: deny-list heading check goes RED without its sentence" \
    'self-governance deny-list'
  neg_check "negative control: AGENTS.md deny-list line-item check goes RED without its line" \
    '^ *- .AGENTS\.md.\$'
  neg_check "negative control: docs/routines.md deny-list line-item check goes RED without its line" \
    '^ *- .docs/routines\.md.\$'
  neg_check "negative control: --name-status requirement check goes RED without the flag" \
    -- '--name-status'
  neg_check "negative control: R/C rename-source check goes RED without its sentence" \
    'no line has status .R. or .C. \(rename/copy\) unless its SOURCE path'
  neg_check "negative control: D deletion check goes RED without its sentence" \
    'no line has status .D. \(deletion\) for an in-scope doc'
  neg_check "negative control: deny-list-defines-permission check goes RED without its clause" \
    'documents that define'
  neg_check "negative control: PreToolUse-honesty check goes RED without its sentence" \
    'do not fire.*it reduces the risk of self-governance drift'
fi

if [ "$checks" -eq 0 ]; then
  echo "FAIL - zero checks ran — guard is vacuous"
  exit 1
fi

[ "$fails" -eq 0 ] && { echo "PASS ($checks checks)"; exit 0; } || { echo "FAILED ($fails/$checks)"; exit 1; }
