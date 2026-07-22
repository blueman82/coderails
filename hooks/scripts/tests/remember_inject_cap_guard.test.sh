#!/bin/bash
# Behavioural test for remember_inject_cap_guard.sh — the SessionStart hook
# that re-applies the out-of-git byte-cap patch to the remember plugin's own
# session-start-hook.sh after a plugin bump wipes it.
#
# Every test points the guard at a TEMP fixture via REMEMBER_HOOK_FILE (the
# test seam). The real plugin cache under ~/.claude/plugins is NEVER touched.
# Run: bash hooks/scripts/tests/remember_inject_cap_guard.test.sh
set -u
SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
GUARD="$SCRIPTS/remember_inject_cap_guard.sh"
PATCHES="$(cd "$SCRIPTS/../patches" && pwd)"
VENDOR="$PATCHES/remember_inject_cap.vendor.txt"
PATCHED="$PATCHES/remember_inject_cap.patched.txt"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

# The guard's DEFAULT is warn-only: it will not rewrite another plugin's source
# unless the user opts in. Every test below this line that asserts the patch was
# APPLIED therefore has to run in opt-in mode, so export it once for the whole
# legacy suite rather than at ~15 separate call sites (one missed site would
# fail confusingly). The warn-only block at the end of this file overrides it
# explicitly per test.
export REMEMBER_INJECT_CAP_AUTOWRITE=1
# Never let a warn-only run write its once-per-version stamp into the real
# $HOME/.claude/coderails — point the seam at the temp tree for the whole suite.
export REMEMBER_INJECT_STATE_DIR="$TMP/state-default"

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %q\n  actual:   %q\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# Build a fixture standing in for the plugin's session-start-hook.sh. Arg 2 is
# the path to the MEMORY block to embed (vendor = unpatched, patched = capped).
# The surrounding scaffolding is a runnable stand-in for the parts of the real
# hook the block depends on: it defines the six MFILE variables and HAS_MEMORY,
# so the fixture can actually be EXECUTED to observe injection behaviour --
# the real hook can't be run here because it sources resolve-paths.sh et al.
#
# The scaffolding deliberately carries SEVERAL standalone `if ... fi` blocks, so
# every fixture has MULTIPLE column-0 bare `fi` lines -- the same structural
# property the real session-start-hook.sh has (8 of them). The MEMORY block's
# own last line is a bare `fi`, so a shape gate that counts marker LINES rather
# than matching the block as a contiguous SEQUENCE would see many "matches" and
# refuse to patch the very file this hook exists to patch. Without these extra
# blocks the fixtures hide that defect class entirely, and the regression is
# only observable on a machine that happens to have the live plugin installed.
make_fixture() { # dest block_file mem_dir
  local dest="$1" block="$2" mem="$3"
  {
    printf '%s\n' '#!/bin/bash'
    printf '%s\n' '# fixture stand-in for remember/scripts/session-start-hook.sh'
    printf '%s\n' 'if true; then'
    printf '%s\n' '    :'
    printf '%s\n' 'fi'
    printf 'IDENTITY_FILE="%s/identity.md"\n' "$mem"
    printf 'CORE_MEMORIES="%s/core-memories.md"\n' "$mem"
    printf 'REMEMBER_TODAY_FILE="%s/today.md"\n' "$mem"
    printf 'REMEMBER_NOW="%s/now.md"\n' "$mem"
    printf 'REMEMBER_RECENT="%s/recent.md"\n' "$mem"
    printf 'REMEMBER_ARCHIVE="%s/archive.md"\n' "$mem"
    printf '%s\n' 'HAS_MEMORY="true"'
    # shellcheck disable=SC2016  # emitted into the fixture verbatim, not expanded here
    printf '%s\n' 'if [ -n "$HAS_MEMORY" ]; then'
    printf '%s\n' '    :'
    printf '%s\n' 'fi'
    cat "$block"
    printf '%s\n' 'if true; then'
    printf '%s\n' '    :'
    printf '%s\n' 'fi'
    printf '%s\n' 'echo "=== TRAILER ==="'
  } > "$dest"
  chmod +x "$dest"
}

