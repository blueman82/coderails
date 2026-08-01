#!/bin/bash
# Behavioural tests for the wiki-ingest debt gate in scripts/merge.sh
# (merge::has_wiki_ingest_for_merged_prs) — the config-keyed, fail-closed
# gate inserted after the smoke-verify/tier-review gates and before the merge
# action. Active only when config keys wiki_debt_epoch_pr AND wiki_path are
# both set; otherwise inert (one-line skip notice, merge proceeds).
#
# Mirrors merge_tier_review_gate.test.sh's stub-dir/wrapper technique. The
# fake config lives at $TMP/proj/.claude/workflow.config.yaml so the gate's
# relative wiki_path resolution (against the config's project root) is
# exercised for real. The vault is a REAL git repo pair (remote + clone) so
# `git fetch origin main` and the two `git grep` coverage regexes run against
# a genuine origin/main ref, not stubs. Only gh (merged-PR list, merge
# plumbing) and the sibling gates' pr::* helpers are stubbed — plus, for
# single tests, env-driven overrides: MOCK_REPO (repo() output),
# MOCK_MERGED_EMPTY (gh exits 0 with empty stdout), MOCK_FETCH_NOOP (git
# fetch succeeds without materialising any ref).
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MERGE_SH="$REPO_ROOT/scripts/merge.sh"
TMP=$(mktemp -d)
trap 'chmod -R u+w "$TMP" 2>/dev/null; find "$TMP" -type f -delete 2>/dev/null; find "$TMP" -depth -type d -exec rmdir {} + 2>/dev/null || true' EXIT

fails=0
testn=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_msg() { # desc pattern output
  if echo "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected pattern: %s\n  actual output:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── Build a stub dir that merge.sh will source ──────────────────────────────
STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR/lib" "$TMP/proj/.claude"

# Stub config.sh — points at the per-run fake config under $TMP/proj/.claude
# so the gate's project-root-relative wiki_path resolution is real.
cat > "$STUB_DIR/lib/config.sh" <<CONFIGSTUB
#!/bin/bash
coderails::config_path() { echo "$TMP/proj/.claude/workflow.config.yaml"; }
coderails::resolve_config() { cat "$TMP/proj/.claude/workflow.config.yaml" 2>/dev/null || echo "NO_CONFIG"; }
CONFIGSTUB

# Stub git-common.sh base (always constant). repo() returns test-owner/test-repo,
# so the gate's repo-qualified regexes must match on the short name "test-repo".
cat > "$STUB_DIR/lib/git-common-base.sh" <<'BASELIB'
#!/bin/bash
readonly C_RED='' C_GRN='' C_YLW='' C_BLU='' C_DIM='' C_BLD='' C_RST='' 2>/dev/null || true
info()    { printf '%s\n' "$1"; }
ok()      { :; }
warn()    { :; }
err()     { printf '%s\n' "$1" >&2; exit 1; }
dim()     { :; }
step()    { :; }
banner()  { :; }

branch()  { echo "feature/test"; }
dirty()   { return 1; }
clean()   { return 0; }
main()    { echo "main"; }

# repo() honours MOCK_REPO when SET (even set-empty — the ${var-default}
# form), so tests can reproduce repo()'s real empty-output-exit-0 mode.
repo()    { echo "${MOCK_REPO-test-owner/test-repo}"; }
protected() { return 1; }
sync::main_branch() { return 0; }

require::feature() { return 0; }
require::clean()   { return 0; }
require::repo()    { return 0; }

pr::num()    { echo "42"; }
pr::url()    { echo "https://github.com/test-owner/test-repo/pull/42"; }
pr::state()  { echo "OPEN"; }
pr::title()  { echo "Test PR"; }
pr::review() { echo "APPROVED"; }
pr::exists() { return 0; }

pr::head_sha() { echo "deadbeef"; }
pr::has_coderails_review_for_head() { return 0; }
pr::has_coderails_eval_for_head() { PR_EVAL_TIER="0"; return 0; }
pr::coderails_eval_embed_for_head() {
    printf '{"tier":0,"tier_justification":"stub","head_sha":"deadbeef","evals":[]}'
    return 0
}
post_evals::smoke_verify() { return 0; }
BASELIB
# The fake config never sets tier_review.machine_user, so the tier-review gate
# stays inactive here — this file exercises only the wiki-ingest debt gate.

# Stub gh: merge plumbing always succeeds; the merged-PR list is driven by
# MOCK_MERGED_JSON / MOCK_MERGED_FAIL env vars set per-test.
cat > "$STUB_DIR/gh" <<'GHSTUB'
#!/bin/bash
case "$*" in
  *"pr list"*"--state merged"*)
    [ -n "${MOCK_MERGED_FAIL:-}" ] && exit 1
    [ -n "${MOCK_MERGED_EMPTY:-}" ] && exit 0
    printf '%s' "${MOCK_MERGED_JSON:-[]}"
    ;;
  *"pr merge"*) exit 0 ;;
  *"pr view "*"headRefName"*) printf '{"headRefName":"feature/test"}\n' ;;
  *) exit 0 ;;
