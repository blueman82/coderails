#!/bin/bash
# Behavioural test for wiki_taxonomy_gate.sh — feeds synthetic PreToolUse payloads
# against a temp git repo carrying a wiki AGENTS.md and asserts allow vs deny.
# All state lives under a temp dir, never the repo tree.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/wiki_taxonomy_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"

# $VAULT — a wiki repo: AGENTS.md at its root with the "wiki-vault: true"
# marker, a "## Page types" table, AND at least 2 of those directories
# actually present on disk (structural corroboration — see
# wiki_taxonomy_gate.sh's rationale). All three are required; missing any
# one means this would no longer be recognised as a vault at all.
VAULT="$TMP/vault"
mkdir -p "$VAULT/architecture" "$VAULT/investigations" "$VAULT/sources"
git -C "$VAULT" init -q
git -C "$VAULT" config user.email t@t.t
git -C "$VAULT" config user.name t
cat > "$VAULT/AGENTS.md" <<'EOF'
# Wiki AGENTS.md

wiki-vault: true

## Page types

| Directory | Purpose |
|-----------|---------|
| `architecture/` | How the system is built |
| `investigations/` | Filed-back answers to queries |
| `sources/` | Ingested references |
EOF
git -C "$VAULT" add AGENTS.md
git -C "$VAULT" commit -q -m init

# $NOVAULT — a normal repo with a decisions/ dir but NO wiki AGENTS.md at all.
NOVAULT="$TMP/novault"
mkdir -p "$NOVAULT/decisions"
git -C "$NOVAULT" init -q
git -C "$NOVAULT" config user.email t@t.t
git -C "$NOVAULT" config user.name t
git -C "$NOVAULT" commit -q --allow-empty -m init

# $NOSECTION — a repo with AGENTS.md but no "## Page types" section.
NOSECTION="$TMP/nosection"
mkdir -p "$NOSECTION"
git -C "$NOSECTION" init -q
git -C "$NOSECTION" config user.email t@t.t
git -C "$NOSECTION" config user.name t
printf '# AGENTS.md\n\nSome other content.\n' > "$NOSECTION/AGENTS.md"
git -C "$NOSECTION" add AGENTS.md
git -C "$NOSECTION" commit -q -m init

# $BADSHAPE — a repo with a Page types section whose table shape yields zero
# parsed directories (unexpected format) — must fail open, not block-everything.
BADSHAPE="$TMP/badshape"
mkdir -p "$BADSHAPE"
git -C "$BADSHAPE" init -q
git -C "$BADSHAPE" config user.email t@t.t
git -C "$BADSHAPE" config user.name t
cat > "$BADSHAPE/AGENTS.md" <<'EOF'
# AGENTS.md

## Page types

Some prose describing page types, no table at all.
EOF
git -C "$BADSHAPE" add AGENTS.md
git -C "$BADSHAPE" commit -q -m init

fails=0

payload() { # tool file_path cwd -> json
  printf '{"tool_name":"%s","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$1" "$2" "$3"
}
run() { # payload -> DENY|ALLOW
  local out
  out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}
check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# Vault + sanctioned directory -> allow.
check "vault, sanctioned investigations/ -> allow" \
  ALLOW "$(run "$(payload Write "$VAULT/investigations/foo.md" "$VAULT")")"

# Vault + unsanctioned directory -> deny (the incident case).
check "vault, unsanctioned decisions/ -> deny" \
  DENY "$(run "$(payload Write "$VAULT/decisions/foo.md" "$VAULT")")"

# Vault + raw/ (structural, not a page type) -> allow.
check "vault, raw/ -> allow" \
  ALLOW "$(run "$(payload Write "$VAULT/raw/dropped.pdf" "$VAULT")")"

# Vault-root file -> allow.
check "vault, root index.md -> allow" \
  ALLOW "$(run "$(payload Write "$VAULT/index.md" "$VAULT")")"

# Vault + dotfile tooling dir -> allow.
check "vault, .obsidian/ dir -> allow" \
  ALLOW "$(run "$(payload Write "$VAULT/.obsidian/workspace.json" "$VAULT")")"

# Non-vault repo, ANY path incl. a decisions/ dir -> allow (inert outside wikis).
check "non-vault repo, decisions/ -> allow" \
  ALLOW "$(run "$(payload Write "$NOVAULT/decisions/foo.md" "$NOVAULT")")"

# Vault whose AGENTS.md lacks a Page types section -> allow (fail-open).
check "AGENTS.md with no Page types section -> allow" \
  ALLOW "$(run "$(payload Write "$NOSECTION/decisions/foo.md" "$NOSECTION")")"

