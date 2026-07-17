#!/bin/bash
# Behavioural test for scripts/push.sh staging behaviour, plus (as of the
# push-status-handling fix) the push-success/push-failure gate itself. Builds
# a real bare origin + clone fixture per case (matching git-common.test.sh's
# convention) and runs push.sh as a real subprocess (`bash "$PUSH_SH"`, not
# `source`d — push.sh resolves its sibling lib via `$(dirname "$0")`, which
# only points at push.sh's own directory when it's actually executed, not
# sourced into a caller with a different $0). `git add -A` was replaced with
# `git add -u` (tracked-only staging) plus an untracked-file warning.
#
# The origin remote is registered as a fake https://github.com/... URL (so
# require::repo() passes) but rewritten via `url.<path>.insteadOf` git config
# to actually redirect to a real local bare repo — so `require::repo()` sees
# a github.com-shaped remote AND the underlying `git push` genuinely talks to
# a real, reachable git repository and can genuinely succeed. A `gh` stub is
# placed first on PATH so the PR-create/PR-comment steps after a successful
# push never touch the real network.
set -u
export GIT_TERMINAL_PROMPT=0
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PUSH_SH="$REPO_ROOT/scripts/push.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── gh stub: PR list is always empty (no existing PR), PR create returns a
# fake URL. Never touches the network. Placed first on PATH by callers via
# PATH="$GH_STUB_DIR:$PATH".
GH_STUB_DIR="$TMP/ghstub"
mkdir -p "$GH_STUB_DIR"
cat > "$GH_STUB_DIR/gh" <<'GHSTUB'
#!/bin/bash
case "$*" in
  "pr list"*) echo "[]" ;;
  "pr create"*) echo "https://github.com/testowner/testrepo-fixture/pull/1" ;;
  "pr comment"*) exit 0 ;;
  "pr view"*) echo "" ;;
  *) exit 0 ;;
esac
GHSTUB
chmod +x "$GH_STUB_DIR/gh"

# new_fixture <name> → sets up $TMP/<name>/origin.git (bare) + $TMP/<name>/repo
# (clone, on a feature branch, remote-HEAD set to main) and echoes the repo path.
# push.sh's require::repo() gates on repo() matching a github.com URL, so
# `origin` is registered as a fake https://github.com/... URL — but a
# `url.<local-path>.insteadOf` git config rewrite makes that fake URL actually
# redirect to the real local bare repo, so the subsequent `git push -u origin
# "$br"` inside push::main is a genuine, reachable push that can genuinely
# succeed (not merely fail-fast against an unreachable host). The `main`
# branch is pushed for real too, so `origin/main` (used by ahead()) is a real
# remote-tracking ref.
new_fixture() {
  local name="$1" origin repo
  origin="$TMP/$name/origin.git"; repo="$TMP/$name/repo"
  mkdir -p "$TMP/$name"
  git init -q --bare "$origin"
  git clone -q "$origin" "$repo" 2>/dev/null
  git -C "$repo" config user.email t@t.t; git -C "$repo" config user.name t
  echo "base" > "$repo/base.txt"
  git -C "$repo" add base.txt
  git -C "$repo" commit -q -m init
  git -C "$repo" branch -M main
  git -C "$repo" push -q -u origin main
  git -C "$repo" remote set-head origin main
  git -C "$repo" remote set-url origin "https://github.com/testowner/testrepo-fixture.git"
  git -C "$repo" config "url.${origin}.insteadOf" "https://github.com/testowner/testrepo-fixture.git"
  git -C "$repo" checkout -q -b feature
  echo "$repo"
}

# run_push <repo> [args...] → runs push.sh with the gh stub on PATH, echoing
# the repo's own path first-on-PATH is NOT needed here (push.sh is invoked by
# absolute path). Sets LAST_RC as a side effect.
run_push() {
  local repo="$1"; shift
  local out
  out=$( (cd "$repo" && PATH="$GH_STUB_DIR:$PATH" bash "$PUSH_SH" "$@") 2>&1 )
  LAST_RC=$?
  LAST_OUT="$out"
}