esac
GHSTUB
chmod +x "$STUB_DIR/gh"

# git stub: branch cleanup plumbing silently succeeds; everything else (the
# gate's real fetch/grep against the vault fixture) passes through to real git.
cat > "$STUB_DIR/git" <<'GITSTUB'
#!/bin/bash
case "$*" in
  *"push origin --delete"*) exit 0 ;;
  *"branch -D"*) exit 0 ;;
  *" fetch "*) if [ -n "${MOCK_FETCH_NOOP:-}" ]; then exit 0; fi; exec /usr/bin/git "$@" ;;
  *) exec /usr/bin/git "$@" ;;
esac
GITSTUB
chmod +x "$STUB_DIR/git"

# ─── Wrapper: real merge.sh with lib sources swapped for the stubs ───────────
WRAPPER="$STUB_DIR/merge_test.sh"
cat > "$WRAPPER" <<WRAPPERHEAD
#!/bin/bash
set -euo pipefail
_DIR="\$(dirname "\${BASH_SOURCE[0]}")"
source "\$_DIR/lib/git-common-base.sh"
source "\$_DIR/lib/config.sh"
WRAPPERHEAD
awk '
    NR==1 { next }
    /^source.*git-common/ { next }
    /^source.*config/ { next }
    /^source.*post_evals/ { next }
    { print }
' "$MERGE_SH" >> "$WRAPPER"

# ─── Gate-only wrapper: calls merge::has_wiki_ingest_for_merged_prs directly ─
# Needed for the unreadable-config test: in the full merge::main path the
# PRE-EXISTING tier-review extractor call (not wrapped in `|| err`) dies first
# under set -e, masking the wiki gate's own fail-loud branch.
GATE_WRAPPER="$STUB_DIR/gate_only_test.sh"
cat > "$GATE_WRAPPER" <<WRAPPERHEAD
#!/bin/bash
set -euo pipefail
_DIR="\$(dirname "\${BASH_SOURCE[0]}")"
source "\$_DIR/lib/git-common-base.sh"
source "\$_DIR/lib/config.sh"
WRAPPERHEAD
awk '
    NR==1 { next }
    /^source.*git-common/ { next }
    /^source.*config/ { next }
    /^source.*post_evals/ { next }
    /^merge::main "\$@"/ { next }
    { print }
' "$MERGE_SH" >> "$GATE_WRAPPER"
printf 'merge::has_wiki_ingest_for_merged_prs "$@"\n' >> "$GATE_WRAPPER"