# Page types section present but table shape unparseable (zero dirs) -> allow
# (fail-open direction; an empty parse must never be read as an empty taxonomy).
check "Page types section, unparseable table -> allow" \
  ALLOW "$(run "$(payload Write "$BADSHAPE/decisions/foo.md" "$BADSHAPE")")"

# $DOCREPO — the regression this hook shipped with and team-lead caught live:
# a CODE repo whose root AGENTS.md documents a taxonomy it does not itself
# implement (e.g. the code repo that builds the agent maintaining a separate
# wiki). It has a parseable Page types table but NONE of those directories
# actually exist at its root — only unrelated source dirs do. Without
# structural corroboration this reads as a vault and blocks every source
# write; with it, it correctly fails open.
DOCREPO="$TMP/docrepo"
mkdir -p "$DOCREPO/src" "$DOCREPO/lib"
git -C "$DOCREPO" init -q
git -C "$DOCREPO" config user.email t@t.t
git -C "$DOCREPO" config user.name t
cat > "$DOCREPO/AGENTS.md" <<'EOF'
# AGENTS.md

## Page types

| Directory | Purpose |
|-----------|---------|
| `architecture/` | How the system is built |
| `investigations/` | Filed-back answers to queries |
| `sources/` | Ingested references |
EOF
git -C "$DOCREPO" add AGENTS.md
git -C "$DOCREPO" commit -q -m init
check "code repo documenting a taxonomy it doesn't implement, src/ -> allow" \
  ALLOW "$(run "$(payload Write "$DOCREPO/src/app.ts" "$DOCREPO")")"
check "code repo documenting a taxonomy it doesn't implement, lib/ -> allow" \
  ALLOW "$(run "$(payload Write "$DOCREPO/lib/util.ts" "$DOCREPO")")"

# $ONEDIR — a repo with exactly ONE sanctioned dir present (below the >=2
# threshold) -> still not a vault, still allow. Confirms the threshold is a
# real floor, not just "any overlap counts".
ONEDIR="$TMP/onedir"
mkdir -p "$ONEDIR/architecture" "$ONEDIR/src"
git -C "$ONEDIR" init -q
git -C "$ONEDIR" config user.email t@t.t
git -C "$ONEDIR" config user.name t
cat > "$ONEDIR/AGENTS.md" <<'EOF'
# AGENTS.md

## Page types

| Directory | Purpose |
|-----------|---------|
| `architecture/` | How the system is built |
| `investigations/` | Filed-back answers to queries |
| `sources/` | Ingested references |
EOF
git -C "$ONEDIR" add AGENTS.md
git -C "$ONEDIR" commit -q -m init
check "only 1 sanctioned dir present (below threshold), src/ -> allow" \
  ALLOW "$(run "$(payload Write "$ONEDIR/src/app.ts" "$ONEDIR")")"

# $NOMARKER — the coderails-shaped case: a plugin/code repo whose AGENTS.md
# has a parseable Page types table AND clears the >=2 structural threshold
# (its own source dirs genuinely overlap the documented taxonomy's names),
# but carries NO wiki-vault: true marker. Structural corroboration alone
# would misidentify this as a vault; the marker requirement is what saves
# it. This is the exact scenario team-lead found live in coderails itself
# (commands/, hooks/, skills/, logs/ overlap coderails-wiki's taxonomy) —
# safe today only because coderails/AGENTS.md has no Page types section,
# which is precisely the tripwire this test exists to catch mechanically
# rather than leaving it to chance.
NOMARKER="$TMP/nomarker"
mkdir -p "$NOMARKER/commands" "$NOMARKER/hooks" "$NOMARKER/skills"
git -C "$NOMARKER" init -q
git -C "$NOMARKER" config user.email t@t.t
git -C "$NOMARKER" config user.name t
cat > "$NOMARKER/AGENTS.md" <<'EOF'
# AGENTS.md

## Page types

| Directory | Purpose |
|-----------|---------|
| `commands/` | Documents one slash command |
| `hooks/` | Documents one hook script |
| `skills/` | Documents one skill |
EOF
git -C "$NOMARKER" add AGENTS.md
git -C "$NOMARKER" commit -q -m init
check "overlapping dirs + parseable table but NO marker, hooks/ -> allow" \
  ALLOW "$(run "$(payload Write "$NOMARKER/hooks/foo.sh" "$NOMARKER")")"
check "overlapping dirs + parseable table but NO marker, commands/ -> allow" \
  ALLOW "$(run "$(payload Write "$NOMARKER/commands/foo.md" "$NOMARKER")")"