# ─── TRACKED-ONLY: modified tracked file, no untracked files ────────────────
# No `??` lines exist here at all, which is the common case and the one that
# previously crashed push.sh (a bare `grep '^??'` with zero matches exits 1,
# and under `set -euo pipefail` that aborted the whole script before the
# commit ever ran) — assert on exit code and HEAD advancing, not just content,
# so a future regression that skips the commit can't pass silently. The push
# now genuinely succeeds against the real local bare origin, so a 0 exit here
# is a true positive, not a swallowed failure.
R=$(new_fixture tracked_only)
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
echo "changed" > "$R/base.txt"
run_push "$R"
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
staged=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "TRACKED-ONLY: does not crash (exit 0)" "0" "$LAST_RC"
check "TRACKED-ONLY: HEAD advances (a new commit was made)" "1" "$([ "$BEFORE_HEAD" != "$AFTER_HEAD" ] && echo 1 || echo 0)"
check "TRACKED-ONLY: modification staged and committed" "base.txt" "$staged"
check "TRACKED-ONLY: no untracked-file warning printed" "0" "$(printf '%s' "$LAST_OUT" | grep -c '^! Untracked')"
check "TRACKED-ONLY: push actually landed (origin/feature == HEAD)" "$AFTER_HEAD" "$(git -C "$R" rev-parse origin/feature)"

# ─── UNTRACKED-PRESENT: modified tracked file AND an untracked file ─────────
R=$(new_fixture untracked_present)
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
echo "changed" > "$R/base.txt"
echo "new" > "$R/newfile.txt"
run_push "$R"
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "UNTRACKED-PRESENT: does not crash (exit 0)" "0" "$LAST_RC"
check "UNTRACKED-PRESENT: HEAD advances (a new commit was made)" "1" "$([ "$BEFORE_HEAD" != "$AFTER_HEAD" ] && echo 1 || echo 0)"
check "UNTRACKED-PRESENT: modification staged and committed" "base.txt" "$committed_files"
check "UNTRACKED-PRESENT: untracked file NOT staged" "0" "$(printf '%s' "$committed_files" | grep -c newfile.txt)"
check "UNTRACKED-PRESENT: warning printed" "1" "$(printf '%s' "$LAST_OUT" | grep -c '^! Untracked')"
check "UNTRACKED-PRESENT: warning names the file" "1" "$(printf '%s' "$LAST_OUT" | grep -c 'newfile.txt')"
check "UNTRACKED-PRESENT: warning mentions git add" "1" "$(printf '%s' "$LAST_OUT" | grep -c -i 'git add')"

# ─── UNTRACKED-ONLY: no tracked changes at all, only a new untracked file ───
R=$(new_fixture untracked_only)
echo "new" > "$R/newfile.txt"
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
run_push "$R"
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
check "UNTRACKED-ONLY: does not crash (exit 0)" "0" "$LAST_RC"
check "UNTRACKED-ONLY: no new commit created (nothing staged)" "$BEFORE_HEAD" "$AFTER_HEAD"
check "UNTRACKED-ONLY: warning still printed" "1" "$(printf '%s' "$LAST_OUT" | grep -c '^! Untracked')"

# ─── MULTIPLE UNTRACKED: warning lists all untracked files ──────────────────
R=$(new_fixture multi_untracked)
echo "changed" > "$R/base.txt"
echo "a" > "$R/alpha.txt"
echo "b" > "$R/beta.txt"
run_push "$R"
check "MULTIPLE UNTRACKED: does not crash (exit 0)" "0" "$LAST_RC"
check "MULTIPLE UNTRACKED: alpha.txt named in warning" "1" "$(printf '%s' "$LAST_OUT" | grep -c 'alpha.txt')"
check "MULTIPLE UNTRACKED: beta.txt named in warning" "1" "$(printf '%s' "$LAST_OUT" | grep -c 'beta.txt')"