# --- Test (a): cap ALREADY present -> file untouched, zero output, exit 0 ---
memdir="$TMP/mem-a"; mkdir -p "$memdir"
fx="$TMP/hook-a.sh"
make_fixture "$fx" "$PATCHED" "$memdir"
before=$(shasum "$fx" | awk '{print $1}')
out=$(REMEMBER_HOOK_FILE="$fx" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "cap present: file byte-identical (not rewritten)" "$before" "$after"
check "cap present: zero output" "" "$out"
check "cap present: exit 0" "0" "$rc"
check "cap present: no backup written" "0" "$(find "$TMP" -name 'hook-a.sh.coderails-bak*' | wc -l | tr -d ' ')"

# --- Test (b): cap ABSENT -> patch re-applied, sentinel now present, visible
# notice emitted naming the plugin version, backup written ---
memdir="$TMP/mem-b"; mkdir -p "$memdir"
fx="$TMP/hook-b.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
check "cap absent (precondition): sentinel not in fixture" "0" "$(grep -c REMEMBER_INJECT_MAX_BYTES "$fx" | tr -d ' ')"
# The shape gate must match the vendor block as a contiguous SEQUENCE, not by
# counting its marker lines. This fixture carries several column-0 bare `fi`
# lines (as the real hook does), so a counting implementation sees >1 and
# refuses. Assert the property here so the regression is caught hermetically,
# on any machine, with no dependency on the live plugin cache.
check "cap absent (precondition): fixture has MULTIPLE bare 'fi' lines" "true" \
  "$([ "$(grep -cFx 'fi' "$fx" | tr -d ' ')" -ge 3 ] && echo true || echo false)"
out=$(REMEMBER_HOOK_FILE="$fx" REMEMBER_PLUGIN_VERSION="9.9.9" bash "$GUARD" 2>&1)
rc=$?
check "cap absent: exit 0" "0" "$rc"
check "cap absent: sentinel now present in file" "true" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$fx" && echo true || echo false)"
# shellcheck disable=SC2016  # the literal $REMEMBER_INJECT_MAX_BYTES is the point
check "cap absent: head -c truncation line applied" "true" \
  "$(grep -q 'head -c "\$REMEMBER_INJECT_MAX_BYTES"' "$fx" && echo true || echo false)"
check "cap absent: visible notice emitted (systemMessage JSON)" "true" \
  "$(printf '%s' "$out" | jq -e -r '.systemMessage' >/dev/null 2>&1 && echo true || echo false)"
check "cap absent: notice mentions the plugin version" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q '9\.9\.9' && echo true || echo false)"
# The notice must reach BOTH audiences in one parseable JSON document:
# systemMessage (user-visible) and hookSpecificOutput.additionalContext (the
# model-visible SessionStart channel used by the sibling inject_bootstrap.sh).
check "cap absent: notice is a SINGLE parseable JSON document" "true" \
  "$(printf '%s' "$out" | jq -e . >/dev/null 2>&1 && echo true || echo false)"
check "cap absent: notice also carries SessionStart additionalContext" "true" \
  "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // ""' | grep -q '9\.9\.9' && echo true || echo false)"
check "cap absent: additionalContext declares hookEventName SessionStart" "SessionStart" \
  "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.hookEventName // ""')"
# The rewritten file must stay executable -- it IS the plugin's hook script.
check "cap absent: patched target is still executable" "true" \
  "$([ -x "$fx" ] && echo true || echo false)"
check "cap absent: backup written alongside the target" "1" \
  "$(find "$TMP" -name 'hook-b.sh.coderails-bak*' | wc -l | tr -d ' ')"
check "cap absent: backup holds the ORIGINAL unpatched content" "0" \
  "$(grep -c REMEMBER_INJECT_MAX_BYTES "$(find "$TMP" -name 'hook-b.sh.coderails-bak*' | head -1)" | tr -d ' ')"
# The rest of the file must survive the block swap untouched.
check "cap absent: surrounding scaffolding preserved" "true" \
  "$(grep -q '=== TRAILER ===' "$fx" && echo true || echo false)"

# --- Test (c): idempotent -- a SECOND run over the just-patched file must not
# double-apply. Re-running the guard on test (b)'s now-patched fixture takes
# the "already present" path: no change, no output. ---
before=$(shasum "$fx" | awk '{print $1}')
out2=$(REMEMBER_HOOK_FILE="$fx" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "idempotent: second run leaves file byte-identical" "$before" "$after"
check "idempotent: second run silent" "" "$out2"
check "idempotent: second run exit 0" "0" "$rc"
check "idempotent: sentinel default-assignment line appears exactly once" "1" \
  "$(grep -c 'REMEMBER_INJECT_MAX_BYTES:-8000' "$fx" | tr -d ' ')"

# --- Test (b2): the success notice must report the cap that will actually be
# in force. The patched block reads ${REMEMBER_INJECT_MAX_BYTES:-8000}, so a
# notice hardcoding 8000 states a number that is not the operative cap whenever
# the environment overrides it. ---
memdir="$TMP/mem-b2"; mkdir -p "$memdir"
fx="$TMP/hook-b2.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
out=$(REMEMBER_HOOK_FILE="$fx" REMEMBER_INJECT_MAX_BYTES=1234 bash "$GUARD" 2>&1)
check "notice reports the EFFECTIVE cap under an override" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q 'capped at 1234 bytes' && echo true || echo false)"
check "notice does NOT report the hardcoded default under an override" "false" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q 'capped at 8000 bytes' && echo true || echo false)"

# --- Test (b3): only ONE backup survives. Every run that reaches the backup
# step used to leave a fresh timestamped copy behind forever, so a plugin that
# keeps getting re-installed litters the cache with byte-identical copies.
# The backup name is second-resolution, so repeated runs inside one second
# collide on a single name and would pass this vacuously -- plant backups under
# EARLIER timestamps instead, which is exactly what previous sessions leave. ---
memdir="$TMP/mem-bak"; mkdir -p "$memdir"
fx="$TMP/hook-bak.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
for stamp in 20260101000000 20260102000000; do
  cp "$fx" "$fx.coderails-bak-$stamp"
done
check "backup hygiene (precondition): stale backups are present" "2" \
  "$(find "$TMP" -name 'hook-bak.sh.coderails-bak*' | wc -l | tr -d ' ')"
REMEMBER_HOOK_FILE="$fx" bash "$GUARD" >/dev/null 2>&1
check "backup hygiene: exactly one backup survives (stale ones reaped)" "1" \
  "$(find "$TMP" -name 'hook-bak.sh.coderails-bak*' | wc -l | tr -d ' ')"
