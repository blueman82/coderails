#!/bin/bash
# Unit test for agentic_loop_path.sh — path derivation + env override.
set -u
HELPER="$(cd "$(dirname "$0")/.." && pwd)/lib/agentic_loop_path.sh"
fails=0
check() { # desc, expected, actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected: %s\n      actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# 1. Default base is $HOME/.claude/agentic-loop; slug replaces / with -; session_id
#    passed explicitly as arg 2.
unset CLAUDE_AGENTIC_LOOP_DIR CLAUDE_CODE_SESSION_ID
check "default base + slug + explicit session_id" \
  "$HOME/.claude/agentic-loop/-Users-foo-bar/S1/progress.json" \
  "$(bash "$HELPER" /Users/foo/bar S1)"

# 2. Env override redirects the base (used by the guard's behavioural tests).
check "env override base" \
  "/tmp/al/-Users-foo-bar/S1/progress.json" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S1)"

# 3. No-arg form defaults cwd to the caller's PWD. PWD during a test run is
#    inside this real git checkout, so since agentic_loop_path.sh now keys off
#    git --git-common-dir when cwd is inside a repo, the expected slug is the
#    git-common-dir's slug, not a plain transform of $PWD (regression-recomputed
#    for the git-aware keying added by this PR — see checks 8-12 below for the
#    non-git cwd byte-for-byte regression guard instead).
PWD_GIT_COMMON_DIR=$(git -C "$PWD" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
if [ -n "$PWD_GIT_COMMON_DIR" ]; then
  PWD_EXPECTED_SLUG=$(printf '%s' "$PWD_GIT_COMMON_DIR" | sed 's#/#-#g')
else
  PWD_EXPECTED_SLUG=$(printf '%s' "$PWD" | sed 's#/#-#g')
fi
check "defaults cwd to PWD (git-keyed when PWD is inside a repo)" \
  "/tmp/al/$PWD_EXPECTED_SLUG/S1/progress.json" \
  "$(cd "$PWD" && CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "" S1)"

# 4. session_id defaults to $CLAUDE_CODE_SESSION_ID when arg 2 is omitted — this is
#    what lets the orchestrator's Bash calls resolve the path without ever typing
#    out its own session_id.
check "session_id defaults to CLAUDE_CODE_SESSION_ID env var" \
  "/tmp/al/-Users-foo-bar/S_ENV/progress.json" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al CLAUDE_CODE_SESSION_ID=S_ENV bash "$HELPER" /Users/foo/bar)"

# 5. Two different session ids for the same cwd resolve to two different paths —
#    the actual fix: concurrent sessions in one directory no longer collide.
p1=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S1)
p2=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S2)
if [ "$p1" != "$p2" ]; then printf 'ok   - %s\n' "distinct sessions -> distinct paths"
else printf 'FAIL - %s\n      both resolved to: %s\n' "distinct sessions -> distinct paths" "$p1"; fails=$((fails+1)); fi

# 6. Same cwd + same session_id resolves to the same path every time — a single
#    session recovers its own file across compaction/restart within one conversation.
p3=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S1)
check "same session_id -> stable path" "$p1" "$p3"

# 7. Two invocations that both have NO real session_id available (empty arg 2,
#    no CLAUDE_CODE_SESSION_ID env var) must NOT collide on a shared fixed
#    sentinel — each must get its own unique fallback so two genuinely different
#    sessions hitting this edge case never share one progress.json.
unset CLAUDE_CODE_SESSION_ID
q1=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar "")
q2=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar "")
if [ "$q1" != "$q2" ]; then printf 'ok   - %s\n' "missing session_id -> unique fallback, no collision"
else printf 'FAIL - %s\n      both resolved to: %s\n' "missing session_id -> unique fallback, no collision" "$q1"; fails=$((fails+1)); fi

# ── New cases (git-aware repo keying + session-id sanitisation) ─────────────
# Throwaway fixtures under a fresh tmpdir so these tests have no dependency on
# this repo's own worktree layout.
FIXTURE_TMP=$(cd "$(mktemp -d)" && pwd -P)
trap 'rm -rf "$FIXTURE_TMP"' EXIT