# Negative control: prove DENY actually fires, not just that the script exits 0.
out=$(printf '%s' "$(payload Write "$VAULT/decisions/foo.md" "$VAULT")" | bash "$HOOK" 2>/dev/null)
check "deny output carries permissionDecision=deny literally" \
  1 "$(printf '%s' "$out" | grep -c '"permissionDecision": *"deny"')"
check "deny reason names the rejected directory" \
  1 "$(printf '%s' "$out" | grep -c 'decisions/')"
check "deny reason names a sanctioned directory" \
  1 "$(printf '%s' "$out" | grep -c 'investigations/')"

# Real-vault sanity check: the actual assistant-agent-wiki repo now carries
# its own root AGENTS.md with a Page types table (fixed after this hook
# surfaced the gap — it previously lived only in a sibling repo and this
# hook could never reach it). Guarded to skip cleanly if the path is absent
# so the suite stays portable across machines/CI.
REALWIKI="/Users/harrison/Github/assistant-agent-wiki"
if [ -d "$REALWIKI/.git" ] && [ -f "$REALWIKI/AGENTS.md" ]; then
  check "real wiki, unsanctioned decisions/ -> deny" \
    DENY "$(run "$(payload Write "$REALWIKI/decisions/foo.md" "$REALWIKI")")"
  # calendar-log.md is a real root file beyond the index.md/log.md pair —
  # confirms root-file detection is structural (no directory component),
  # not a hardcoded name list that would miss it.
  check "real wiki, root calendar-log.md -> allow" \
    ALLOW "$(run "$(payload Write "$REALWIKI/calendar-log.md" "$REALWIKI")")"
else
  printf 'ok   - real wiki check skipped (path not present on this machine)\n'
fi

# Real-repo false-positive check: assistant-agent is the CODE repo whose
# AGENTS.md documents assistant-agent-wiki's taxonomy from the outside — it
# has a parseable Page types table but none of those directories exist at
# its own root (proactive/, bridge/, gate/, etc. do, not
# architecture/capabilities/patterns/investigations/sources/templates).
# Team-lead live-probed this exact scenario and found every source write in
# the repo denied before structural corroboration was added. Guarded to
# skip cleanly if the path is absent.
REALCODEREPO="/Users/harrison/Github/assistant-agent"
if [ -d "$REALCODEREPO/.git" ] && [ -f "$REALCODEREPO/AGENTS.md" ]; then
  check "real assistant-agent repo, proactive/ -> allow" \
    ALLOW "$(run "$(payload Write "$REALCODEREPO/proactive/memoryIndex.ts" "$REALCODEREPO")")"
  check "real assistant-agent repo, bridge/ -> allow" \
    ALLOW "$(run "$(payload Write "$REALCODEREPO/bridge/telegram-bridge.ts" "$REALCODEREPO")")"
  check "real assistant-agent repo, gate/ -> allow" \
    ALLOW "$(run "$(payload Write "$REALCODEREPO/gate/sendGate.ts" "$REALCODEREPO")")"
else
  printf 'ok   - real assistant-agent repo check skipped (path not present on this machine)\n'
fi

# Taxonomy-is-dynamic: add a fake type to a temp AGENTS.md, confirm that
# directory becomes allowed. Proves the parse is live, not hardcoded. Needs
# >=2 real sanctioned dirs present (architecture/ + zorptastic/ itself once
# created) to be recognised as a vault under structural corroboration.
DYNAMIC="$TMP/dynamic"
mkdir -p "$DYNAMIC/architecture" "$DYNAMIC/zorptastic"
git -C "$DYNAMIC" init -q
git -C "$DYNAMIC" config user.email t@t.t
git -C "$DYNAMIC" config user.name t
cat > "$DYNAMIC/AGENTS.md" <<'EOF'
# AGENTS.md

wiki-vault: true

## Page types

| Directory | Purpose |
|-----------|---------|
| `architecture/` | How the system is built |
| `zorptastic/` | A made-up page type that does not exist anywhere else |
EOF
git -C "$DYNAMIC" add AGENTS.md
git -C "$DYNAMIC" commit -q -m init
check "dynamic taxonomy: fake type not yet added -> deny" \
  DENY "$(run "$(payload Write "$DYNAMIC/zorptastic2/foo.md" "$DYNAMIC")")"
check "dynamic taxonomy: fake type present in table -> allow" \
  ALLOW "$(run "$(payload Write "$DYNAMIC/zorptastic/foo.md" "$DYNAMIC")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