check "backup hygiene: the survivor is the one this run wrote" "0" \
  "$(grep -c REMEMBER_INJECT_MAX_BYTES "$(find "$TMP" -name 'hook-bak.sh.coderails-bak*' | head -1)" | tr -d ' ')"

# --- Test (c-comment): the token present ONLY as a comment must NOT count as
# "already capped". A bare substring grep for REMEMBER_INJECT_MAX_BYTES is
# satisfied by a changelog line or the residue of a half-applied edit, so the
# guard would exit silently while the truncation code is absent -- swallowing
# the exact condition it exists to detect. Detection must key on evidence of
# the PATCH ITSELF, not on the token appearing anywhere in the file. ---
memdir="$TMP/mem-cc"; mkdir -p "$memdir"
fx="$TMP/hook-cc.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
printf '%s\n' '# REMEMBER_INJECT_MAX_BYTES was here once' >> "$fx"
out=$(REMEMBER_HOOK_FILE="$fx" REMEMBER_PLUGIN_VERSION="9.9.9" bash "$GUARD" 2>&1)
rc=$?
check "token-as-comment only: exit 0" "0" "$rc"
# shellcheck disable=SC2016  # the literal $REMEMBER_INJECT_MAX_BYTES is the point
check "token-as-comment only: guard still applied the truncation line" "true" \
  "$(grep -q 'head -c "\$REMEMBER_INJECT_MAX_BYTES"' "$fx" && echo true || echo false)"
check "token-as-comment only: notice emitted (not a silent no-op)" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q '9\.9\.9' && echo true || echo false)"

# --- Test (d): unrecognised shape (anchor block not found) -> file NOT
# modified, warning emitted, exit 0. Simulates a future vendor rewrite of the
# MEMORY block that the stored search text no longer matches. ---
fx="$TMP/hook-d.sh"
{
  printf '%s\n' '#!/bin/bash'
  printf '%s\n' '# a totally different vendor shape -- no matching MEMORY block'
  printf '%s\n' 'echo "vendor rewrote this entirely"'
} > "$fx"
before=$(shasum "$fx" | awk '{print $1}')
out=$(REMEMBER_HOOK_FILE="$fx" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "unrecognised shape: file NOT modified" "$before" "$after"
check "unrecognised shape: exit 0 (fail-open)" "0" "$rc"
check "unrecognised shape: warning emitted" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -qi 'by hand' && echo true || echo false)"
check "unrecognised shape: no backup written (nothing was touched)" "0" \
  "$(find "$TMP" -name 'hook-d.sh.coderails-bak*' | wc -l | tr -d ' ')"

# --- Test (d2): AMBIGUOUS shape -- the search block appears TWICE. A blind
# replace-all would corrupt the file; the guard must refuse. Without this
# case a "replace every occurrence" implementation passes test (d) too. ---
memdir="$TMP/mem-d2"; mkdir -p "$memdir"
fx="$TMP/hook-d2.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
cat "$VENDOR" >> "$fx"
before=$(shasum "$fx" | awk '{print $1}')
out=$(REMEMBER_HOOK_FILE="$fx" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "ambiguous shape: file NOT modified when block matches twice" "$before" "$after"
check "ambiguous shape: exit 0" "0" "$rc"
check "ambiguous shape: warning emitted" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -qi 'by hand' && echo true || echo false)"

# --- Test (e): target file MISSING -> no crash, no write, exit 0 ---
REMEMBER_HOOK_FILE="$TMP/does-not-exist/session-start-hook.sh" bash "$GUARD" >/dev/null 2>&1
rc=$?
check "missing target: exit 0" "0" "$rc"
check "missing target: nothing created" "false" \
  "$([ -e "$TMP/does-not-exist/session-start-hook.sh" ] && echo true || echo false)"

# --- Test (e2): target file UNREADABLE -> no crash, exit 0, not modified ---
memdir="$TMP/mem-e2"; mkdir -p "$memdir"
fx="$TMP/hook-e2.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
before=$(shasum "$fx" | awk '{print $1}')
chmod 000 "$fx"
REMEMBER_HOOK_FILE="$fx" bash "$GUARD" >/dev/null 2>&1
rc=$?
chmod 644 "$fx"
after=$(shasum "$fx" | awk '{print $1}')
check "unreadable target: exit 0" "0" "$rc"
check "unreadable target: file unchanged" "$before" "$after"

# --- Test (f): BEHAVIOURAL PROOF -- the patched output actually truncates.
# Not "the string is present": patch a vendor fixture, EXECUTE it, and assert
# an oversized memory file is capped at REMEMBER_INJECT_MAX_BYTES while a
# small one is emitted whole. This is the only test that proves the re-applied
# patch does the job it exists to do. ---
memdir="$TMP/mem-f"; mkdir -p "$memdir"
# 50,000 bytes of 'x' -> far over the 8000-byte default cap.
awk 'BEGIN{for(i=0;i<50000;i++)printf "x"}' > "$memdir/now.md"
printf 'small-identity-content\n' > "$memdir/identity.md"
fx="$TMP/hook-f.sh"
make_fixture "$fx" "$VENDOR" "$memdir"