# ─── PRE-STAGED NEW FILE: a new file already `git add`ed before push.sh runs ─
# `git add -u` only touches already-tracked paths; a pre-staged new file has
# no prior tracked history, but it IS already in the index (mode A), so `git
# add -u` must leave it staged rather than unstaging it — the previous
# `git add -A` behaviour and the new `git add -u` behaviour agree here for
# already-staged content, so this proves the tracked-only migration didn't
# regress the pre-staged case.
R=$(new_fixture prestaged_new)
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
echo "brand new" > "$R/prestaged.txt"
git -C "$R" add prestaged.txt
run_push "$R"
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "PRE-STAGED NEW FILE: does not crash (exit 0)" "0" "$LAST_RC"
check "PRE-STAGED NEW FILE: HEAD advances (a new commit was made)" "1" "$([ "$BEFORE_HEAD" != "$AFTER_HEAD" ] && echo 1 || echo 0)"
check "PRE-STAGED NEW FILE: the pre-staged file is committed" "1" "$(printf '%s' "$committed_files" | grep -c prestaged.txt)"
check "PRE-STAGED NEW FILE: no untracked-file warning printed" "0" "$(printf '%s' "$LAST_OUT" | grep -c '^! Untracked')"

# ─── DELETED TRACKED FILE: a tracked file removed from disk before push.sh runs ─
# `git add -u` (unlike a bare `git add -A .` restricted to modified files)
# must also stage deletions of already-tracked paths — this is the case
# that would silently leave a deleted file "modified but uncommitted" if a
# future edit narrowed the staging call to skip removals.
R=$(new_fixture deleted_tracked)
echo "to be deleted" > "$R/todelete.txt"
git -C "$R" add todelete.txt
git -C "$R" commit -q -m "add todelete.txt"
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
rm "$R/todelete.txt"
run_push "$R"
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "DELETED TRACKED FILE: does not crash (exit 0)" "0" "$LAST_RC"
check "DELETED TRACKED FILE: HEAD advances (a new commit was made)" "1" "$([ "$BEFORE_HEAD" != "$AFTER_HEAD" ] && echo 1 || echo 0)"
check "DELETED TRACKED FILE: the deletion is committed" "1" "$(printf '%s' "$committed_files" | grep -c todelete.txt)"
check "DELETED TRACKED FILE: file absent from the resulting tree" "0" "$(git -C "$R" show HEAD:todelete.txt 2>/dev/null | wc -l | tr -d ' ')"
check "DELETED TRACKED FILE: no untracked-file warning printed" "0" "$(printf '%s' "$LAST_OUT" | grep -c '^! Untracked')"

# ─── NEGATIVE CONTROL: script no longer contains git add -A ─────────────────
check "NEGATIVE CONTROL: push.sh contains zero 'git add -A'" "0" "$(grep -c 'git add -A' "$PUSH_SH")"
check "NEGATIVE CONTROL: push.sh contains 'git add -u'" "1" "$(grep -c 'git add -u' "$PUSH_SH" | head -1)"

# ─── --force-with-lease flag: opt-in gated push ──────────────────────────────
# The fixture's origin is now a genuinely reachable local bare repo, so these
# checks assert on the git command push.sh SELECTS based on the flag, via a
# stub `git` shim placed first on PATH that records its own argv and then
# delegates to the real git — this isolates "did push.sh choose
# --force-with-lease" from the push's actual success/failure.
STUB_BIN="$TMP/stubbin"
mkdir -p "$STUB_BIN"
# Resolved OUTSIDE the stub (before $STUB_BIN is on PATH) — resolving it
# INSIDE the stub via `command -v git` would find the stub itself once
# $STUB_BIN is prepended to PATH, causing infinite self-recursion on every
# non-push git call (status, rev-list, log, ...) that push.sh's earlier
# commit/status steps depend on.
REAL_GIT_PATH=$(command -v git)
cat > "$STUB_BIN/git" <<EOF
#!/bin/bash
# Records argv for any \`git push\` call, then delegates to the real git so
# the push actually happens against the fixture's real local bare origin.
if [[ "\$1" == "push" ]]; then
  echo "\$*" >> "\$GIT_PUSH_LOG"
fi
exec "$REAL_GIT_PATH" "\$@"
EOF
chmod +x "$STUB_BIN/git"

R=$(new_fixture force_with_lease_flag)
echo "changed" > "$R/base.txt"
GIT_PUSH_LOG="$TMP/force_with_lease_flag/push.log"
: > "$GIT_PUSH_LOG"
( cd "$R" && PATH="$STUB_BIN:$GH_STUB_DIR:$PATH" GIT_PUSH_LOG="$GIT_PUSH_LOG" bash "$PUSH_SH" --force-with-lease "msg" ) >/dev/null 2>&1
logged=$(cat "$GIT_PUSH_LOG" 2>/dev/null || true)
check "FLAG: git push invoked with --force-with-lease" "1" "$(printf '%s' "$logged" | grep -c -- '--force-with-lease')"

