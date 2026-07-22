#!/usr/bin/env bash
# SessionStart hook — re-applies the remember-plugin memory-injection byte cap.
#
# WHY THIS EXISTS
#   The "token-burn reduction" work of 2026-07-17 shipped seven measures. Six
#   went in via PRs. The seventh caps each memory file the remember plugin
#   injects at session start to REMEMBER_INJECT_MAX_BYTES (default 8000) — but
#   it had to be applied BY HAND to a file inside the version-pinned plugin
#   cache, which is not in git. A plugin bump installs a fresh directory
#   (remember/0.8.3 -> remember/0.9.0) carrying an unpatched copy, and the cap
#   silently disappears. This hook detects that and re-applies it, keeping the
#   canonical patch text version-controlled under hooks/patches/.
#
# HOW THE TARGET IS RESOLVED
#   The ACTIVE remember version is read from Claude Code's own manifest,
#   ~/.claude/plugins/installed_plugins.json — the "remember@..." entry's
#   .installPath is authoritative, so a bump is followed automatically. If that
#   manifest (or jq) is unavailable, we fall back to globbing the version
#   directories under cache/*/remember/ and taking the HIGHEST by `sort -V`.
#   The fallback is a heuristic: if two versions are installed side by side and
#   Claude Code is running the lower one, we would patch the wrong tree. That
#   is acceptable — patching an inactive copy is inert, and the manifest path
#   is the normal case.
#
# HOW THE PATCH IS APPLIED
#   Whole-block literal search/replace, not a context diff: hooks/patches/
#   holds the vendor's unpatched MEMORY block (the search) and the patched one
#   (the replace). The search block must occur EXACTLY ONCE. Zero matches (the
#   vendor rewrote the block) or more than one (ambiguous) means we do not
#   recognise the file's shape, so we refuse to write and tell the user to
#   re-apply by hand. Line-number-based tooling would drift silently across a
#   vendor bump; a literal block match fails cleanly instead.
#
# SAFETY
#   Fail-open throughout: this hook never exits non-zero and never blocks
#   session start. It backs the target up before writing, and writes via a
#   temp file + mv, so the target is never left half-patched.
#
# ENVIRONMENT (all optional; the first two exist as test seams)
#   REMEMBER_HOOK_FILE     Target file, bypassing all version resolution.
#   REMEMBER_PATCH_DIR     Directory holding the canonical patch text.
#   CLAUDE_PLUGINS_DIR     Plugin root (default: $HOME/.claude/plugins).
#   REMEMBER_PLUGIN_VERSION  Version string used in the notice.
#
# EXIT CODES
#   0   Always.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCH_DIR="${REMEMBER_PATCH_DIR:-"$(cd "${SCRIPT_DIR}/.." && pwd)/patches"}"
VENDOR_BLOCK="${PATCH_DIR}/remember_inject_cap.vendor.txt"
PATCHED_BLOCK="${PATCH_DIR}/remember_inject_cap.patched.txt"
PLUGINS_DIR="${CLAUDE_PLUGINS_DIR:-"$HOME/.claude/plugins"}"
SENTINEL="REMEMBER_INJECT_MAX_BYTES"

# Emit a notice on BOTH channels in ONE JSON document (two concatenated
# top-level objects would not parse as a single document — see the same note
# in loop_stall_guard.sh):
#   systemMessage    — the user-visible channel (loop_stall_guard.sh's idiom).
#   additionalContext — the model-visible SessionStart channel, matching this
#                       repo's sibling SessionStart hook inject_bootstrap.sh.
# Both matter here: the human needs to know a plugin update wiped a hand
# patch, and the agent needs to know its memory injection was just re-capped.
# Falls back to stderr if jq is unavailable, so a notice is never lost just
# because the JSON encoder is missing.
notify() { # message
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg m "$1" '{
      systemMessage: $m,
      hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: $m }
    }' 2>/dev/null || printf '%s\n' "$1" >&2
  else
    printf '%s\n' "$1" >&2
  fi
}