# 8. Worktree-hop invariance: primary clone + a `git worktree add` off it must
#    resolve to the SAME slug for the same session_id — this is the actual bug
#    (2026-07-06 mid-session EnterWorktree collision) this PR exists to fix.
PRIMARY="$FIXTURE_TMP/primary"
mkdir -p "$PRIMARY"
git -C "$PRIMARY" init -q
git -C "$PRIMARY" -c user.email=t@t.com -c user.name=t commit -q --allow-empty -m init
WT="$FIXTURE_TMP/primary-wt"
git -C "$PRIMARY" worktree add -q "$WT" -b wt-branch >/dev/null 2>&1
p_primary=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$PRIMARY" S1)
p_wt=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$WT" S1)
check "worktree-hop invariance: primary + worktree -> same path" "$p_primary" "$p_wt"

# 9. Non-git cwd regression guard: a plain non-git directory resolves to
#    EXACTLY today's sed 's#/#-#g' transform — zero behavior change for
#    non-git callers.
NONGIT="$FIXTURE_TMP/plain-dir"
mkdir -p "$NONGIT"
nongit_expected="/tmp/al/$(printf '%s' "$NONGIT" | sed 's#/#-#g')/S1/progress.json"
check "non-git cwd -> unchanged cwd-slug transform" \
  "$nongit_expected" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$NONGIT" S1)"

# 10. Two separate (unrelated) clones -> different slugs — confirms the fix
#     doesn't over-collapse unrelated repos onto one slug.
CLONE_A="$FIXTURE_TMP/clone-a"
CLONE_B="$FIXTURE_TMP/clone-b"
mkdir -p "$CLONE_A" "$CLONE_B"
git -C "$CLONE_A" init -q
git -C "$CLONE_A" -c user.email=t@t.com -c user.name=t commit -q --allow-empty -m init
git -C "$CLONE_B" init -q
git -C "$CLONE_B" -c user.email=t@t.com -c user.name=t commit -q --allow-empty -m init
p_a=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$CLONE_A" S1)
p_b=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$CLONE_B" S1)
if [ "$p_a" != "$p_b" ]; then printf 'ok   - %s\n' "two separate clones -> different slugs"
else printf 'FAIL - %s\n      both resolved to: %s\n' "two separate clones -> different slugs" "$p_a"; fails=$((fails+1)); fi

# 11. git-broken -> cwd fallback: a fake `git` that always fails is placed
#     earlier on PATH (deterministic, no real corrupt-.git fixture needed) so
#     the helper's `git -C ... rev-parse` call fails while every other tool the
#     helper/harness needs (bash, sed, tr, printf, ...) stays reachable — this
#     isolates "git itself fails" from "PATH has nothing," proving fallback
#     triggers on ANY git failure, not a specific exit code.
FAKE_GIT_DIR="$FIXTURE_TMP/fake-git-bin"
mkdir -p "$FAKE_GIT_DIR"
printf '#!/bin/bash\nexit 1\n' > "$FAKE_GIT_DIR/git"
chmod +x "$FAKE_GIT_DIR/git"
broken_expected="/tmp/al/$(printf '%s' "$CLONE_A" | sed 's#/#-#g')/S1/progress.json"
check "git-broken (git always fails) -> cwd-slug fallback" \
  "$broken_expected" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al PATH="$FAKE_GIT_DIR:$PATH" bash "$HELPER" "$CLONE_A" S1)"

# 12. Submodule pin-or-document: record actual --git-common-dir behavior for a
#     cwd inside a submodule's own checkout (submodules have their own .git
#     FILE pointing into the superproject's .git/modules/<name>, so behavior
#     may differ from a plain nested repo). This pins whatever is actually
#     observed rather than asserting a predetermined "correct" answer.
SUPER="$FIXTURE_TMP/super"
SUBLIB="$FIXTURE_TMP/sublib"
mkdir -p "$SUPER" "$SUBLIB"
git -C "$SUBLIB" init -q
git -C "$SUBLIB" -c user.email=t@t.com -c user.name=t commit -q --allow-empty -m init
git -C "$SUPER" init -q
git -C "$SUPER" -c user.email=t@t.com -c user.name=t -c protocol.file.allow=always \
  submodule add -q "$SUBLIB" sub >/dev/null 2>&1