R=$(new_fixture no_flag)
echo "changed" > "$R/base.txt"
GIT_PUSH_LOG="$TMP/no_flag/push.log"
: > "$GIT_PUSH_LOG"
( cd "$R" && PATH="$STUB_BIN:$GH_STUB_DIR:$PATH" GIT_PUSH_LOG="$GIT_PUSH_LOG" bash "$PUSH_SH" "msg" ) >/dev/null 2>&1
logged=$(cat "$GIT_PUSH_LOG" 2>/dev/null || true)
check "NO FLAG: git push invoked WITHOUT --force-with-lease" "0" "$(printf '%s' "$logged" | grep -c -- '--force-with-lease')"

# ══════════════════════════════════════════════════════════════════════════
# ─── REJECTED PUSH: real non-fast-forward rejection must NOT report success ─
# ══════════════════════════════════════════════════════════════════════════
# Simulates a second clone pushing to the same feature branch first, so our
# clone's push is a genuine non-fast-forward rejection from a real git
# server (the fixture's bare repo) — not a stubbed/simulated failure. Before
# the fix, push.sh piped `git push` through `grep -v '^remote:' || true`,
# which discarded git's real exit status and unconditionally printed
# "Pushed". After the fix, a rejected push must exit non-zero, must NOT
# print "Pushed", and the real git error text must reach the user.
R=$(new_fixture rejected_push)
OTHER="$TMP/rejected_push/other"
ORIGIN_BARE="$TMP/rejected_push/origin.git"
git clone -q "$ORIGIN_BARE" "$OTHER" 2>/dev/null
git -C "$OTHER" config user.email o@o.o; git -C "$OTHER" config user.name other
git -C "$OTHER" checkout -q -b feature
echo "other change" > "$OTHER/other.txt"
git -C "$OTHER" add other.txt
git -C "$OTHER" commit -q -m "other commit"
git -C "$OTHER" push -q -u origin feature

BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
echo "changed" > "$R/base.txt"
run_push "$R"
check "REJECTED PUSH: exits non-zero" "1" "$([ "$LAST_RC" -ne 0 ] && echo 1 || echo 0)"
check "REJECTED PUSH: does NOT print 'Pushed'" "0" "$(printf '%s' "$LAST_OUT" | grep -c 'Pushed')"
check "REJECTED PUSH: real rejection text reaches the user" "1" "$(printf '%s' "$LAST_OUT" | grep -q 'rejected' && echo 1 || echo 0)"
check "REJECTED PUSH: a failure is reported" "1" "$(printf '%s' "$LAST_OUT" | grep -q -i 'fail\|error\|✗' && echo 1 || echo 0)"
check "REJECTED PUSH: local commit still happened (commit step is independent of push outcome)" "1" "$([ "$BEFORE_HEAD" != "$(git -C "$R" rev-parse HEAD)" ] && echo 1 || echo 0)"

# ══════════════════════════════════════════════════════════════════════════
# ─── SERVER-REASON: a remote:-only rejection must still explain WHY ─────────
# ══════════════════════════════════════════════════════════════════════════
# How a GitHub ruleset actually rejects: the server's reason (GH006, the rule
# name) arrives ONLY on `remote:`-prefixed lines. Git's own summary line says
# a rejection happened but never why. The display filter strips `remote:` to
# de-noise a SUCCESSFUL push, so it must not run on the failure path — else
# `err "see error above"` points at output with the only useful line removed.
# A pre-receive hook is the faithful local stand-in for a server-side rule.
R=$(new_fixture serverreason)
cat > "$TMP/serverreason/origin.git/hooks/pre-receive" <<'HOOK'
#!/bin/bash
echo "error: GH006: Protected branch update failed for refs/heads/feature." >&2
echo "error: Changes must be made through a pull request." >&2
exit 1
HOOK
chmod +x "$TMP/serverreason/origin.git/hooks/pre-receive"
echo "change" >> "$R/base.txt"
run_push "$R" "server reason msg"