# Resolve the active remember install directory. Echoes "<version>|<path>", or
# nothing when the plugin is not installed at all (a machine without remember
# must stay silent, not be nagged every session).
resolve_install() {
  local manifest="$PLUGINS_DIR/installed_plugins.json" entry=""
  if [ -r "$manifest" ] && command -v jq >/dev/null 2>&1; then
    # The manifest keys plugins as "<name>@<marketplace>" and each value is an
    # array of install records (one per scope). Take the first record whose
    # installPath actually exists on disk.
    entry=$(jq -r '
      .plugins // {}
      | to_entries[]
      | select(.key | startswith("remember@"))
      | .value[]?
      | select(.installPath != null)
      | "\(.version // "unknown")|\(.installPath)"
    ' "$manifest" 2>/dev/null | while IFS='|' read -r v p; do
        [ -d "$p" ] && { printf '%s|%s\n' "$v" "$p"; break; }
      done)
    [ -n "$entry" ] && { printf '%s\n' "$entry"; return 0; }
  fi

  # Fallback: glob the version directories and take the highest by `sort -V`
  # (version-aware, so 0.10.0 correctly outranks 0.8.3 — a plain lexicographic
  # sort would get that backwards).
  local best="" d ver
  for d in "$PLUGINS_DIR"/cache/*/remember/*/; do
    [ -d "$d" ] || continue
    ver=$(basename "${d%/}")
    if [ -z "$best" ] || [ "$(printf '%s\n%s\n' "$best" "$ver" | sort -V | tail -1)" = "$ver" ]; then
      best="$ver"
    fi
  done
  [ -n "$best" ] || return 0
  for d in "$PLUGINS_DIR"/cache/*/remember/"$best"/; do
    [ -d "$d" ] && { printf '%s|%s\n' "$best" "${d%/}"; return 0; }
  done
}

# ── Locate the target ──────────────────────────────────────────────────────
VERSION="${REMEMBER_PLUGIN_VERSION:-unknown}"
if [ -n "${REMEMBER_HOOK_FILE:-}" ]; then
  TARGET="$REMEMBER_HOOK_FILE"
else
  resolved="$(resolve_install)"
  # Plugin not installed — nothing to guard, stay silent.
  [ -n "$resolved" ] || exit 0
  VERSION="${resolved%%|*}"
  TARGET="${resolved#*|}/scripts/session-start-hook.sh"
fi

# ── Missing or unreadable target: warn only if we were pointed at one ───────
# A resolved-but-absent hook script means the plugin's layout changed; say so
# rather than silently doing nothing. Never write.
if [ ! -f "$TARGET" ] || [ ! -r "$TARGET" ]; then
  notify "coderails: cannot read the remember plugin's session-start-hook.sh at ${TARGET} — the memory-injection byte cap could not be checked. Re-apply it by hand if the plugin layout changed."
  exit 0
fi

# ── Already capped? Then we are done — silently, on every normal session ────
if grep -q "$SENTINEL" "$TARGET" 2>/dev/null; then
  exit 0
fi

# ── The canonical patch text must be present in the repo ───────────────────
if [ ! -r "$VENDOR_BLOCK" ] || [ ! -r "$PATCHED_BLOCK" ]; then
  notify "coderails: the memory-injection byte cap is MISSING from the remember plugin (version ${VERSION}), and the canonical patch text was not found under ${PATCH_DIR}. Re-apply the cap by hand."
  exit 0
fi

# ── Shape check: the vendor block must occur EXACTLY ONCE ──────────────────
# Counting individual marker lines does NOT work here: the block's last line
# is a bare `fi`, which appears 8 times in the real session-start-hook.sh, so
# a per-line count would refuse to patch the very file this hook exists to
# patch. Match the block as a contiguous literal line SEQUENCE instead, and
# report how many times that whole sequence occurs. 0 means the vendor
# rewrote the block; >1 means ambiguous. Only exactly 1 is safe to replace.
n_block=$(awk '
  NR==FNR { pat[++np]=$0; next }
  { line[++nl]=$0 }
  END {
    n=0
    for (i=1; i<=nl-np+1; i++) {
      ok=1
      for (j=1; j<=np; j++) if (line[i+j-1] != pat[j]) { ok=0; break }
      if (ok) n++
    }
    print n
  }
' "$VENDOR_BLOCK" "$TARGET" 2>/dev/null || true)

if [ "${n_block:-0}" != "1" ]; then
  notify "coderails: the memory-injection byte cap is MISSING from the remember plugin (version ${VERSION}), but its session-start-hook.sh no longer has the shape the patch expects (found ${n_block:-0} matching blocks, expected exactly 1). Nothing was changed — re-apply the cap by hand at ${TARGET}."
  exit 0
fi

# ── Back up, then apply atomically ─────────────────────────────────────────
BACKUP="${TARGET}.coderails-bak-$(date +%Y%m%d%H%M%S)"
if ! cp -p "$TARGET" "$BACKUP" 2>/dev/null; then
  notify "coderails: the memory-injection byte cap is MISSING from the remember plugin (version ${VERSION}), but a backup of ${TARGET} could not be written, so nothing was changed. Re-apply the cap by hand."
  exit 0
fi

TMP_OUT="${TARGET}.coderails-tmp.$$"
# Three input files in order: search block, replace block, target. FNR==1
# marks each new file, so `fidx` tells the three passes apart without relying
# on FILENAME comparisons (which break when two args share a path).
if ! awk '
  FNR==1 { fidx++ }
  fidx==1 { pat[++np]=$0; next }
  fidx==2 { rep[++nr]=$0; next }
  { line[++nl]=$0 }
  END {
    i=1
    while (i <= nl) {
      ok=(i+np-1 <= nl)
      if (ok) for (j=1; j<=np; j++) if (line[i+j-1] != pat[j]) { ok=0; break }
      if (ok) {
        for (j=1; j<=nr; j++) print rep[j]
        i += np
      } else {
        print line[i]
        i++
      }
    }
  }
' "$VENDOR_BLOCK" "$PATCHED_BLOCK" "$TARGET" > "$TMP_OUT" 2>/dev/null; then
  rm -f "$TMP_OUT"
  notify "coderails: failed to rewrite ${TARGET} while re-applying the memory-injection byte cap. Nothing was changed (backup at ${BACKUP}). Re-apply by hand."
  exit 0
fi

# Sanity-gate the rewrite before it replaces anything: it must be non-empty and
# must actually contain the sentinel. A silently-empty awk output overwriting
# the plugin's hook would be far worse than the missing cap.
if [ ! -s "$TMP_OUT" ] || ! grep -q "$SENTINEL" "$TMP_OUT" 2>/dev/null; then
  rm -f "$TMP_OUT"
  notify "coderails: the re-applied memory-injection byte cap did not verify, so ${TARGET} was left unchanged (backup at ${BACKUP}). Re-apply by hand."
  exit 0
fi

# Preserve the original mode, then swap in place. `chmod --reference` is
# GNU-only and does NOT exist on macOS, so read the mode with stat: BSD
# `stat -f %Lp` first, GNU `stat -c %a` second. If both fail, fall back to
# chmod +x -- the file is a hook script and must stay executable.
mode=$(stat -f '%Lp' "$TARGET" 2>/dev/null || stat -c '%a' "$TARGET" 2>/dev/null || true)
if [ -n "$mode" ]; then
  chmod "$mode" "$TMP_OUT" 2>/dev/null || true
else
  chmod +x "$TMP_OUT" 2>/dev/null || true
fi
if ! mv -f "$TMP_OUT" "$TARGET" 2>/dev/null; then
  rm -f "$TMP_OUT"
  notify "coderails: could not replace ${TARGET} with the re-patched version (backup at ${BACKUP}). Re-apply the memory-injection byte cap by hand."
  exit 0
fi

notify "coderails: re-applied the memory-injection byte cap to the remember plugin (version ${VERSION}). The plugin was updated, which installed a fresh unpatched copy of session-start-hook.sh and wiped the hand-applied cap. Memory files are capped at 8000 bytes each again (override with ${SENTINEL}). Original saved to ${BACKUP}."
exit 0