# Baseline: the UNPATCHED fixture emits the oversized file in full. Without
# this the "8000" assertion below can't distinguish a working cap from a
# fixture that never had 50000 bytes to emit in the first place.
# Measure the payload by isolating the single longest RUN of 'x' in the
# output. Counting every 'x' character would be contaminated by the temp-dir
# path echoed in the truncation notice (mktemp names contain letters), which
# is exactly the kind of instrument defect that turns a passing cap into an
# off-by-N failure.
longest_x_run() { tr -c 'x' '\n' | awk '{ if (length($0) > m) m = length($0) } END { print m+0 }'; }

raw=$(bash "$fx")
raw_x=$(printf '%s' "$raw" | longest_x_run)
check "truncation proof (baseline): unpatched fixture emits all 50000 bytes" "50000" "$raw_x"

REMEMBER_HOOK_FILE="$fx" bash "$GUARD" >/dev/null 2>&1
out=$(bash "$fx")
x_count=$(printf '%s' "$out" | longest_x_run)
check "truncation proof: oversized now.md capped to 8000 bytes (was 50000)" "8000" "$x_count"
check "truncation proof: truncation notice emitted" "true" \
  "$(printf '%s' "$out" | grep -q 'truncated to 8000 bytes' && echo true || echo false)"
check "truncation proof: small identity.md emitted whole (not truncated)" "true" \
  "$(printf '%s' "$out" | grep -q 'small-identity-content' && echo true || echo false)"

# --- Test (f2): the cap is env-overridable, as the patch advertises ---
out=$(REMEMBER_INJECT_MAX_BYTES=100 bash "$fx")
x_count=$(printf '%s' "$out" | longest_x_run)
check "truncation proof: REMEMBER_INJECT_MAX_BYTES=100 honoured" "100" "$x_count"

# --- Test (g): version resolution -- with no REMEMBER_HOOK_FILE override the
# guard reads installPath/version out of an installed_plugins.json-shaped
# file. Points CLAUDE_PLUGINS_DIR at a fixture tree, never the real one. ---
pdir="$TMP/plugins-g"
vdir="$pdir/cache/claude-plugins-official/remember/1.2.3/scripts"
mkdir -p "$vdir"
memdir="$TMP/mem-g"; mkdir -p "$memdir"
make_fixture "$vdir/session-start-hook.sh" "$VENDOR" "$memdir"
jq -n --arg p "$pdir/cache/claude-plugins-official/remember/1.2.3" \
  '{version:2,plugins:{"remember@claude-plugins-official":[{scope:"user",installPath:$p,version:"1.2.3"}]}}' \
  > "$pdir/installed_plugins.json"
out=$(CLAUDE_PLUGINS_DIR="$pdir" bash "$GUARD" 2>&1)
rc=$?
check "version resolution: exit 0" "0" "$rc"
check "version resolution: patched the installPath-resolved 1.2.3 file" "true" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$vdir/session-start-hook.sh" && echo true || echo false)"
check "version resolution: notice names version 1.2.3 from the manifest" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q '1\.2\.3' && echo true || echo false)"

# --- Test (g-scope): MULTI-SCOPE manifest. Several install records can be on
# disk at once (a stale project-scoped copy alongside the user-scoped one that
# Claude Code actually runs). Taking the first record whose installPath exists
# patches whichever the manifest happens to list first, so the user is told the
# cap was re-applied while the running install stays uncapped. The user-scoped
# record must win regardless of ordering. ---
pdir="$TMP/plugins-scope"
memdir="$TMP/mem-scope"; mkdir -p "$memdir"
proj="$pdir/cache/claude-plugins-official/remember/0.1.0"
usr="$pdir/cache/claude-plugins-official/remember/2.0.0"
mkdir -p "$proj/scripts" "$usr/scripts"
make_fixture "$proj/scripts/session-start-hook.sh" "$VENDOR" "$memdir"
make_fixture "$usr/scripts/session-start-hook.sh" "$VENDOR" "$memdir"
mkdir -p "$pdir"
jq -n --arg proj "$proj" --arg usr "$usr" \
  '{version:2,plugins:{"remember@claude-plugins-official":[
     {scope:"project",installPath:$proj,version:"0.1.0"},
     {scope:"user",installPath:$usr,version:"2.0.0"}]}}' \
  > "$pdir/installed_plugins.json"
out=$(CLAUDE_PLUGINS_DIR="$pdir" bash "$GUARD" 2>&1)
check "multi-scope: the USER-scoped 2.0.0 install was patched" "true" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$usr/scripts/session-start-hook.sh" && echo true || echo false)"
check "multi-scope: the project-scoped 0.1.0 install was left alone" "false" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$proj/scripts/session-start-hook.sh" && echo true || echo false)"
check "multi-scope: notice names 2.0.0, not the first-listed 0.1.0" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q '2\.0\.0' && echo true || echo false)"

# --- Test (g2): manifest absent -> glob fallback picks the HIGHEST version
# directory present, and says so. Two versions installed side by side (the
# shape a plugin bump leaves behind); only the higher may be patched.
# 0.10.0 vs 0.8.3 also proves the sort is version-aware, not lexicographic
# (a plain sort would wrongly rank 0.8.3 above 0.10.0). ---
pdir="$TMP/plugins-g2"
memdir="$TMP/mem-g2"; mkdir -p "$memdir"
for v in 0.8.3 0.10.0; do
  mkdir -p "$pdir/cache/claude-plugins-official/remember/$v/scripts"
  make_fixture "$pdir/cache/claude-plugins-official/remember/$v/scripts/session-start-hook.sh" "$VENDOR" "$memdir"