check "SERVER-REASON: exits non-zero" "1" "$([ "$LAST_RC" -ne 0 ] && echo 1 || echo 0)"
check "SERVER-REASON: does NOT print 'Pushed'" "0" "$(printf '%s' "$LAST_OUT" | grep -c 'Pushed')"
# The point of the whole block: the server's actual reason must survive.
check "SERVER-REASON: GH006 rule id reaches the user" "1" "$(printf '%s' "$LAST_OUT" | grep -q 'GH006' && echo 1 || echo 0)"
check "SERVER-REASON: actionable reason text reaches the user" "1" "$(printf '%s' "$LAST_OUT" | grep -q 'through a pull request' && echo 1 || echo 0)"

# ══════════════════════════════════════════════════════════════════════════
# ─── STALE-LEASE REJECTION: --force-with-lease's own rejection reason ───────
# ══════════════════════════════════════════════════════════════════════════
# The plain non-fast-forward case above exercises the default push path's
# capture/err logic; this exercises the SAME logic on the --force-with-lease
# branch with lease's own distinct rejection reason ("stale info"), so the
# force-with-lease code path isn't just covered by code-reading symmetry.
# Builds a fixture whose local origin/feature tracking ref goes stale: a
# second clone pushes new history to feature on the real remote WITHOUT our
# fixture's repo ever fetching, so our repo's local record of origin/feature
# no longer matches the actual remote tip — the exact condition
# --force-with-lease is designed to detect and refuse to clobber.
R=$(new_fixture stale_lease)
git -C "$R" checkout -q feature
echo "v1" > "$R/base.txt"
git -C "$R" add base.txt
git -C "$R" commit -q -m "v1"
git -C "$R" push -q -u origin feature
OTHER2="$TMP/stale_lease/other2"
git clone -q "$TMP/stale_lease/origin.git" "$OTHER2" 2>/dev/null
git -C "$OTHER2" config user.email o2@o2.o; git -C "$OTHER2" config user.name other2
git -C "$OTHER2" checkout -q -b feature origin/feature
echo "v2-from-other" > "$OTHER2/base.txt"
git -C "$OTHER2" add base.txt
git -C "$OTHER2" commit -q -m "v2 other"
git -C "$OTHER2" push -q origin feature
# $R's local origin/feature ref is now stale (still records v1; the real
# remote tip is v2-from-other) — force-with-lease must refuse this.
echo "v3-local-diverged" > "$R/base.txt"
git -C "$R" add base.txt
git -C "$R" commit -q -m "v3 local diverged"
run_push "$R" --force-with-lease "msg"
check "STALE-LEASE: exits non-zero" "1" "$([ "$LAST_RC" -ne 0 ] && echo 1 || echo 0)"
check "STALE-LEASE: does NOT print 'Pushed'" "0" "$(printf '%s' "$LAST_OUT" | grep -c 'Pushed')"
check "STALE-LEASE: real 'stale info' rejection text reaches the user" "1" "$(printf '%s' "$LAST_OUT" | grep -q -i 'stale' && echo 1 || echo 0)"

# ══════════════════════════════════════════════════════════════════════════
# ─── ALL-REMOTE-LINES SUCCESS: false-negative guard ─────────────────────────
# ══════════════════════════════════════════════════════════════════════════
# A successful push whose entire stderr/stdout output consists of `remote:`
# lines must still be treated as success and still print "Pushed". This
# guards against a fix that determines success/failure by checking whether
# `grep -v '^remote:'` produced any output — under `set -o pipefail`, a
# real push whose only lines start with `remote:` makes that grep exit 1
# (nothing matched), which must NOT be mistaken for a git-push failure.
# A `git` stub that delegates the real push, then rewrites the *displayed*
# output only, is used so status capture is independent of display filtering.
STUB_BIN2="$TMP/stubbin2"
mkdir -p "$STUB_BIN2"
cat > "$STUB_BIN2/git" <<EOF
#!/bin/bash
if [[ "\$1" == "push" ]]; then
  shift
  "$REAL_GIT_PATH" push "\$@" >/tmp/.push_out_\$\$ 2>&1
  rc=\$?
  printf 'remote: %s\n' "ok"
  printf 'remote: %s\n' "more remote output"
  rm -f /tmp/.push_out_\$\$
  exit \$rc
fi
exec "$REAL_GIT_PATH" "\$@"
EOF
chmod +x "$STUB_BIN2/git"