git -C "$SUPER" -c user.email=t@t.com -c user.name=t commit -q -m "add submodule" >/dev/null 2>&1
if [ -d "$SUPER/sub" ] && [ -e "$SUPER/sub/.git" ]; then
  sub_common_dir=$(git -C "$SUPER/sub" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  p_sub=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$SUPER/sub" S1)
  case "$sub_common_dir" in
    "$SUPER"/.git/modules/*)
      printf 'ok   - %s (KNOWN: submodule --git-common-dir resolves into superproject .git/modules/<name>: %s)\n' \
        "submodule cwd -> pinned observed git-common-dir behavior" "$sub_common_dir"
      ;;
    *)
      printf 'ok   - %s (KNOWN: submodule --git-common-dir observed as: %s)\n' \
        "submodule cwd -> pinned observed git-common-dir behavior" "$sub_common_dir"
      ;;
  esac
  # Whatever git-common-dir resolves to, the helper's slug must match its
  # deterministic transform (or the cwd fallback if git-common-dir was empty).
  if [ -n "$sub_common_dir" ]; then
    sub_expected="/tmp/al/$(printf '%s' "$sub_common_dir" | sed 's#/#-#g')/S1/progress.json"
  else
    sub_expected="/tmp/al/$(printf '%s' "$SUPER/sub" | sed 's#/#-#g')/S1/progress.json"
  fi
  check "submodule cwd -> helper matches observed git-common-dir transform" "$sub_expected" "$p_sub"
else
  printf 'ok   - %s (SKIPPED: submodule fixture setup was not viable in this environment)\n' "submodule cwd -> pinned observed git-common-dir behavior"
fi

# 13. Sanitisation: session_id containing '/' is replaced (not discarded) so
#     the resulting path has no extra nested directory segment.
p_slash=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$NONGIT" "S1/evil")
slash_segs=$(printf '%s' "$p_slash" | awk -F/ '{print NF}')
expected_segs=$(printf '/tmp/al/x/y/progress.json' | awk -F/ '{print NF}')
if [ "$slash_segs" = "$expected_segs" ] && ! printf '%s' "$p_slash" | grep -q '/evil/progress.json$'; then
  printf 'ok   - %s\n' "session_id with / -> sanitised in place, no path traversal"
else
  printf 'FAIL - %s\n      actual: %s\n' "session_id with / -> sanitised in place, no path traversal" "$p_slash"; fails=$((fails+1))
fi

# 14. Sanitisation: session_id containing '..' has the '..' collapsed/removed.
p_dotdot=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$NONGIT" "../../S1")
if ! printf '%s' "$p_dotdot" | grep -qE '(^|/)\.\.(/|$)'; then
  printf 'ok   - %s\n' "session_id with .. -> collapsed, no path traversal"
else
  printf 'FAIL - %s\n      actual: %s\n' "session_id with .. -> collapsed, no path traversal" "$p_dotdot"; fails=$((fails+1))
fi

# 15. Garbage-git-output-on-exit-0 -> cwd fallback. Real trigger: git <2.31
#     doesn't recognise --path-format and echoes it back verbatim alongside a
#     RELATIVE .git path, exiting 0 — every repo on an old-git host would
#     collapse onto one garbage slug if the helper trusted any non-empty
#     stdout. A fake `git` here reproduces that shape (relative, non-absolute
#     output, exit 0) to prove the helper validates the output is an absolute
#     path before using it, not just that git exited zero.
FAKE_GIT_GARBAGE_DIR="$FIXTURE_TMP/fake-git-garbage-bin"
mkdir -p "$FAKE_GIT_GARBAGE_DIR"
printf '#!/bin/bash\necho "--path-format=absolute .git"\nexit 0\n' > "$FAKE_GIT_GARBAGE_DIR/git"
chmod +x "$FAKE_GIT_GARBAGE_DIR/git"
garbage_expected="/tmp/al/$(printf '%s' "$CLONE_A" | sed 's#/#-#g')/S1/progress.json"
check "git prints non-absolute garbage on exit 0 -> cwd-slug fallback (not garbage slug)" \
  "$garbage_expected" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al PATH="$FAKE_GIT_GARBAGE_DIR:$PATH" bash "$HELPER" "$CLONE_A" S1)"

# 16. cwd-with-spaces pin: today's behavior already handles a cwd containing
#     spaces correctly (quoting throughout); lock it so a future change can't
#     silently regress word-splitting on an unquoted expansion.
SPACEY="$FIXTURE_TMP/has spaces/dir"
mkdir -p "$SPACEY"
spacey_expected="/tmp/al/$(printf '%s' "$SPACEY" | sed 's#/#-#g')/S1/progress.json"
check "cwd containing spaces -> resolves correctly (pinned)" \
  "$spacey_expected" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$SPACEY" S1)"

# 17. Sanitisation collision, documented/pinned: "foo/bar" and "foo_bar" both
#     sanitise to the same value (accepted tradeoff — session_id is
#     harness-owned, not attacker-controlled, and replacement was chosen over
#     fresh-fallback specifically to avoid orphaning a malformed id's real
#     session; a residual collision between two DIFFERENT malformed/plain ids
#     is a known, accepted cost of that choice, not a regression).
p_collide_slash=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$NONGIT" "foo/bar")
p_collide_plain=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "$NONGIT" "foo_bar")
if [ "$p_collide_slash" = "$p_collide_plain" ]; then
  printf 'ok   - %s\n' "sanitisation collision foo/bar == foo_bar (KNOWN/ACCEPTED, not a regression)"
else
  printf 'FAIL - %s\n      foo/bar -> %s\n      foo_bar -> %s\n' \
    "sanitisation collision foo/bar == foo_bar (expected collision, behavior changed)" \
    "$p_collide_slash" "$p_collide_plain"
  fails=$((fails+1))
fi

# ── Session-id fallback probing (2026-07-08 split-slug incident) ────────────
# When no progress.json exists at the CANONICAL slug path, the helper probes
# <base>/*/<session_id>/progress.json for state a PRIOR helper version (or a
# mid-loop cwd drift) parked under a different slug. session_id is unique per
# session, so it is a sufficient key on its own. These tests use a dedicated
# base per case so unrelated slugs from earlier cases can't leak in.

# 18. Canonical-exists wins: when a progress.json exists at BOTH the canonical
#     (git-common-dir) slug AND a stale legacy (raw-cwd) slug, the canonical one
#     is printed — the probe must never override an existing canonical file.
BASE18=$(cd "$(mktemp -d)" && pwd -P)
canon18=$(CLAUDE_AGENTIC_LOOP_DIR="$BASE18" bash "$HELPER" "$PRIMARY" S18)
legacy18_slug=$(printf '%s' "$PRIMARY" | sed 's#/#-#g')
legacy18="$BASE18/$legacy18_slug/S18/progress.json"
mkdir -p "$(dirname "$canon18")" "$(dirname "$legacy18")"
printf '{"canonical":true}\n' > "$canon18"
printf '{"legacy":true}\n' > "$legacy18"
check "canonical-exists wins even when a legacy-slug file also exists" \
  "$canon18" \
  "$(CLAUDE_AGENTIC_LOOP_DIR="$BASE18" bash "$HELPER" "$PRIMARY" S18)"

# 19. The incident: state was registered under a LEGACY raw-cwd slug, but the
#     current helper resolves the canonical git-common-dir slug (which has no
#     file). The probe must find the legacy file by session_id and print it,
#     so the Stop guards see the registered loop instead of nudging a phantom.
BASE19=$(cd "$(mktemp -d)" && pwd -P)
legacy19_slug=$(printf '%s' "$PRIMARY" | sed 's#/#-#g')
legacy19="$BASE19/$legacy19_slug/S19/progress.json"
mkdir -p "$(dirname "$legacy19")"
printf '{"legacy":true}\n' > "$legacy19"
check "legacy-slug state found when canonical slug has no file (the incident)" \
  "$legacy19" \
  "$(CLAUDE_AGENTIC_LOOP_DIR="$BASE19" bash "$HELPER" "$PRIMARY" S19)"

# 20. No state anywhere -> canonical printed, so a fresh loop registers at the
#     canonical path (probe must fall through cleanly on an empty glob).
BASE20=$(cd "$(mktemp -d)" && pwd -P)
canon20=$(CLAUDE_AGENTIC_LOOP_DIR="$BASE20" bash "$HELPER" "$PRIMARY" S20)
check "no state anywhere -> canonical printed (fresh registration)" \
  "$canon20" \
  "$(CLAUDE_AGENTIC_LOOP_DIR="$BASE20" bash "$HELPER" "$PRIMARY" S20)"

# 21. Symlinked duplicates of ONE real state dir (the orchestrator's live
#     workaround symlinks the same progress.json under 3 slugs). The probe must
#     dedupe by physical identity, not crash, and print a path that references
#     the one REAL state file.
BASE21=$(cd "$(mktemp -d)" && pwd -P)
real21_slug="real-slug"
real21_dir="$BASE21/$real21_slug/S21"
mkdir -p "$real21_dir"
printf '{"real":true}\n' > "$real21_dir/progress.json"
# Two extra slugs whose <session_id> dir is a symlink to the real one.
for alias in alias-a alias-b; do
  mkdir -p "$BASE21/$alias"
  ln -s "$real21_dir" "$BASE21/$alias/S21"
done
out21=$(CLAUDE_AGENTIC_LOOP_DIR="$BASE21" bash "$HELPER" "$PRIMARY" S21)
# Exactly one path printed, and it must resolve (realpath) to the real file.
lines21=$(printf '%s\n' "$out21" | grep -c .)
real21_canon=$(cd "$(dirname "$real21_dir/progress.json")" && pwd -P)/progress.json
out21_canon=$(cd "$(dirname "$out21")" 2>/dev/null && pwd -P)/progress.json
if [ "$lines21" = "1" ] && [ "$out21_canon" = "$real21_canon" ]; then
  printf 'ok   - %s\n' "symlinked duplicates -> one path, references the real state"
else
  printf 'FAIL - %s\n      printed: %s (lines=%s, real=%s)\n' \
    "symlinked duplicates -> one path, references the real state" "$out21" "$lines21" "$real21_canon"
  fails=$((fails+1))
fi

# 22. Generated fallback session ids (unknown-<pid>-<ns>) still resolve to the
#     canonical path. Two such invocations must NOT probe each other's dirs into
#     a match (each fallback id is unique), so each prints its own canonical
#     path with a fresh (non-existent) state file -> plain canonical, no probe hit.
BASE22=$(cd "$(mktemp -d)" && pwd -P)
unset CLAUDE_CODE_SESSION_ID
u1=$(CLAUDE_AGENTIC_LOOP_DIR="$BASE22" bash "$HELPER" "$PRIMARY" "")
u2=$(CLAUDE_AGENTIC_LOOP_DIR="$BASE22" bash "$HELPER" "$PRIMARY" "")
# Both must be under the canonical git-common-dir slug for PRIMARY, and distinct.
canon22_slug=$(printf '%s' "$(git -C "$PRIMARY" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" | sed 's#/#-#g')
if printf '%s' "$u1" | grep -q "^$BASE22/$canon22_slug/unknown-.*/progress.json$" \
   && printf '%s' "$u2" | grep -q "^$BASE22/$canon22_slug/unknown-.*/progress.json$" \
   && [ "$u1" != "$u2" ]; then
  printf 'ok   - %s\n' "generated fallback session ids -> canonical, no cross-probe collision"
else
  printf 'FAIL - %s\n      u1: %s\n      u2: %s\n' \
    "generated fallback session ids -> canonical, no cross-probe collision" "$u1" "$u2"
  fails=$((fails+1))
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
