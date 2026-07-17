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

# Claude Code's per-project state dir (/tmp/claude-<uid>/<slug-of-worktree>) must
# be granted or a sandboxed worker writes one file then EPERMs on mkdir at its
# next tool call — the E2 end-to-end probe failed exactly this way, while every
# component test passed. The slug is the worktree path with / replaced by -.
CLAUDE_STATE="/private/tmp/claude-$(id -u)/$(printf '%s' "$WORKTREE" | sed 's|/|-|g')"
check "claude project-state dir substituted into allowWrite" "true" \
  "$(jq --arg p "$CLAUDE_STATE" '.filesystem.allowWrite | index($p) != null' "$OUT")"
# ...and ONLY this worker's own slug. Granting the whole /tmp/claude-<uid> tree
# would hand every worker write access over every other project's session state.
check "claude state grant is the slug subdir, NOT the whole tree" "true" \
  "$(jq --arg root "/private/tmp/claude-$(id -u)" '.filesystem.allowWrite | index($root) == null' "$OUT")"

# Paths are DATA, not syntax. The renderer substitutes with jq (not sed) because
# every sed delimiter is a legal filename character and sed cannot JSON-escape.
# Two regressions, both reproduced against the old sed implementation:
#   `|` -> sed died "bad flag in substitute command", no settings file written.
#   `"` -> sed spliced it in raw, producing structurally-invalid JSON (caught
#          only by the downstream jq gate, and an injection risk in principle).
PIPE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/settings-pipe.XXXXXX")
mkdir -p "$PIPE_ROOT/pipe|dir"
git init -q "$PIPE_ROOT/pipe|dir/wt"
PIPE_GIT=$(git -C "$PIPE_ROOT/pipe|dir/wt" rev-parse --path-format=absolute --git-common-dir)
mkdir -p "$PIPE_ROOT/scratch"
PIPE_OUT="$PIPE_ROOT/rendered.json"
"$RENDER" "$PIPE_ROOT/pipe|dir/wt" "$PIPE_ROOT/scratch" "$PIPE_GIT" "$PIPE_OUT" >/dev/null 2>&1
check "path containing | renders (sed delimiter regression)" "true" \
  "$(jq -e . "$PIPE_OUT" >/dev/null 2>&1 && echo true || echo false)"
check "path containing | is substituted literally" "true" \
  "$(jq --arg p "$PIPE_ROOT/pipe|dir/wt" '.filesystem.allowWrite | index($p) != null' "$PIPE_OUT" 2>/dev/null)"

QUOTE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/settings-quote.XXXXXX")
mkdir -p "$QUOTE_ROOT/qu\"ote"
git init -q "$QUOTE_ROOT/qu\"ote/wt"
QUOTE_GIT=$(git -C "$QUOTE_ROOT/qu\"ote/wt" rev-parse --path-format=absolute --git-common-dir)
mkdir -p "$QUOTE_ROOT/scratch"
QUOTE_OUT="$QUOTE_ROOT/rendered.json"
"$RENDER" "$QUOTE_ROOT/qu\"ote/wt" "$QUOTE_ROOT/scratch" "$QUOTE_GIT" "$QUOTE_OUT" >/dev/null 2>&1
check "path containing a quote renders valid JSON (escaping regression)" "true" \
  "$(jq -e . "$QUOTE_OUT" >/dev/null 2>&1 && echo true || echo false)"
# The quote must be ESCAPED into one entry, never splice a second one in.
check "quoted path does not inject an extra allowWrite entry" "7" \
  "$(jq '.filesystem.allowWrite | length' "$QUOTE_OUT" 2>/dev/null)"

# No placeholder may survive, anywhere in the file.
check "no %% placeholder remains" "0" "$(grep -c '%%' "$OUT" || true)"
# ~ must be expanded by the renderer, not left for srt/the shell to guess.
check "no bare ~ path remains" "0" \
  "$(jq -r '[.filesystem[] | select(type == "array") | .[] | select(type == "string") | select(startswith("~"))] | length' "$OUT")"