R=$(new_fixture all_remote_lines)
echo "changed" > "$R/base.txt"
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
OUT=$( (cd "$R" && PATH="$STUB_BIN2:$GH_STUB_DIR:$PATH" bash "$PUSH_SH") 2>&1 )
RC=$?
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
check "ALL-REMOTE-LINES: still exits 0 (false-negative guard)" "0" "$RC"
check "ALL-REMOTE-LINES: still prints 'Pushed'" "1" "$(printf '%s' "$OUT" | grep -c 'Pushed')"
check "ALL-REMOTE-LINES: push actually landed (origin/feature == HEAD)" "$AFTER_HEAD" "$(git -C "$R" rev-parse origin/feature)"

# ══════════════════════════════════════════════════════════════════════════
# ─── POSITIVE VERIFICATION: origin/$br must equal local HEAD after success ──
# ══════════════════════════════════════════════════════════════════════════
# On an ordinary successful push (no stubs at all — the real git binary),
# origin/<branch> must equal local HEAD by the time push.sh prints "Pushed".
R=$(new_fixture verify_landed)
echo "changed" > "$R/base.txt"
run_push "$R"
check "VERIFY-LANDED: exits 0" "0" "$LAST_RC"
check "VERIFY-LANDED: prints 'Pushed'" "1" "$(printf '%s' "$LAST_OUT" | grep -c 'Pushed')"
check "VERIFY-LANDED: origin/feature == local HEAD" "$(git -C "$R" rev-parse HEAD)" "$(git -C "$R" rev-parse origin/feature)"

# ══════════════════════════════════════════════════════════════════════════
# ─── DECEPTIVE-SUCCESS GUARD: push_rc==0 but origin/$br never moved ─────────
# ══════════════════════════════════════════════════════════════════════════
# Drives the rev-parse-mismatch `err` branch directly: this state cannot arise
# from a real, unmodified git push (a real push that reports success DOES
# move the remote-tracking ref), so it is only reachable via a stub that lies
# — `git push` exits 0 without touching the remote at all. push.sh's own
# push-status check (`push_rc -eq 0`) is satisfied and stays silent; only the
# rev-parse verification added by this fix can catch the deception. Asserts
# the SPECIFIC "does not match local HEAD" message, not just "any failure",
# so this can't pass by accidentally tripping the unrelated push_rc branch.
STUB_BIN3="$TMP/stubbin3"
mkdir -p "$STUB_BIN3"
cat > "$STUB_BIN3/git" <<EOF
#!/bin/bash
if [[ "\$1" == "push" ]]; then
  echo "Everything up-to-date"
  exit 0
fi
exec "$REAL_GIT_PATH" "\$@"
EOF
chmod +x "$STUB_BIN3/git"

R=$(new_fixture deceptive_success)
echo "changed" > "$R/base.txt"
OUT=$( (cd "$R" && PATH="$STUB_BIN3:$GH_STUB_DIR:$PATH" bash "$PUSH_SH") 2>&1 )
RC=$?
check "DECEPTIVE-SUCCESS: exits non-zero (rev-parse guard catches the lie)" "1" "$([ "$RC" -ne 0 ] && echo 1 || echo 0)"
check "DECEPTIVE-SUCCESS: does NOT print 'Pushed'" "0" "$(printf '%s' "$OUT" | grep -c 'Pushed')"
check "DECEPTIVE-SUCCESS: reports the specific mismatch reason" "1" "$(printf '%s' "$OUT" | grep -q 'does not match local HEAD' && echo 1 || echo 0)"