done
out=$(CLAUDE_PLUGINS_DIR="$pdir" bash "$GUARD" 2>&1)
rc=$?
check "glob fallback: exit 0" "0" "$rc"
check "glob fallback: highest version (0.10.0) patched" "true" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$pdir/cache/claude-plugins-official/remember/0.10.0/scripts/session-start-hook.sh" && echo true || echo false)"
check "glob fallback: lower version (0.8.3) left alone" "false" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$pdir/cache/claude-plugins-official/remember/0.8.3/scripts/session-start-hook.sh" && echo true || echo false)"

# --- Test (h): remember plugin not installed at all -> silent, exit 0.
# A machine without the remember plugin must not get a warning every session. ---
pdir="$TMP/plugins-h"; mkdir -p "$pdir"
out=$(CLAUDE_PLUGINS_DIR="$pdir" bash "$GUARD" 2>&1)
rc=$?
check "plugin absent: exit 0" "0" "$rc"
check "plugin absent: silent (no nag on machines without remember)" "" "$out"

# --- Test (i2): file MODE is preserved across the rewrite. `chmod
# --reference` is GNU-only and silently fails on macOS, so a naive
# implementation quietly falls back to a default mode. Use a distinctive
# non-default mode (0700) that neither `chmod +x` nor a fresh-file default
# would reproduce -- that is what makes this test discriminate. ---
memdir="$TMP/mem-mode"; mkdir -p "$memdir"
fx="$TMP/hook-mode.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
chmod 700 "$fx"
REMEMBER_HOOK_FILE="$fx" bash "$GUARD" >/dev/null 2>&1
mode_now=$(stat -f '%Lp' "$fx" 2>/dev/null || stat -c '%a' "$fx" 2>/dev/null)
check "mode preservation: 0700 target still 700 after re-patch" "700" "$mode_now"
check "mode preservation (precondition): the patch was actually applied" "true" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$fx" && echo true || echo false)"

# --- Test (j): REALISTIC-SHAPE fixture. The minimal fixtures above contain
# exactly one bare `fi` -- the vendor block's own -- which structurally hides
# a whole class of shape-gate defect. The real session-start-hook.sh has 8
# column-0 `fi` lines, so any gate that counts marker LINES rather than
# matching the block as a contiguous SEQUENCE refuses to patch the exact file
# this hook exists to patch. Reconstruct a pristine vendor file by reverse-
# applying the patch to a COPY of the live cache file (the real file is only
# ever READ, never written), then assert the guard patches it.
#
# The against-the-live-cache half below is a BONUS: it needs the plugin
# installed AND the deployed copy to still carry the current patched block. A
# change to the patch text's own comment (which the guard does not re-apply,
# since detection keys on the truncation call, not the comment) legitimately
# makes the deployed copy stale, so the byte-exact round trip is gated on
# freshness rather than asserted unconditionally. The hermetic coverage that
# this test exists for -- a many-`fi` file must still patch -- lives in
# make_fixture and runs on every machine, live cache or not.
LIVE="$HOME/.claude/plugins/cache/claude-plugins-official/remember/0.8.3/scripts/session-start-hook.sh"
live_is_current=false
if [ -r "$LIVE" ] && grep -qF "$(head -1 "$PATCHED")" "$LIVE" 2>/dev/null; then
  # Deployed copy carries the CURRENT patched block verbatim?
  if awk '
    FNR==1 { fidx++ }
    fidx==1 { pat[++np]=$0; next }
    { line[++nl]=$0 }
    END {
      for (i=1; i<=nl-np+1; i++) {
        ok=1
        for (j=1; j<=np; j++) if (line[i+j-1] != pat[j]) { ok=0; break }
        if (ok) exit 0
      }
      exit 1
    }
  ' "$PATCHED" "$LIVE" 2>/dev/null; then
    live_is_current=true
  fi
fi
if [ "$live_is_current" = true ]; then
  fx="$TMP/hook-real.sh"
  # Reverse the patch: swap the patched block back to the vendor block.
  awk '
    FNR==1 { fidx++ }
    fidx==1 { pat[++np]=$0; next }
    fidx==2 { rep[++nr]=$0; next }
    { line[++nl]=$0 }
    END {
      i=1
      while (i <= nl) {
        ok=(i+np-1 <= nl)
        if (ok) for (j=1; j<=np; j++) if (line[i+j-1] != pat[j]) { ok=0; break }
        if (ok) { for (j=1; j<=nr; j++) print rep[j]; i += np }
        else { print line[i]; i++ }
      }
    }
  ' "$PATCHED" "$VENDOR" "$LIVE" > "$fx"
  check "realistic fixture (precondition): reverse-apply produced an UNPATCHED file" "0" \
    "$(grep -c REMEMBER_INJECT_MAX_BYTES "$fx" | tr -d ' ')"
  check "realistic fixture (precondition): it really does have many bare 'fi' lines" "true" \
    "$([ "$(grep -cFx 'fi' "$fx" | tr -d ' ')" -ge 2 ] && echo true || echo false)"
  out=$(REMEMBER_HOOK_FILE="$fx" REMEMBER_PLUGIN_VERSION="0.9.0" bash "$GUARD" 2>&1)
  rc=$?
  check "realistic fixture: exit 0" "0" "$rc"
  check "realistic fixture: cap APPLIED to a real-shaped vendor file" "true" \
    "$(grep -q REMEMBER_INJECT_MAX_BYTES "$fx" && echo true || echo false)"
  check "realistic fixture: notice emitted (not a refuse-by-hand warning)" "false" \
    "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -qi 'by hand' && echo true || echo false)"
  # The reconstructed-vendor round trip must be lossless: re-patching the
  # reversed file has to reproduce the live file byte-for-byte. This is what
  # proves hooks/patches/*.txt are byte-exact against the real target.
  check "realistic fixture: round trip reproduces the live file byte-for-byte" \
    "$(shasum "$LIVE" | awk '{print $1}')" "$(shasum "$fx" | awk '{print $1}')"
