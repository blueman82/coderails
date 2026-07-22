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
make_fixture() { # dest block_file mem_dir
  local dest="$1" block="$2" mem="$3"
  {
    printf '%s\n' '#!/bin/bash'
    printf '%s\n' '# fixture stand-in for remember/scripts/session-start-hook.sh'
    printf 'IDENTITY_FILE="%s/identity.md"\n' "$mem"
    printf 'CORE_MEMORIES="%s/core-memories.md"\n' "$mem"
    printf 'REMEMBER_TODAY_FILE="%s/today.md"\n' "$mem"
    printf 'REMEMBER_NOW="%s/now.md"\n' "$mem"
    printf 'REMEMBER_RECENT="%s/recent.md"\n' "$mem"
    printf 'REMEMBER_ARCHIVE="%s/archive.md"\n' "$mem"
    printf '%s\n' 'HAS_MEMORY="true"'
    cat "$block"
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
LIVE="$HOME/.claude/plugins/cache/claude-plugins-official/remember/0.8.3/scripts/session-start-hook.sh"
if [ -r "$LIVE" ]; then
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
  printf 'skip - realistic-shape fixture (remember plugin not installed here)\n'
fi

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

# shellcheck disable=SC2015  # matches the house idiom in loop_cost.test.sh
[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails failures)"; exit 1; }