# ══════════════════════════════════════════════════════════════════════════
# ─── --add FLAG: opt-in staging of a caller's own new files ─────────────────
# ══════════════════════════════════════════════════════════════════════════
# Fixture carries THREE kinds of change at once: a tracked-modified file
# (base.txt, always staged by `git add -u`), a NEW untracked file the caller
# names via --add (mynew.txt), and a FOREIGN untracked file the caller never
# named (foreign.txt) — proving --add stages only what it's told to, not
# every untracked file (that would be the git-add-A over-staging bug this
# change must avoid reintroducing).
R=$(new_fixture add_flag_stages_named)
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
echo "changed" > "$R/base.txt"
echo "new" > "$R/mynew.txt"
echo "not mine" > "$R/foreign.txt"
run_push "$R" --add mynew.txt
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "ADD-FLAG: does not crash (exit 0)" "0" "$LAST_RC"
check "ADD-FLAG: HEAD advances (a new commit was made)" "1" "$([ "$BEFORE_HEAD" != "$AFTER_HEAD" ] && echo 1 || echo 0)"
check "ADD-FLAG: tracked-modified file committed" "1" "$(printf '%s' "$committed_files" | grep -c base.txt)"
check "ADD-FLAG: named new file committed" "1" "$(printf '%s' "$committed_files" | grep -c mynew.txt)"
check "ADD-FLAG: foreign untracked file NOT committed" "0" "$(printf '%s' "$committed_files" | grep -c foreign.txt)"
check "ADD-FLAG: foreign file still warned as untracked" "1" "$(printf '%s' "$LAST_OUT" | grep -c '^! Untracked')"
check "ADD-FLAG: warning names the foreign file" "1" "$(printf '%s' "$LAST_OUT" | grep -c 'foreign.txt')"
# Scoped to the untracked-file warning's OWN lines (not the whole output,
# which legitimately mentions mynew.txt elsewhere — e.g. "create mode ...
# mynew.txt" in git's own commit summary) — the warning block itself must not
# name a file that --add already staged.
check "ADD-FLAG: warning does NOT name the added file (it's no longer untracked)" "0" "$(printf '%s' "$LAST_OUT" | grep '^!' | grep -c 'mynew.txt')"

# ─── --add FLAG + commit message: flag parsing doesn't corrupt either value ──
# The add-path must not be swallowed as the commit message, and the message
# must not be swallowed as an add-path. Asserts the commit SUBJECT exactly
# (fixture has no JIRA key configured on this branch, so no prefix to strip).
R=$(new_fixture add_flag_with_message)
echo "changed" > "$R/base.txt"
echo "new" > "$R/mynew.txt"
run_push "$R" --add mynew.txt "my message"
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
subject=$(git -C "$R" log -1 --format=%s)
check "ADD-FLAG+MSG: does not crash (exit 0)" "0" "$LAST_RC"
check "ADD-FLAG+MSG: commit subject is exactly the message (not corrupted by flag parsing)" "my message" "$subject"
check "ADD-FLAG+MSG: named new file committed" "1" "$(printf '%s' "$committed_files" | grep -c mynew.txt)"

# ─── MULTIPLE --add FLAGS: each repeated --add stages its own path ──────────
R=$(new_fixture add_flag_multiple)
echo "changed" > "$R/base.txt"
echo "a" > "$R/a.txt"
echo "b" > "$R/b.txt"
echo "not mine" > "$R/foreign2.txt"
run_push "$R" --add a.txt --add b.txt
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "ADD-FLAG-MULTI: does not crash (exit 0)" "0" "$LAST_RC"
check "ADD-FLAG-MULTI: first added path committed" "1" "$(printf '%s' "$committed_files" | grep -c a.txt)"
check "ADD-FLAG-MULTI: second added path committed" "1" "$(printf '%s' "$committed_files" | grep -c b.txt)"
check "ADD-FLAG-MULTI: foreign file NOT committed" "0" "$(printf '%s' "$committed_files" | grep -c foreign2.txt)"

# ─── DEFAULT UNCHANGED: no --add flag ⇒ new untracked file still not staged ──
# Regression lock: the additive --add branch must not alter the default
# (no-flag) path. Overlaps UNTRACKED-PRESENT above by design — an explicit
# lock scoped to this feature's own fixture, independent of that case.
R=$(new_fixture no_add_flag_default)
echo "changed" > "$R/base.txt"
echo "new" > "$R/mynew.txt"
run_push "$R"
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "NO-ADD-DEFAULT: does not crash (exit 0)" "0" "$LAST_RC"
check "NO-ADD-DEFAULT: new untracked file NOT committed" "0" "$(printf '%s' "$committed_files" | grep -c mynew.txt)"
check "NO-ADD-DEFAULT: untracked-file warning printed" "1" "$(printf '%s' "$LAST_OUT" | grep -c '^! Untracked')"

printf '\n--- push_staging.test.sh: %d failing checks ---\n' "$fails"
[ "$fails" -eq 0 ] && exit 0 || exit 1