else
  printf 'skip - live-cache round trip (plugin absent, or deployed copy predates the current patch text)\n'
fi

# --- Test (j2): HERMETIC lossless inverse. The reverse-apply above depends on
# the live cache; this does not. Build a PATCHED fixture, reverse the patch to
# get the vendor shape back, run the guard over it, and assert the result is
# byte-identical to the original. Proves vendor.txt and patched.txt are exact
# inverses of one another on any machine. ---
memdir="$TMP/mem-j2"; mkdir -p "$memdir"
orig="$TMP/hook-j2-orig.sh"
fx="$TMP/hook-j2.sh"
make_fixture "$orig" "$PATCHED" "$memdir"
awk '
  FNR==1 { fidx++ }
  fidx==1 { pat[++np]=$0; next }
  fidx==2 { rep[++nr]=$0; next }
  { line[++nl]=$0 }
  END {
    i=1
    while (i <= nl) {
      ok=(i+np-1 <= nl)
      if (ok) for (j=1; j<=np; j++) if (line[i+j-1] != pat[j]) { ok=0; break }
      if (ok) { for (j=1; j<=nr; j++) print rep[j]; i += np }
      else { print line[i]; i++ }
    }
  }
' "$PATCHED" "$VENDOR" "$orig" > "$fx"
chmod +x "$fx"
check "lossless inverse (precondition): reverse-apply produced an UNPATCHED file" "0" \
  "$(grep -c REMEMBER_INJECT_MAX_BYTES "$fx" | tr -d ' ')"
REMEMBER_HOOK_FILE="$fx" bash "$GUARD" >/dev/null 2>&1
check "lossless inverse: re-patching reproduces the original byte-for-byte" \
  "$(shasum "$orig" | awk '{print $1}')" "$(shasum "$fx" | awk '{print $1}')"

# --- Test (i): canonical patch text missing from the repo -> the guard must
# not half-write anything, and must not crash. ---
memdir="$TMP/mem-i"; mkdir -p "$memdir"
fx="$TMP/hook-i.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
before=$(shasum "$fx" | awk '{print $1}')
out=$(REMEMBER_HOOK_FILE="$fx" REMEMBER_PATCH_DIR="$TMP/no-such-patch-dir" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "patch text missing: exit 0" "0" "$rc"
check "patch text missing: target NOT modified" "$before" "$after"

# --- Test (i3): the POST-WRITE sanity gate. Before the rewrite replaces the
# target, the guard must verify the rewrite actually contains the cap. Point
# REMEMBER_PATCH_DIR at a patch dir whose replacement block is well-formed but
# carries NO cap: the block match succeeds and the rewrite runs, so only the
# post-write check can stop it. The target must be left byte-identical and the
# guard must warn. Without this case the sanity gate can be deleted outright
# and every other test still passes. ---
baddir="$TMP/patches-nosentinel"; mkdir -p "$baddir"
cp "$VENDOR" "$baddir/remember_inject_cap.vendor.txt"
# A replacement that is valid shell and swaps in cleanly, but omits the cap.
sed 's/=== MEMORY ===/=== MEMORY (no cap) ===/' "$VENDOR" \
  > "$baddir/remember_inject_cap.patched.txt"
check "sanity gate (precondition): replacement block carries no sentinel" "0" \
  "$(grep -c REMEMBER_INJECT_MAX_BYTES "$baddir/remember_inject_cap.patched.txt" | tr -d ' ')"
memdir="$TMP/mem-i3"; mkdir -p "$memdir"
fx="$TMP/hook-i3.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
before=$(shasum "$fx" | awk '{print $1}')
out=$(REMEMBER_HOOK_FILE="$fx" REMEMBER_PATCH_DIR="$baddir" \
  REMEMBER_PLUGIN_VERSION="9.9.9" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "sanity gate: exit 0" "0" "$rc"
check "sanity gate: target left byte-identical (unverified rewrite refused)" "$before" "$after"
check "sanity gate: warning emitted" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -qi 'did not verify' && echo true || echo false)"
check "sanity gate: no temp file left behind" "0" \
  "$(find "$TMP" -name 'hook-i3.sh.coderails-tmp*' | wc -l | tr -d ' ')"

# ===========================================================================
# WARN-ONLY DEFAULT. Everything above ran with REMEMBER_INJECT_CAP_AUTOWRITE=1
# because it asserts write behaviour. The DEFAULT, though, is warn-only:
# coderails is a public plugin and must not silently rewrite another plugin's
# source on a user's machine. These tests unset/zero the opt-in explicitly.
# ===========================================================================

# --- Test (w1): DEFAULT (var unset), cap missing -> target byte-identical, a
# notice explaining the opt-in emitted, exit 0, nothing written anywhere. ---
memdir="$TMP/mem-w1"; mkdir -p "$memdir"
fx="$TMP/hook-w1.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
before=$(shasum "$fx" | awk '{print $1}')
out=$(env -u REMEMBER_INJECT_CAP_AUTOWRITE REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$TMP/state-w1" \
  REMEMBER_PLUGIN_VERSION="9.9.9" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "default warn-only: exit 0" "0" "$rc"
check "default warn-only: target byte-identical (NOT rewritten)" "$before" "$after"
check "default warn-only: no backup written" "0" \
  "$(find "$TMP" -name 'hook-w1.sh.coderails-bak*' | wc -l | tr -d ' ')"
check "default warn-only: no temp file left behind" "0" \
  "$(find "$TMP" -name 'hook-w1.sh.coderails-tmp*' | wc -l | tr -d ' ')"
check "default warn-only: notice emitted (single parseable JSON document)" "true" \
  "$(printf '%s' "$out" | jq -e . >/dev/null 2>&1 && echo true || echo false)"
# The notice is only useful if it names the exact opt-in switch and where to set
# it -- a vague "the cap is missing" leaves the user with no action to take.
check "default warn-only: notice names the opt-in env var" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q 'REMEMBER_INJECT_CAP_AUTOWRITE' && echo true || echo false)"
check "default warn-only: notice names settings.json as where to set it" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q 'settings\.json' && echo true || echo false)"
check "default warn-only: notice states coderails will not modify without permission" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -qi 'without your permission' && echo true || echo false)"
check "default warn-only: notice names the plugin version" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q '9\.9\.9' && echo true || echo false)"