# Comments must not reach the rendered file: srt parses with JSON.parse, which
# rejects them outright (the justifications live in the .template, stripped here).
check "no // comment survives into rendered JSON" "0" "$(grep -c '^[[:space:]]*//' "$OUT" || true)"

# ─── Allowlist content ──────────────────────────────────────────────────────
# ~/.cache is deliberately ABSENT from allowWrite: claude -p's cache need is
# met instead by the spawn script redirecting XDG_CACHE_HOME to a subdir of
# %%SCRATCH%% (already allowlisted below), which is narrower than granting
# ~/.cache (shared with gh/uv/huggingface). Verified live, srt 0.0.65 — see
# spawn_sandboxed_worker.test.sh for the behavioural guard on that env var.
check "network allowlist carries api.anthropic.com" "true" \
  "$(jq '.network.allowedDomains | index("api.anthropic.com") != null' "$OUT")"
check "network allowlist carries github.com" "true" \
  "$(jq '.network.allowedDomains | index("github.com") != null' "$OUT")"
# The claude-home settings carve-out: denyWrite takes precedence over allowWrite,
# so these two OS-deny the one file class whose edit dismantles the hook layer.
# Claude-home EXEC guard: settings.json only NAMES the hooks — denying it while
# the hook bodies stay writable protects the pointer, not the target. Found by
# security review (a sandboxed worker wrote into ~/.claude/hooks/ live). The
# behavioural counterpart lives in sandbox_probe.test.sh; this is the shape half.
check "denyWrite covers ~/.claude/hooks (exec guard)" "true" \
  "$(jq --arg p "$HOME/.claude/hooks" '.filesystem.denyWrite | index($p) != null' "$OUT")"
check "denyWrite covers ~/.claude/plugins (exec guard)" "true" \
  "$(jq --arg p "$HOME/.claude/plugins" '.filesystem.denyWrite | index($p) != null' "$OUT")"

check "denyWrite carves out ~/.claude/settings.json" "true" \
  "$(jq --arg p "$HOME/.claude/settings.json" '.filesystem.denyWrite | index($p) != null' "$OUT")"
check "denyWrite carves out ~/.claude/settings.local.json" "true" \
  "$(jq --arg p "$HOME/.claude/settings.local.json" '.filesystem.denyWrite | index($p) != null' "$OUT")"
# allowGitConfig must stay unset/false. srt only emits its .git/config deny
# `if (!allowGitConfig)` (dist/sandbox/macos-sandbox-utils.js). Note this only
# protects the CWD's own .git — see the primary-.git assertions below.
check "allowGitConfig is not enabled" "true" \
  "$(jq '(.filesystem | has("allowGitConfig") | not) or (.filesystem.allowGitConfig == false)' "$OUT")"

# ─── Primary .git hooks/config deny — SANDBOX ESCAPE GUARD ──────────────────
# srt's "mandatory" denies do NOT cover the primary .git in a worktree topology.
# macGetMandatoryDenyPatterns() builds them as path.resolve(cwd, '.git/hooks')
# plus a '**/.git/hooks/**' glob, and normalizePathForSandbox() ANCHORS that
# glob to cwd — so it means "under the worker's worktree", never the primary
# repo, which lives at an unrelated absolute path. allowWrite grants
# %%PRIMARY_GIT%% (required: a linked worktree's objects/refs land there), so
# without these explicit entries a sandboxed worker can write
# <primary>/.git/hooks/pre-commit — which then executes UNSANDBOXED on the next
# git operation in the primary repo. That is a full escape, verified live
# against srt 0.0.65 and closed by these two denies (also verified: the denies
# block hooks+config while ordinary commits still succeed).
check "denyWrite covers the PRIMARY .git/hooks (escape guard)" "true" \
  "$(jq --arg p "$PRIMARY_GIT/hooks" '.filesystem.denyWrite | index($p) != null' "$OUT")"
check "denyWrite covers the PRIMARY .git/config (escape guard)" "true" \
  "$(jq --arg p "$PRIMARY_GIT/config" '.filesystem.denyWrite | index($p) != null' "$OUT")"

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