# run_wiki_gate_test: <config_mode> <log_line> <src_line> <merged_json> [gh_fail] [break_fetch]
#   config_mode: both | noepoch | nowiki
#   log_line:    line committed into the vault's log.md (besides "# Log")
#   src_line:    line committed into the vault's sources/p.md frontmatter
#   merged_json: gh pr list --state merged stub output
#   gh_fail:     non-empty -> gh pr list exits 1
#   break_fetch: non-empty -> vault origin remote re-pointed at a missing path
run_wiki_gate_test() {
    local config_mode="$1" log_line="$2" src_line="$3" merged_json="$4" gh_fail="${5:-}" break_fetch="${6:-}"
    local stderr_file="$TMP/stderr_run" stdout_file="$TMP/stdout_run"

    testn=$((testn+1))
    local vr="$TMP/vr$testn" vault_name="vault$testn" vault="$TMP/vault$testn"

    case "$config_mode" in
        both)    printf 'wiki_path: ../%s\nwiki_debt_epoch_pr: 80\n' "$vault_name" ;;
        noepoch) printf 'wiki_path: ../%s\n' "$vault_name" ;;
        nowiki)  printf 'wiki_debt_epoch_pr: 80\n' ;;
        badpath) printf 'wiki_path: ../no-such-vault-dir\nwiki_debt_epoch_pr: 80\n' ;;
        quoted)  printf 'wiki_path: "../%s" # vault dir\nwiki_debt_epoch_pr: "80" # epoch note\n' "$vault_name" ;;
    esac > "$TMP/proj/.claude/workflow.config.yaml"

    mkdir -p "$vr/sources"
    printf '%s\n' '# Log' "$log_line" > "$vr/log.md"
    printf '%s\n' '---' "$src_line" '---' > "$vr/sources/p.md"
    git -C "$vr" init -q -b main
    git -C "$vr" add -A
    git -C "$vr" -c user.email=t@t -c user.name=t commit -qm init
    git clone -q "$vr" "$vault"
    if [[ -n "$break_fetch" ]]; then
        git -C "$vault" remote set-url origin "$TMP/missing-remote"
    fi

    (
        export PATH="$STUB_DIR:$PATH"
        export MOCK_MERGED_JSON="$merged_json"
        [[ -n "$gh_fail" ]] && export MOCK_MERGED_FAIL=1
        bash "$WRAPPER" 42 2>"$stderr_file" >"$stdout_file"
    )
    local rc=$?
    LAST_STDERR=$(cat "$stderr_file" 2>/dev/null || true)
    LAST_STDOUT=$(cat "$stdout_file" 2>/dev/null || true)
    return $rc
}

NOOP_85='## [2026-08-01] no-op | test-repo PR #85 — covered by a memory note instead'
MERGED_85='[{"number":85},{"number":79}]'

# ─── Test 1: epoch set, uncovered post-epoch merged PR -> BLOCK, names it ────
run_wiki_gate_test both 'nothing relevant' 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate blocks an uncovered post-epoch merged PR" 1 $rc
check_msg "block message names the uncovered PR number" "#85" "$LAST_STDERR"
check_msg "block message names both ways to clear the debt" "no-op" "$LAST_STDERR"

# ─── Test 2: covered by an anchored no-op log.md entry -> merge proceeds ─────
run_wiki_gate_test both "$NOOP_85" 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate passes when the PR has an anchored no-op ledger entry" 0 $rc

# ─── Test 3: covered by a sources origin: line (multi-PR form) -> proceeds ───
run_wiki_gate_test both 'nothing relevant' 'origin: test-repo PRs #24 (adhoc), #85' "$MERGED_85"
rc=$?
check "wiki-debt gate passes on multi-PR sources origin: coverage" 0 $rc

# ─── Test 4: covered by the singular sources form "PR #85" -> proceeds ───────
run_wiki_gate_test both 'nothing relevant' 'origin: test-repo PR #85' "$MERGED_85"
rc=$?
check "wiki-debt gate passes on singular sources origin: coverage (PR, not PRs)" 0 $rc

# ─── Test 5: no wiki_debt_epoch_pr key -> inert skip, merge proceeds ─────────
run_wiki_gate_test noepoch 'nothing relevant' 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate is inert (exit 0) when the epoch key is absent" 0 $rc
check_msg "inert path prints a one-line skip notice" "skipped" "$LAST_STDOUT"

# ─── Test 6: epoch set but no wiki_path -> inert skip, merge proceeds ────────
run_wiki_gate_test nowiki 'nothing relevant' 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate is inert (exit 0) when wiki_path is absent" 0 $rc
check_msg "wiki_path-absent path prints the skip notice" "skipped" "$LAST_STDOUT"

# ─── Test 7: digit boundary — a #850 no-op entry must NOT cover #85 ──────────
run_wiki_gate_test both '## [2026-08-01] no-op | test-repo PR #850 — other work' 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate: no-op entry for #850 does not cover #85 (digit boundary)" 1 $rc

# ─── Test 8: repo qualification — other-repo coverage must NOT count ─────────
run_wiki_gate_test both '## [2026-08-01] no-op | other-repo PR #85 — theirs' 'origin: other-repo PRs #85' "$MERGED_85"
rc=$?
check "wiki-debt gate: other-repo no-op/origin lines do not cover test-repo #85" 1 $rc