# --- Test (w2): explicit =0 is warn-only too (not just "unset"). A gate keyed
# on "is the var set at all" would pass w1 and fail here. ---
memdir="$TMP/mem-w2"; mkdir -p "$memdir"
fx="$TMP/hook-w2.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
before=$(shasum "$fx" | awk '{print $1}')
out=$(REMEMBER_INJECT_CAP_AUTOWRITE=0 REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$TMP/state-w2" bash "$GUARD" 2>&1)
rc=$?
after=$(shasum "$fx" | awk '{print $1}')
check "explicit =0: exit 0" "0" "$rc"
check "explicit =0: target byte-identical (NOT rewritten)" "$before" "$after"
check "explicit =0: notice still emitted" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q 'REMEMBER_INJECT_CAP_AUTOWRITE' && echo true || echo false)"

# --- Test (w3): opt-in mode on the SAME fixture shape still patches. Proves the
# gate is the only thing standing between warn-only and the old behaviour. ---
memdir="$TMP/mem-w3"; mkdir -p "$memdir"
fx="$TMP/hook-w3.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
out=$(REMEMBER_INJECT_CAP_AUTOWRITE=1 REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_PLUGIN_VERSION="9.9.9" bash "$GUARD" 2>&1)
rc=$?
check "opt-in =1: exit 0" "0" "$rc"
check "opt-in =1: patch APPLIED (cap present)" "true" \
  "$(grep -q REMEMBER_INJECT_MAX_BYTES "$fx" && echo true || echo false)"
check "opt-in =1: notice is the re-applied one, not the opt-in nag" "false" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q 'REMEMBER_INJECT_CAP_AUTOWRITE=1' && echo true || echo false)"

