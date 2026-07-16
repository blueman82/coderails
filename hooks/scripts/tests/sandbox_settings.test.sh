#!/bin/bash
# Behavioural test for scripts/sandbox/render-settings.sh — the srt settings
# renderer. Runs everywhere (no srt, no sandbox exec): it asserts the RENDERED
# ARTIFACT's shape, not the sandbox's runtime behaviour, which the live probe
# and Task 3/4's tests cover on supported platforms only.
#
# The five-required-keys assertions are the load-bearing ones. srt 0.0.65
# validates settings with a zod schema (dist/sandbox/sandbox-config.js) in which
# network.allowedDomains, network.deniedDomains, filesystem.denyRead,
# filesystem.allowWrite and filesystem.denyWrite are all NON-optional. Omit any
# one and loadConfig() returns null, so `srt --settings <path>` exits 1 with
# "Refusing to run with the default config" — the config never boots. An
# earlier draft of this template omitted deniedDomains and could not boot.
# These `has()` checks are the regression guard for exactly that omission.
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RENDER="$REPO_ROOT/scripts/sandbox/render-settings.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── Fixtures ───────────────────────────────────────────────────────────────
# Three real, absolute, existing dirs — the renderer fail-fasts on anything else.
WORKTREE="$TMP/wt"; SCRATCH="$TMP/scratch"; PRIMARY_GIT="$TMP/primary/.git"
mkdir -p "$WORKTREE" "$SCRATCH" "$PRIMARY_GIT"
OUT="$TMP/rendered.json"

# ─── Happy path ─────────────────────────────────────────────────────────────
render_rc=0
"$RENDER" "$WORKTREE" "$SCRATCH" "$PRIMARY_GIT" "$OUT" >"$TMP/render.log" 2>&1 || render_rc=$?
check "renderer exits 0 on three valid dirs" "0" "$render_rc"

if [ ! -s "$OUT" ]; then
  printf 'FAIL - renderer produced no output at %s; log:\n' "$OUT"; cat "$TMP/render.log"
  echo "FAILED ($((fails+1)))"; exit 1
fi

jq_rc=0; jq . "$OUT" >/dev/null 2>&1 || jq_rc=$?
check "rendered settings are valid JSON (jq parses)" "0" "$jq_rc"

# ─── The five keys srt's zod schema requires ────────────────────────────────
# Asserted individually so a failure names the missing key.
for key in '.network.allowedDomains' '.network.deniedDomains' \
           '.filesystem.denyRead' '.filesystem.allowWrite' '.filesystem.denyWrite'; do
  parent="${key%.*}"; leaf="${key##*.}"
  check "required key $key present and is an array" "true" \
    "$(jq -r --arg k "$leaf" "($parent | has(\$k)) and (${key} | type == \"array\")" "$OUT" 2>/dev/null)"
done

# ─── Substitution ───────────────────────────────────────────────────────────
check "worktree path substituted into allowWrite" "true" \
  "$(jq --arg p "$WORKTREE" '.filesystem.allowWrite | index($p) != null' "$OUT")"
check "scratch path substituted into allowWrite" "true" \
  "$(jq --arg p "$SCRATCH" '.filesystem.allowWrite | index($p) != null' "$OUT")"
check "primary .git path substituted into allowWrite" "true" \
  "$(jq --arg p "$PRIMARY_GIT" '.filesystem.allowWrite | index($p) != null' "$OUT")"

# No placeholder may survive, anywhere in the file.
check "no %% placeholder remains" "0" "$(grep -c '%%' "$OUT" || true)"
# ~ must be expanded by the renderer, not left for srt/the shell to guess.
check "no bare ~ path remains" "0" \
  "$(jq -r '[.filesystem[] | select(type == "array") | .[] | select(type == "string") | select(startswith("~"))] | length' "$OUT")"
# Comments must not reach the rendered file: srt parses with JSON.parse, which
# rejects them outright (the justifications live in the .template, stripped here).
check "no // comment survives into rendered JSON" "0" "$(grep -c '^[[:space:]]*//' "$OUT" || true)"

# ─── Allowlist content ──────────────────────────────────────────────────────
check "network allowlist carries api.anthropic.com" "true" \
  "$(jq '.network.allowedDomains | index("api.anthropic.com") != null' "$OUT")"
check "network allowlist carries github.com" "true" \
  "$(jq '.network.allowedDomains | index("github.com") != null' "$OUT")"
# The claude-home settings carve-out: denyWrite takes precedence over allowWrite,
# so these two OS-deny the one file class whose edit dismantles the hook layer.
check "denyWrite carves out ~/.claude/settings.json" "true" \
  "$(jq --arg p "$HOME/.claude/settings.json" '.filesystem.denyWrite | index($p) != null' "$OUT")"
check "denyWrite carves out ~/.claude/settings.local.json" "true" \
  "$(jq --arg p "$HOME/.claude/settings.local.json" '.filesystem.denyWrite | index($p) != null' "$OUT")"
# allowGitConfig must stay unset/false: srt's macos-sandbox-utils.js only pushes
# the .git/config deny path `if (!allowGitConfig)`. Setting it true would trade
# away the free hardening the spec relies on to make `git push -u` fail loudly.
check "allowGitConfig is not enabled" "true" \
  "$(jq '(.filesystem | has("allowGitConfig") | not) or (.filesystem.allowGitConfig == false)' "$OUT")"

# ─── Fail-fast preconditions ────────────────────────────────────────────────
rc=0; "$RENDER" "$WORKTREE" "$SCRATCH" >/dev/null 2>&1 || rc=$?
check "missing args → non-zero" "1" "$([ "$rc" -ne 0 ] && echo 1 || echo 0)"

rc=0; err=$("$RENDER" "$TMP/nonexistent" "$SCRATCH" "$PRIMARY_GIT" "$OUT.2" 2>&1) || rc=$?
check "nonexistent worktree → non-zero" "1" "$([ "$rc" -ne 0 ] && echo 1 || echo 0)"
check "nonexistent worktree → error names the path" "1" \
  "$(printf '%s' "$err" | grep -qF "$TMP/nonexistent" && echo 1 || echo 0)"

rc=0; err=$("$RENDER" "relative/path" "$SCRATCH" "$PRIMARY_GIT" "$OUT.3" 2>&1) || rc=$?
check "relative path → non-zero" "1" "$([ "$rc" -ne 0 ] && echo 1 || echo 0)"
check "relative path → error says absolute" "1" \
  "$(printf '%s' "$err" | grep -qi 'absolute' && echo 1 || echo 0)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
