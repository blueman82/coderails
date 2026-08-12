#!/bin/bash
#═══════════════════════════════════════════════════════════════════════════════
#  merge.sh │ verify → merge → sync
#═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
source "$(dirname "$0")/lib/git-common.sh"
source "$(dirname "$0")/lib/config.sh"
source "$(dirname "$0")/post_evals.sh"

# coderails::_integrity_machine_user <config_file>
# Echoes the value of the nested key integrity_review.machine_user from a
# workflow.config.yaml, or nothing if the key/block is absent. No generic
# nested-key YAML reader exists in this repo (scripts/lib/config.sh only
# locates the file) — this is a minimal, single-purpose extractor for this
# one key, not a new config system.
coderails::_integrity_machine_user() {
    local config_file="$1"
    [[ -f "$config_file" ]] || return 0
    awk '
        /^integrity_review:[[:space:]]*$/ { in_block=1; next }
        in_block && /^[^[:space:]]/ { in_block=0 }
        in_block && /^[[:space:]]+machine_user:/ {
            sub(/^[[:space:]]+machine_user:[[:space:]]*/, "")
            gsub(/^["'"'"']|["'"'"']$/, "")
            gsub(/[[:space:]]*#.*$/, "")
            gsub(/[[:space:]]+$/, "")
            print
            exit
        }
    ' "$config_file" 2>/dev/null
}

# coderails::_wiki_debt_epoch_pr <config_file>
# Echoes the value of the top-level key wiki_debt_epoch_pr from a
# workflow.config.yaml, or nothing if the key is absent. Same minimal
# single-purpose awk extractor shape as coderails::_integrity_machine_user
# above — still not a generic config system. One deliberate ordering
# difference from that older extractor: the inline comment is stripped BEFORE
# the surrounding quotes, so `key: "80" # note` yields `80`, not `80"` (quote
# stripping first leaves the trailing quote glued to the value).
coderails::_wiki_debt_epoch_pr() {
    local config_file="$1"
    [[ -f "$config_file" ]] || return 0
    awk '
        /^wiki_debt_epoch_pr:/ {
            sub(/^wiki_debt_epoch_pr:[[:space:]]*/, "")
            gsub(/[[:space:]]*#.*$/, "")
            gsub(/[[:space:]]+$/, "")
            gsub(/^["'"'"']|["'"'"']$/, "")
            print
            exit
        }
    ' "$config_file" 2>/dev/null
}

# coderails::_wiki_path <config_file>
# Echoes the value of the top-level key wiki_path from a workflow.config.yaml,
# or nothing if absent. No sourceable resolver exists for this key —
# hooks/scripts/wiki_taxonomy_gate.sh parses it inline for its own purposes —
# so this mirrors that hook's handling (quote stripping; the caller treats
# YAML nulls `null`/`~` as unset) in the same extractor shape as above.
coderails::_wiki_path() {
    local config_file="$1"
    [[ -f "$config_file" ]] || return 0
    awk '
        /^wiki_path:/ {
            sub(/^wiki_path:[[:space:]]*/, "")
            gsub(/[[:space:]]*#.*$/, "")
            gsub(/[[:space:]]+$/, "")
            gsub(/^["'"'"']|["'"'"']$/, "")
            print
            exit
        }
    ' "$config_file" 2>/dev/null
}

# merge::has_wiki_ingest_for_merged_prs <pr_number>
# Wiki-ingest debt gate (config-keyed, fail-closed). Blocks the merge while
# any PR merged AFTER config key wiki_debt_epoch_pr remains unrepresented in
# the configured wiki vault's origin/main — either by a sources/*.md page
# whose `origin:` frontmatter names the PR, or by an anchored no-op ledger
# entry in log.md (`## [YYYY-MM-DD] no-op | <repo> PR #N — reason`).
#
# CONFIG-KEYED AND INERT BY DEFAULT: merge.sh is repo-generic, so a repo
# without wiki_debt_epoch_pr (or without wiki_path) gets a one-line skip
# notice and no behaviour change. When both keys are set, every failure mode
# is fail-closed: a gh/network failure, an unresolvable wiki_path, or a
# failed vault fetch all err and block — never a silent skip, which would be
# indistinguishable from the gate approving the debt.
#
# REGEX IDENTITY REQUIREMENT: the two coverage regexes below are a frozen
# contract — a future proactive sweep family re-implements them and the two
# must stay character-exact identical, or the gate and the sweep would
# disagree about what counts as covered. Change them only in lockstep. Both
# patterns now appear THREE times in this function — against origin/main
# below, and again against each open vault PR head's FETCH_HEAD in the
# coverage-in-progress check further down — every copy must move together.
# The exact forms, with ${repo_escaped} = the repo short name with ERE
# metacharacters backslash-escaped (repo names may contain ".", an ERE
# wildcard) and ${n} = the candidate PR number:
#   log.md:   ^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}\] no-op \| ${repo_escaped} PR #${n}([^0-9]|$)
#   sources/: ^origin:(.*[^A-Za-z0-9._-])?${repo_escaped} PRs? [^\"]*#${n}([^0-9]|$)
# The sources regex's (.*[^A-Za-z0-9._-])? group is a left boundary: the char
# before the repo name must be the start (right after "origin:") or a
# non-repo-name char, so a suffix-colliding repo ("xtest-repo") can never
# clear "test-repo". The log.md regex's literal "| " prefix already bounds
# its left side.
#
# The PR being merged is excluded from its own debt check (its ingest happens
# after this merge), and only the vault's origin/main counts — a local,
# unpushed wiki page is not durable coverage, hence the single fetch first.
merge::has_wiki_ingest_for_merged_prs() {
    local num="$1"
    local config epoch="" wiki_rel=""
    config=$(coderails::config_path "$PWD")
    if [[ -n "$config" ]]; then
        epoch=$(coderails::_wiki_debt_epoch_pr "$config") \
            || err "Could not read $config for the wiki-ingest debt gate."
        wiki_rel=$(coderails::_wiki_path "$config") \
            || err "Could not read $config for the wiki-ingest debt gate."
    fi
    case "$wiki_rel" in null|'~') wiki_rel="" ;; esac
    if [[ -z "$epoch" || -z "$wiki_rel" ]]; then
        info "Wiki-ingest debt gate (has_wiki_ingest_for_merged_prs) skipped — wiki_debt_epoch_pr and/or wiki_path not configured."
        return 0
    fi
    if ! [[ "$epoch" =~ ^[0-9]+$ ]]; then
        err "wiki_debt_epoch_pr ('$epoch') is not a PR number — fix .claude/workflow.config.yaml."
    fi

    # wiki_path may be relative (resolved against the config's project root —
    # the directory holding .claude/, same base wiki_taxonomy_gate.sh uses) or
    # absolute. Configured-but-unresolvable is a block, not a skip.
    local project_root vault
    project_root=$(dirname "$(dirname "$config")")
    case "$wiki_rel" in
        /*) vault=$(cd "$wiki_rel" 2>/dev/null && pwd -P) || vault="" ;;
        *)  vault=$(cd "$project_root/$wiki_rel" 2>/dev/null && pwd -P) || vault="" ;;
    esac
    if [[ -z "$vault" ]]; then
        err "wiki_path ('$wiki_rel') does not resolve to a directory — fix it (or unset wiki_debt_epoch_pr to disable the wiki-ingest debt gate)."
    fi

    local repo
    repo=$(repo) || err "Could not resolve the origin repo for the wiki-ingest debt gate."
    repo="${repo##*/}"
    # repo() can succeed with EMPTY output (non-github origin URL) — an empty
    # $repo would collapse the coverage regexes into matching ANY repo's
    # coverage, so emptiness is a hard block, not a passthrough.
    [[ -n "$repo" ]] || err "Could not resolve the origin repo for the wiki-ingest debt gate."
    # ERE-escape the repo name before regex interpolation ("." in a repo name
    # would otherwise act as a wildcard — "myXrepo" coverage clearing "my.repo").
    local repo_escaped
    repo_escaped=$(printf '%s' "$repo" | sed 's/[][$.*+?^(){}|\\]/\\&/g')

    local merged
    merged=$(gh pr list --state merged --json number --limit 100 2>/dev/null) \
        || err "GitHub fetch failed — could not list merged PRs for the wiki-ingest debt gate. Retry, or check gh auth/network."
    # gh can exit 0 with empty stdout on some failure modes — jq would then
    # "parse" nothing and the gate would silently see zero merged PRs.
    [[ -n "$merged" ]] || err "GitHub returned an empty merged-PR response for the wiki-ingest debt gate."
    local merged_count
    merged_count=$(printf '%s' "$merged" | jq -r 'length' 2>/dev/null) \
        || err "Could not parse the merged PR list for the wiki-ingest debt gate."
    # gh pr list returns newest-first, so a full window truncates the OLDEST
    # merged PRs — exactly the ones most likely to carry unpaid debt. A full
    # window means unknown PRs went unchecked: fail closed.
    if [[ "$merged_count" -eq 100 ]]; then
        err "merged-PR window full — advance wiki_debt_epoch_pr or raise the limit."
    fi
    local candidates
    candidates=$(printf '%s' "$merged" | jq -r --argjson epoch "$epoch" --argjson cur "$num" \
        '.[].number | select(. > $epoch and . != $cur)' 2>/dev/null) \
        || err "Could not parse the merged PR list for the wiki-ingest debt gate."
    if [[ -z "$candidates" ]]; then
        ok "Wiki-ingest debt clear (no merged PRs after epoch #$epoch)"
        return 0
    fi

    git -C "$vault" fetch -q origin main \
        || err "Wiki fetch failed — could not fetch origin main in $vault for the wiki-ingest debt gate. Retry, or check the vault path/network."
    # A fetch that succeeds without materialising the ref would make every
    # grep below report "not covered" against a wiki that was never searched.
    git -C "$vault" rev-parse -q --verify origin/main >/dev/null \
        || err "vault has no origin/main ref after the fetch — the wiki was never searched; fix the vault's origin remote for the wiki-ingest debt gate."

    local n uncovered=""
    while IFS= read -r n; do
        [[ -z "$n" ]] && continue
        if git -C "$vault" grep -qE "^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}\] no-op \| ${repo_escaped} PR #${n}([^0-9]|$)" origin/main -- log.md \
           || git -C "$vault" grep -qE "^origin:(.*[^A-Za-z0-9._-])?${repo_escaped} PRs? [^\"]*#${n}([^0-9]|$)" origin/main -- sources/; then
            continue
        fi
        uncovered="${uncovered:+$uncovered }#$n"
    done <<< "$candidates"

    # ─── Coverage-in-progress check (open vault PR) ────────────────────────
    # wiki-ingest's PR flow (wiki_git_worktree: true) no longer self-merges —
    # its output page lands on an OPEN PR's head, not origin/main, until a
    # human merges it. Without this check, every PR-flow ingest would be a
    # false "uncovered" violation between `gh pr create` and human merge,
    # hard-blocking this repo's own next unrelated /coderails:merge on a PR
    # only a human can close. Any open PR on the vault (not just one this
    # gate can identify as wiki-ingest's own — headRefName alone doesn't
    # distinguish that) whose head already carries the coverage line is
    # in-progress, not missing — but a merged, closed, or never-opened
    # ingest still hard-blocks (fail-closed unchanged). Introduces a third
    # gate outcome alongside the pre-existing covered/uncovered pair: see
    # the REGEX IDENTITY REQUIREMENT note above — the same two coverage
    # regexes are reused verbatim below, now duplicated a third time (also
    # against FETCH_HEAD); any edit to those patterns must update every
    # copy, including this one, in lockstep.
    local in_progress=""
    if [[ -n "$uncovered" ]]; then
        local vault_url vault_repo=""
        vault_url=$(git -C "$vault" remote get-url origin 2>/dev/null) || vault_url=""
        if [[ "$vault_url" =~ github\.com[:/]([^/]+)/(.+)$ ]]; then
            local vname="${BASH_REMATCH[2]}"
            vname="${vname%/}"; vname="${vname%.git}"
            vault_repo="${BASH_REMATCH[1]}/${vname}"
        fi
        if [[ -z "$vault_repo" ]]; then
            # Not a failure — a vault with a non-github.com origin simply has
            # no open-PR concept to probe. Warn (visibility) and fall through
            # to the pre-existing origin/main verdict unchanged; do not
            # misdiagnose this as a remote misconfiguration to fix.
            warn "Wiki-ingest debt: in-progress-coverage probe skipped (vault origin is not a github.com URL) — verdict based on origin/main only."
        else
            local open_heads open_rc=0
            open_heads=$(gh pr list --repo "$vault_repo" --state open --json headRefName --limit 100 -q '.[].headRefName' 2>/dev/null) || open_rc=$?
            if [[ $open_rc -ne 0 ]]; then
                err "Wiki-ingest debt: GitHub fetch failed — could not list open PRs on vault $vault_repo to check for in-progress ingest coverage of ${uncovered}. Retry, or check gh auth/network."
            fi
            # Same fail-closed posture as the merged-PR window above: a full
            # window of 100 open PRs on the vault means some may be truncated
            # and unchecked — that could hide real coverage-in-progress and
            # cause a false hard-block, so warn rather than silently
            # proceeding as if the list were complete.
            if [[ $(printf '%s\n' "$open_heads" | grep -c .) -eq 100 ]]; then
                warn "Wiki-ingest debt: vault $vault_repo has 100+ open PRs — in-progress-coverage probe may have missed some; a false debt block is possible."
            fi
            if [[ -n "$open_heads" ]]; then
                # Loop heads OUTER, still-uncovered numbers INNER: one fetch
                # per head (FETCH_HEAD is always the head just fetched — no
                # named refs, no vault-side state, nothing to clean up), and
                # each covered number is dropped from $remaining as it's
                # found so later heads only check what's left. A per-ref
                # fetch failure is tracked, not silently skipped: if any open
                # head fails to fetch while debt still remains uncovered
                # after the loop, that's surfaced as a hard err rather than
                # silently downgrading to "no coverage" — a single stale ref
                # is enough to make the verdict unverifiable, not just a
                # full vault/network outage, because that one ref might have
                # been the PR carrying the coverage line.
                local href remaining="$uncovered" failed_hrefs=""
                while IFS= read -r href; do
                    [[ -z "$href" || -z "$remaining" ]] && continue
                    if ! git -C "$vault" fetch -q origin "$href" 2>/dev/null; then
                        failed_hrefs="${failed_hrefs:+$failed_hrefs }${href}"
                        continue
                    fi
                    local un next_remaining=""
                    for un in $remaining; do
                        n="${un#\#}"
                        if git -C "$vault" grep -qE "^## \[[0-9]{4}-[0-9]{2}-[0-9]{2}\] no-op \| ${repo_escaped} PR #${n}([^0-9]|$)" FETCH_HEAD -- log.md \
                           || git -C "$vault" grep -qE "^origin:(.*[^A-Za-z0-9._-])?${repo_escaped} PRs? [^\"]*#${n}([^0-9]|$)" FETCH_HEAD -- sources/; then
                            in_progress="${in_progress:+$in_progress }${un}(vault:$href)"
                        else
                            next_remaining="${next_remaining:+$next_remaining }${un}"
                        fi
                    done
                    remaining="$next_remaining"
                done <<< "$open_heads"
                if [[ -n "$failed_hrefs" ]]; then
                    warn "Wiki-ingest debt: could not fetch open vault PR head(s) to check in-progress coverage: ${failed_hrefs} — treating as unchecked, not as absent."
                fi
                [[ -n "$in_progress" ]] && warn "Wiki-ingest debt coverage in progress (open vault PR, not yet merged — will re-check next merge): ${in_progress}"
                if [[ -n "$remaining" && -n "$failed_hrefs" ]]; then
                    err "Wiki-ingest debt: could not verify in-progress coverage for ${remaining} — fetch failed for open vault PR head(s) ${failed_hrefs}, so this may be unchecked debt rather than confirmed debt. Retry, or check the vault path/network, then retry the merge."
                fi
                uncovered="$remaining"
            fi
        fi
    fi

    if [[ -n "$uncovered" ]]; then
        err "Wiki-ingest debt: merged ${repo} PR(s) not covered in the wiki: ${uncovered} — clear each with a sources/*.md page whose origin: names the PR, or a log.md entry '## [YYYY-MM-DD] no-op | ${repo} PR #N — reason', then retry."
    fi
    if [[ -n "$in_progress" ]]; then
        ok "Wiki-ingest debt: no hard violations (some PRs have coverage in progress on an open vault PR, not yet merged — see warning above; epoch #$epoch)"
    else
        ok "Wiki-ingest debt clear (all merged PRs after epoch #$epoch covered)"
    fi
    return 0
}

merge::main() {
    local arg="${1:-auto}" br=$(branch) m=$(main)

    require::repo

    step "$(repo)"

    # ─── Resolve PR ───────────────────────────────────────────────────────────
    local num
    case "$arg" in
        auto)
            [[ $br == "$m" ]] && err "On $m ─ specify PR# or branch"
            num=$(pr::num "$br") || err "No PR for $br"
            ;;
        [0-9]*)
            num=$arg
            ;;
        *)
            num=$(pr::num "$arg") || err "No PR for $arg"
            ;;
    esac

    info "PR #$num │ $(pr::title "$num")"

    # ─── Merge ────────────────────────────────────────────────────────────────
    case $(pr::state "$num") in
        MERGED) warn "Already merged" ;;
        CLOSED) err "PR closed (not merged)" ;;
        OPEN)
            protected && {
                [[ $(pr::review "$num") == APPROVED ]] || err "Not approved ($(pr::review "$num"))"
                ok "Approved"
            }
            if [[ -z "$(coderails::config_path "$PWD")" ]]; then
                info "No workflow.config.yaml — enforce_pr_workflow hook is inactive, but the review artifact gate still applies."
            fi

            # ─── Review artifact gate (fail-closed) ───────────────────────────
            # Requires a coderails review comment on the PR matching the current
            # head SHA. No match → block. No fallback to local files.
            local sha
            sha=$(pr::head_sha "$num")
            if [[ -z "$sha" ]]; then
                err "GitHub fetch failed — could not resolve PR head SHA. Retry, or check gh auth/network."
            fi
            local gate_rc
            gate_rc=0
            pr::has_coderails_review_for_head "$num" "$sha" || gate_rc=$?
            if [[ $gate_rc -eq 2 ]]; then
                case "${PR_TRUST_FETCH_FAIL_REASON:-}" in
                    identity)   err "GitHub fetch failed — could not resolve the authenticated identity (gh api user). Retry, or check gh auth/network." ;;
                    permission) err "GitHub fetch failed — could not resolve repo permission for the authenticated identity. Retry, or check gh auth/network." ;;
                    tempfile)   err "Local temporary file allocation failed (mktemp) before any GitHub fetch was attempted. Check /tmp disk space or permissions, then retry." ;;
                    *)          err "GitHub fetch failed — could not fetch PR comments. Retry, or check gh auth/network." ;;
                esac
            elif [[ $gate_rc -ne 0 ]]; then
                err "No coderails review artifact for current head $sha — run /coderails:post-review after /pr-review-toolkit:review-pr (or add a 'gh pr merge' permission to bypass)."
            fi
            ok "Review artifact verified (SHA: $sha)"

            # ─── Eval artifact gate (fail-closed) ─────────────────────────────
            # Requires a coderails eval comment on the PR matching the current
            # head SHA with result=GO. No match → block. No fallback, no
            # config opt-out (same posture as the review gate).
            local eval_gate_rc
            eval_gate_rc=0
            pr::has_coderails_eval_for_head "$num" "$sha" || eval_gate_rc=$?
            if [[ $eval_gate_rc -eq 2 ]]; then
                case "${PR_TRUST_FETCH_FAIL_REASON:-}" in
                    identity)   err "GitHub fetch failed — could not resolve the authenticated identity (gh api user) for the eval artifact gate. Retry, or check gh auth/network." ;;
                    permission) err "GitHub fetch failed — could not resolve repo permission for the eval artifact gate. Retry, or check gh auth/network." ;;
                    tempfile)   err "Local temporary file allocation failed (mktemp) before any GitHub fetch was attempted for the eval artifact gate. Check /tmp disk space or permissions, then retry." ;;
                    *)          err "GitHub fetch failed — could not fetch PR comments for eval artifact. Retry, or check gh auth/network." ;;
                esac
            elif [[ $eval_gate_rc -ne 0 ]]; then
                if [[ -n "${PR_EVAL_VERIFICATION_LEVEL:-}" ]]; then
                    err "Eval artifact for current head $sha is NO-GO (verification_level $PR_EVAL_VERIFICATION_LEVEL) — resolve failing P0 evals and re-run /coderails:post-evals."
                else
                    err "No coderails eval artifact for current head $sha — run /coderails:task-evals then /coderails:post-evals after /pr-review-toolkit:review-pr."
                fi
            fi
            ok "Eval artifact verified (SHA: $sha, verification_level ${PR_EVAL_VERIFICATION_LEVEL:-?})"

            # ─── Smoke-verify gate (fail-closed) ──────────────────────────────
            # The eval-artifact gate above only parses the marker comment's
            # result=GO text — checks 1-10 in post_evals.sh's
            # validate_structure never ran against it here, only in the
            # posting agent's own session at post time (advisory, not
            # binding). This gate makes checks 1-9 plus gate-time
            # re-execution binding at merge: it extracts the embed from the
            # SAME trusted comment the eval-artifact gate above already
            # matched, checks out the trusted head SHA into a detached
            # worktree, and re-executes every verification_level>=1 scripted eval's cmd and
            # negative_control there — closing the gap where a hand-written
            # smoke object for a script that never existed passed the
            # eval-artifact gate at rc=0 (PR post_evals.sh check 9/10 never
            # ran). Verification level 0 has an empty .evals array, so this is a fast no-op
            # at that verification_level; nothing to opt out of.
            local embed embed_rc
            embed_rc=0
            embed=$(pr::coderails_eval_embed_for_head "$num" "$sha") || embed_rc=$?
            if [[ $embed_rc -eq 2 ]]; then
                case "${PR_TRUST_FETCH_FAIL_REASON:-}" in
                    identity)   err "GitHub fetch failed — could not resolve the authenticated identity (gh api user) for the smoke-verify gate. Retry, or check gh auth/network." ;;
                    permission) err "GitHub fetch failed — could not resolve repo permission for the smoke-verify gate. Retry, or check gh auth/network." ;;
                    tempfile)   err "Local temporary file allocation failed (mktemp) before any GitHub fetch was attempted for the smoke-verify gate. Check /tmp disk space or permissions, then retry." ;;
                    *)          err "GitHub fetch failed — could not fetch PR comments for the smoke-verify gate. Retry, or check gh auth/network." ;;
                esac
            elif [[ $embed_rc -ne 0 ]]; then
                err "No coderails eval artifact embed found for current head $sha — the eval-artifact gate above should have caught this first; investigate the mismatch before merging."
            fi
            local embed_file
            embed_file=$(mktemp) || err "Local temporary file allocation failed (mktemp) for the smoke-verify gate. Check /tmp disk space or permissions, then retry."
            printf '%s' "$embed" > "$embed_file"
            if ! post_evals::smoke_verify "$embed_file" "$sha"; then
                rm -f "$embed_file"
                err "Smoke-verify failed for current head $sha — one or more scripted evals could not be confirmed by gate-time re-execution against the trusted commit. See the reason above; do not bypass, fix the eval or the artifact and re-post."
            fi
            rm -f "$embed_file"
            ok "Smoke-verify passed (SHA: $sha)"

            # ─── Integrity attestation gate (redundant defence-in-depth, fail-closed) ───
            # This layer is redundant defence-in-depth alongside the now-active
            # server-side ruleset: it fails loudly on misconfiguration, and it
            # still matters even with the ruleset active because the ruleset's
            # bypass actor (the repo admin role) can push straight past it;
            # this local check has no such bypass. It is NOT the primary
            # control — do not delete it as dead code once the ruleset is
            # active; it is the only local check that catches a machine-user
            # misconfiguration before GitHub itself would. Config-keyed and
            # inactive by default: only runs when config key
            # integrity_review.machine_user is set. The daemon attests the
            # current SHA's evidence and never evaluates verification_level semantics.
            local integrity_config; integrity_config=$(coderails::config_path "$PWD")
            local integrity_machine_user=""
            if [[ -n "$integrity_config" ]]; then
                integrity_machine_user=$(coderails::_integrity_machine_user "$integrity_config")
            fi
            if [[ -n "$integrity_machine_user" ]]; then
                local tr_statuses tr_rc=0
                tr_statuses=$(gh api "repos/$(repo)/commits/${sha}/statuses" --paginate \
                    --jq '[.[] | select(.context == "integrity-review")]' 2>/dev/null) || tr_rc=$?
                if [[ $tr_rc -ne 0 ]]; then
                    err "GitHub fetch failed — could not fetch integrity-review status for $sha. Retry, or check gh auth/network."
                fi
                local tr_state tr_creator tr_desc
                tr_state=$(printf '%s' "$tr_statuses" | jq -r '.[0].state // empty' 2>/dev/null)
                tr_creator=$(printf '%s' "$tr_statuses" | jq -r '.[0].creator.login // empty' 2>/dev/null)
                tr_desc=$(printf '%s' "$tr_statuses" | jq -r '.[0].description // empty' 2>/dev/null)
                if [[ -z "$tr_state" ]]; then
                    err "No integrity-review status found for $sha — the integrity daemon has not attested this SHA yet. Wait for it, or kickstart it, then retry."
                elif [[ "$tr_state" != "success" ]]; then
                    err "integrity-review status for $sha is '$tr_state' (not success) — the integrity daemon has not attested this SHA. Resolve and retry."
                elif [[ "$tr_creator" != "$integrity_machine_user" ]]; then
                    err "integrity-review status for $sha was posted by '$tr_creator', not the configured machine user '$integrity_machine_user' — investigate the creator mismatch."
                elif ! [[ "$tr_desc" =~ (^|[[:space:]])integrity=pass([[:space:]]|$) ]] || ! [[ "$tr_desc" =~ (^|[[:space:]])sha=${sha}([[:space:]]|$) ]]; then
                    err "integrity-review status for $sha is not a valid SHA-bound pass attestation. Do not bypass; investigate."
                fi
                ok "Integrity attestation verified (SHA: $sha, creator: $tr_creator)"
            fi

            # ─── Wiki-ingest debt gate (config-keyed, fail-closed) ────────────
            # Third artifact gate: blocks while any post-epoch merged PR lacks
            # wiki coverage. Inert unless wiki_debt_epoch_pr + wiki_path are
            # configured — see merge::has_wiki_ingest_for_merged_prs above.
            merge::has_wiki_ingest_for_merged_prs "$num"

            step "Merging"
            gh pr merge "$num" --merge          # remote merge ONLY — its failure must abort; branch cleanup is separate + non-fatal
            ok "Merged"
            ;;
        *) err "Unknown state" ;;
    esac

    # ─── Sync ─────────────────────────────────────────────────────────────────
    # sync::main_branch handles both the primary tree (checkout main; pull) and a
    # linked worktree (pull main in the primary tree — a checkout here would abort
    # under set -e because main is already checked out elsewhere). See git-common.sh.
    sync::main_branch

    # ─── Branch cleanup (best-effort — a merged PR must NEVER report failure) ──
    # --delete-branch was dropped above: it deletes the local branch too, which
    # fails (and, under set -e, aborts the whole script) when another worktree has
    # the branch checked out — reporting an already-merged PR as failed. Cleanup is
    # decoupled and non-fatal here instead.
    local head; head=$(gh pr view "$num" --json headRefName -q .headRefName 2>/dev/null || true)
    if [[ -n "${head:-}" && "$head" != "$m" ]]; then
        git push origin --delete "$head" &>/dev/null \
            && ok "Deleted remote branch $head" \
            || warn "Remote branch $head not deleted (already gone?)"
        if git branch -D "$head" &>/dev/null; then
            ok "Deleted local branch $head"
        else
            local wt; wt=$(git worktree list --porcelain \
                | awk -v b="branch refs/heads/$head" '/^worktree /{p=$2} $0==b{print p}' || true)
            warn "Local branch $head kept${wt:+ (worktree $wt holds it — remove manually)}"
        fi
    fi

    dim "$(git log --oneline -5 | sed 's/^/  /')"
    banner "Done"
}

merge::main "$@"