# --- Test (w4): SUPPRESSION. The reviewer ran three consecutive sessions on a
# plugin whose block shape differs and got three identical nags -- no
# suppression, no opt-out. Two warn-only runs at the SAME version must notify
# exactly ONCE. ---
memdir="$TMP/mem-w4"; mkdir -p "$memdir"
fx="$TMP/hook-w4.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
statedir="$TMP/state-w4"
first=$(env -u REMEMBER_INJECT_CAP_AUTOWRITE REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$statedir" REMEMBER_PLUGIN_VERSION="1.0.0" bash "$GUARD" 2>&1)
second=$(env -u REMEMBER_INJECT_CAP_AUTOWRITE REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$statedir" REMEMBER_PLUGIN_VERSION="1.0.0" bash "$GUARD" 2>&1)
rc=$?
check "suppression: first run notifies" "true" \
  "$(printf '%s' "$first" | jq -r '.systemMessage // ""' | grep -q 'REMEMBER_INJECT_CAP_AUTOWRITE' && echo true || echo false)"
check "suppression: second run at the same version is SILENT" "" "$second"
check "suppression: second run exit 0" "0" "$rc"

# --- Test (w5): a NEW version must warn again -- suppression is per-version,
# not permanent. A plugin bump is exactly when the user needs to hear about it. ---
third=$(env -u REMEMBER_INJECT_CAP_AUTOWRITE REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$statedir" REMEMBER_PLUGIN_VERSION="1.1.0" bash "$GUARD" 2>&1)
rc=$?
check "new version: warns again after a bump" "true" \
  "$(printf '%s' "$third" | jq -r '.systemMessage // ""' | grep -q '1\.1\.0' && echo true || echo false)"
check "new version: exit 0" "0" "$rc"
# ...and the new version is now itself suppressed.
fourth=$(env -u REMEMBER_INJECT_CAP_AUTOWRITE REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$statedir" REMEMBER_PLUGIN_VERSION="1.1.0" bash "$GUARD" 2>&1)
check "new version: the bumped version is suppressed on its second run" "" "$fourth"

# --- Test (w6): UNWRITABLE stamp location -> still warns, exit 0, no crash.
# The stamp is a convenience; failing to write it must never cost the user the
# notice or take the session down with it. ---
memdir="$TMP/mem-w6"; mkdir -p "$memdir"
fx="$TMP/hook-w6.sh"
make_fixture "$fx" "$VENDOR" "$memdir"
nowrite="$TMP/nowrite"; mkdir -p "$nowrite"; chmod 500 "$nowrite"
out=$(env -u REMEMBER_INJECT_CAP_AUTOWRITE REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$nowrite/state" REMEMBER_PLUGIN_VERSION="3.3.3" bash "$GUARD" 2>&1)
rc=$?
chmod 700 "$nowrite"
check "unwritable stamp dir: exit 0 (no crash)" "0" "$rc"
check "unwritable stamp dir: notice still emitted (fail-open)" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q '3\.3\.3' && echo true || echo false)"
# The failed stamp write must not CORRUPT the notice. A failing output
# redirection is diagnosed by the shell before the command runs, so a
# per-command `2>/dev/null` does not suppress it and the diagnostic lands in
# the hook's output -- where it breaks the JSON document Claude Code parses.
# A grep-for-the-version assertion passes happily on mangled output; only
# parsing the whole document discriminates.
check "unwritable stamp dir: notice is still VALID JSON (no leaked shell error)" "true" \
  "$(printf '%s' "$out" | jq -e . >/dev/null 2>&1 && echo true || echo false)"
check "unwritable stamp dir: target still byte-identical" "true" \
  "$(grep -qc REMEMBER_INJECT_MAX_BYTES "$fx" >/dev/null 2>&1 && echo false || echo true)"

# --- Test (w7): warn-only mode must NOT write into the plugins dir at all.
# Resolve the target through the manifest (no REMEMBER_HOOK_FILE seam) and
# assert the whole fixture plugin tree is unchanged. ---
pdir="$TMP/plugins-w7"
vdir="$pdir/cache/claude-plugins-official/remember/4.5.6/scripts"
mkdir -p "$vdir"
memdir="$TMP/mem-w7"; mkdir -p "$memdir"
make_fixture "$vdir/session-start-hook.sh" "$VENDOR" "$memdir"
jq -n --arg p "$pdir/cache/claude-plugins-official/remember/4.5.6" \
  '{version:2,plugins:{"remember@claude-plugins-official":[{scope:"user",installPath:$p,version:"4.5.6"}]}}' \
  > "$pdir/installed_plugins.json"
tree_before=$(find "$pdir" -type f | sort | xargs shasum | shasum | awk '{print $1}')
out=$(env -u REMEMBER_INJECT_CAP_AUTOWRITE CLAUDE_PLUGINS_DIR="$pdir" \
  REMEMBER_INJECT_STATE_DIR="$TMP/state-w7" bash "$GUARD" 2>&1)
rc=$?
tree_after=$(find "$pdir" -type f | sort | xargs shasum | shasum | awk '{print $1}')
check "warn-only via manifest: exit 0" "0" "$rc"
check "warn-only via manifest: plugin tree completely unchanged" "$tree_before" "$tree_after"
check "warn-only via manifest: notice names the resolved version 4.5.6" "true" \
  "$(printf '%s' "$out" | jq -r '.systemMessage // ""' | grep -q '4\.5\.6' && echo true || echo false)"

# --- Test (w8): genuine ERROR warnings are NOT suppressed. Suppression covers
# the opt-in notice only. An unrecognised file shape names a real fault the user
# must see on EVERY session, not once per version. This runs in opt-in mode
# because the shape check is only reached once writing is permitted. ---
fx="$TMP/hook-w8.sh"
{
  printf '%s\n' '#!/bin/bash'
  printf '%s\n' '# a totally different vendor shape -- no matching MEMORY block'
} > "$fx"
statedir="$TMP/state-w8"
e1=$(REMEMBER_INJECT_CAP_AUTOWRITE=1 REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$statedir" REMEMBER_PLUGIN_VERSION="5.0.0" bash "$GUARD" 2>&1)
e2=$(REMEMBER_INJECT_CAP_AUTOWRITE=1 REMEMBER_HOOK_FILE="$fx" \
  REMEMBER_INJECT_STATE_DIR="$statedir" REMEMBER_PLUGIN_VERSION="5.0.0" bash "$GUARD" 2>&1)
check "error not suppressed: first run warns about the shape" "true" \
  "$(printf '%s' "$e1" | jq -r '.systemMessage // ""' | grep -qi 'by hand' && echo true || echo false)"
check "error not suppressed: SECOND run warns again (real fault, not a nag)" "true" \
  "$(printf '%s' "$e2" | jq -r '.systemMessage // ""' | grep -qi 'by hand' && echo true || echo false)"

# shellcheck disable=SC2015  # matches the house idiom in loop_cost.test.sh
[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails failures)"; exit 1; }