# ─── Test 9: anchoring — an unanchored no-op mention must NOT count ──────────
run_wiki_gate_test both 'note: no-op | test-repo PR #85 — buried mid-file' 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate: unanchored no-op mention does not cover #85" 1 $rc

# ─── Test 10: gh merged-PR list failure -> BLOCK (fail closed) ───────────────
run_wiki_gate_test both "$NOOP_85" 'origin: unrelated' "" fail
rc=$?
check "wiki-debt gate blocks when gh pr list fails (fail closed)" 1 $rc
check_msg "gh-failure block message mentions the fetch" "GitHub fetch failed" "$LAST_STDERR"

# ─── Test 11: vault fetch failure -> BLOCK (fail closed) ─────────────────────
run_wiki_gate_test both "$NOOP_85" 'origin: unrelated' "$MERGED_85" "" breakfetch
rc=$?
check "wiki-debt gate blocks when the vault fetch fails (fail closed)" 1 $rc
check_msg "vault-fetch block message names the wiki fetch" "Wiki fetch failed" "$LAST_STDERR"

# ─── Test 12: at/below-epoch merged PRs are filtered out ─────────────────────
# Epoch is 80; the merged list holds only numbers <= 80 (42, 79, 80), all
# uncovered in the vault. No candidates survive the epoch filter, so the
# gate must proceed without consulting coverage at all.
run_wiki_gate_test both 'nothing relevant' 'origin: unrelated' '[{"number":42},{"number":79},{"number":80}]'
rc=$?
check "wiki-debt gate: at/below-epoch merged PRs produce no candidates" 0 $rc

# ─── Test 13: the PR being merged is excluded from its own debt check ────────
# Merged list holds only #81 (post-epoch, uncovered); merging PR IS 81 (gh
# sometimes lists a just-merged PR). Must not block itself.
(
    export PATH="$STUB_DIR:$PATH"
    export MOCK_MERGED_JSON='[{"number":81}]'
    printf 'wiki_path: ../vault%s\nwiki_debt_epoch_pr: 80\n' "$testn" > "$TMP/proj/.claude/workflow.config.yaml"
    bash "$WRAPPER" 81 2>"$TMP/stderr_run" >"$TMP/stdout_run"
)
rc=$?
LAST_STDERR=$(cat "$TMP/stderr_run" 2>/dev/null || true)
check "wiki-debt gate: the PR being merged is excluded from candidates" 0 $rc

# ─── Test 14: repo() empty-output-exit-0 -> BLOCK (no false coverage) ────────
# repo() succeeds with EMPTY output on a non-github origin URL; an empty repo
# name would collapse the sources regex into matching ANY repo's coverage.
# The vault deliberately holds coverage for #85 (under test-repo) that the
# collapsed regex WOULD have matched — the gate must err instead.
export MOCK_REPO=""
run_wiki_gate_test both "$NOOP_85" 'origin: test-repo PRs #85' "$MERGED_85"
rc=$?
unset MOCK_REPO
check "wiki-debt gate blocks when repo() resolves to empty (fail closed)" 1 $rc
check_msg "empty-repo block message names the repo resolution" "Could not resolve the origin repo" "$LAST_STDERR"

# ─── Test 15: configured-but-unresolvable wiki_path -> BLOCK, not skip ───────
run_wiki_gate_test badpath 'nothing relevant' 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate blocks when the configured wiki_path does not resolve" 1 $rc
check_msg "unresolvable-path block message says it does not resolve" "does not resolve" "$LAST_STDERR"

# ─── Test 16: suffix-colliding repo must NOT clear (left boundary) ───────────
# "origin: xtest-repo PRs #85" must not cover test-repo's #85.
run_wiki_gate_test both 'nothing relevant' 'origin: xtest-repo PRs #85' "$MERGED_85"
rc=$?
check "wiki-debt gate: suffix-colliding repo coverage (xtest-repo) does not clear test-repo" 1 $rc

# ─── Test 17: dotted repo name — "." must not act as an ERE wildcard ─────────
# repo my.repo with only myXrepo coverage in the vault must still block.
export MOCK_REPO="test-owner/my.repo"
run_wiki_gate_test both '## [2026-08-01] no-op | myXrepo PR #85 — theirs' 'origin: myXrepo PRs #85' "$MERGED_85"
rc=$?
check "wiki-debt gate: myXrepo coverage does not clear my.repo (dot escaped)" 1 $rc

# ─── Test 18: dotted repo name still matches ITSELF after escaping ───────────
run_wiki_gate_test both 'nothing relevant' 'origin: my.repo PRs #85' "$MERGED_85"
rc=$?
unset MOCK_REPO
check "wiki-debt gate: my.repo coverage clears my.repo (escaping is not over-broad)" 0 $rc

# ─── Test 19: gh exits 0 with EMPTY stdout -> BLOCK (fail closed) ────────────
export MOCK_MERGED_EMPTY=1
run_wiki_gate_test both "$NOOP_85" 'origin: unrelated' "$MERGED_85"
rc=$?
unset MOCK_MERGED_EMPTY
check "wiki-debt gate blocks when gh returns empty stdout at exit 0" 1 $rc
check_msg "empty-response block message names the empty response" "empty merged-PR response" "$LAST_STDERR"

# ─── Test 20: merged-PR window full (100 entries) -> BLOCK (truncation) ──────
# All 100 entries sit at/below the epoch, so without the window check the
# gate would pass with zero candidates — the check must fire regardless,
# because a full window means older post-epoch PRs may have been truncated.
MERGED_100=$(jq -nc '[range(100) | {number: 79}]')
run_wiki_gate_test both 'nothing relevant' 'origin: unrelated' "$MERGED_100"
rc=$?
check "wiki-debt gate blocks when the merged-PR window is full (100 entries)" 1 $rc
check_msg "full-window block message says how to clear it" "merged-PR window full" "$LAST_STDERR"

# ─── Test 21: fetch succeeds but origin/main ref is absent -> BLOCK ──────────
# A no-op "successful" fetch against a vault clone with no origin/main must
# block — otherwise every candidate reads as 'not covered' against a wiki
# that was never searched.
testn=$((testn+1))
vault="$TMP/vault$testn"
mkdir -p "$vault"
git -C "$vault" init -q -b main
git -C "$vault" remote add origin "$TMP/no-such-remote"
printf 'wiki_path: ../vault%s\nwiki_debt_epoch_pr: 80\n' "$testn" > "$TMP/proj/.claude/workflow.config.yaml"
(
    export PATH="$STUB_DIR:$PATH"
    export MOCK_MERGED_JSON="$MERGED_85"
    export MOCK_FETCH_NOOP=1
    bash "$WRAPPER" 42 2>"$TMP/stderr_run" >"$TMP/stdout_run"
)
rc=$?
LAST_STDERR=$(cat "$TMP/stderr_run" 2>/dev/null || true)
check "wiki-debt gate blocks when the vault has no origin/main ref after fetch" 1 $rc
check_msg "missing-ref block message names the absent ref" "no origin/main ref" "$LAST_STDERR"

# ─── Test 22: quoted values with inline comments parse cleanly ───────────────
# wiki_debt_epoch_pr: "80" # note  must yield 80 (comment stripped BEFORE
# quotes), and the quoted-with-comment wiki_path must resolve — the covered
# vault then lets the merge proceed.
run_wiki_gate_test quoted "$NOOP_85" 'origin: unrelated' "$MERGED_85"
rc=$?
check "wiki-debt gate parses quoted config values with inline comments" 0 $rc

# ─── Test 23: unreadable config -> loud err, not a silent set -e death ───────
# Uses the gate-only wrapper (see above): the full merge::main path dies
# earlier at the pre-existing unwrapped tier-review extractor call.
printf 'wiki_path: ../vault%s\nwiki_debt_epoch_pr: 80\n' "$testn" > "$TMP/proj/.claude/workflow.config.yaml"
chmod 000 "$TMP/proj/.claude/workflow.config.yaml"
(
    export PATH="$STUB_DIR:$PATH"
    export MOCK_MERGED_JSON="$MERGED_85"
    bash "$GATE_WRAPPER" 42 2>"$TMP/stderr_run" >"$TMP/stdout_run"
)
rc=$?
LAST_STDERR=$(cat "$TMP/stderr_run" 2>/dev/null || true)
chmod 644 "$TMP/proj/.claude/workflow.config.yaml"
check "wiki-debt gate errs loudly when the config file is unreadable" 1 $rc
check_msg "unreadable-config block message names the config read" "Could not read" "$LAST_STDERR"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
