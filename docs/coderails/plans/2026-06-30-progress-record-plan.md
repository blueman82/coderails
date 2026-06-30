**For agentic workers:** REQUIRED SUB-SKILL: Use `coderails:subagent-driven-development` (recommended) or `coderails:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

# Independent-Review Truth Seam (durable PR artifact + fail-closed merge gate) — Implementation Plan

**Goal:** Review truth is a GitHub-visible, SHA-bound PR comment that `/merge` verifies fail-closed — not ephemeral chat output and not a self-authored local boolean.

**Architecture:** A new coderails-owned `/coderails:post-review` validates a structured review summary and posts a machine-marked, SHA-bound PR comment (the truth authority). `/merge` fetches live PR comments and requires a marker matching the current head SHA before merging, fail-closed. Marker construction and matching share a single source (`scripts/lib/review-artifact.sh`). Loop and non-loop use the same artifact gate.

**Intentional spec/plan divergences (planning-sequence refinements, NOT accidental):** (a) this plan adds `scripts/lib/review-artifact.sh`, overriding the spec's "no new lib" bias because marker SSOT outranks it; (b) this plan defers the spec's Stop guard and universal-ledger enforcement. Both are deliberate stress-test outcomes — a reviewer seeing the spec still describe the guard should read this slice as a scoped first implementation of the approved design, not a deviation.

**Scope decision (from the planning-sequence stress-test):** This slice ships the **durable artifact + merge gate** — the direct repair for the verified flaw (ephemeral review output). It **defers** the universal `progress.json` Stop guard: the stress-test's Red Team showed a blocking Stop hook on every run reintroduces the ceremony tax this project set out to reduce, and its value (a file exists and is session-owned) does not justify a block in the first slice. The verified flaw was ephemeral review output, not missing ledger enforcement. `progress.json.review` remains an optional cache, never a dependency or authority. Ledger enforcement can be added later **with evidence** that it is being harmfully skipped.

## Global Constraints

- Source spec: `docs/coderails/specs/2026-06-30-progress-record-design.md`. Every requirement traces there.
- Bash hook convention (verbatim from AGENTS.md): read stdin via `IFS= read -r -d '' -t 5 input || true`; block via stdout `permissionDecision: deny` for PreToolUse, `exit 2` + stderr for Stop; append a greppable `key=value` line to `$CLAUDE_DISCIPLINE_LOG`; guard scripts do NOT use `set -euo pipefail`.
- The local `progress.json.review` block is a **cache/index, never authority**. No code path may treat it as proof of review. `/merge` authority is live GitHub state only.
- `/merge` fails **closed**: a `gh` fetch failure or a no-match → block. NO fallback to local `review.summary_posted`.
- Marker is parsed **narrowly-anchored**, not loose grep: literal `<!-- coderails-review-summary `, version exactly `v1`, `pr` exactly current PR number, `head_sha` exactly current `headRefOid`, trailing ` -->`. Unknown version → no-match → fail-closed.
- coderails does NOT own `/pr-review-toolkit:review-pr` (external). All durable-artifact behaviour lives in the new owned `/coderails:post-review`.
- **Test location: ALL `*.test.sh` go in `hooks/scripts/tests/`** — `run_all.sh` discovers `*.test.sh` in that directory only (verified: `for test_file in *.test.sh`). This holds EVEN FOR tests of code under `scripts/` (e.g. `git-common.sh`, `merge.sh`, `post_review.sh`): the existing `git-common.test.sh` already lives in `hooks/scripts/tests/` though `git-common.sh` is under `scripts/lib/`. Do NOT create `scripts/tests/` — a test there is never run.
- Mechanics (marker build, SHA stamp, cache write, grammar validation) are **script-backed** (`scripts/post_review.sh`) for determinism; the command markdown handles only the agent-mediated summary hand-off.
- Honest ceiling (do not re-open): the gate proves an auditable, SHA-bound artifact exists, never that the review was substantive. `/post-review` validates summary *structure*, not *provenance*.

---

## Task 0 — Marker SSOT lib (single source for writer and reader)

**Files:** `scripts/lib/review-artifact.sh` (create), `hooks/scripts/tests/review-artifact.test.sh` (create).

**Why first / why a new lib:** the marker is built by `/post-review` (writer) and matched by `/merge` (reader). Two literal constructions would drift (stress-test failure mode 2 — silent gate failure). This is the one place the spec's "no new lib" bias is correctly overridden: SSOT outranks it. One constructor, both sides source it.

**Interface produced (for Tasks 2 and 4):**
- `REVIEW_ARTIFACT_MARKER_VERSION` — constant, currently `v1`.
- `review_artifact::marker <pr> <head_sha>` — echoes exactly `<!-- coderails-review-summary v1 pr=<pr> head_sha=<head_sha> -->`.
- `review_artifact::matches_marker <line> <pr> <head_sha>` — exit 0 iff `<line>` is **exactly equal** to the marker for `<pr>`/`<head_sha>` at the current version. Use string equality, NOT substring: `[ "$line" = "$(review_artifact::marker "$pr" "$head_sha")" ]`. Substring matching (`grep -F`) is wrong — `junk <!-- … --> junk` must FAIL. An unknown/other version never matches → fail-closed.

**Steps (TDD per `coderails:test-driven-development`):**
- [ ] Write `review-artifact.test.sh` failing cases: `marker 123 abc` equals the exact literal; `matches_marker "<that exact line>" 123 abc` → 0; wrong pr → 1; wrong sha → 1; a hand-edited `v2` marker line → 1; a line missing the trailing ` -->` → 1; **a line with junk prefix/suffix around the exact marker (`junk <!-- … --> junk`) → 1** (proves exact-equality, not substring).
- [ ] Run; watch fail.
- [ ] Implement: `marker` is a single `printf`; `matches_marker` does string equality `[ "$line" = "$(review_artifact::marker "$pr" "$head_sha")" ]` (NOT `grep -F` — substring would pass the junk-wrapped case).
- [ ] Run; watch pass.
- [ ] Commit.

**Verify-criteria:** `bash hooks/scripts/tests/review-artifact.test.sh` passes; the literal `v2` line fails to match (fail-closed on version).

---

## Task 1 — Summary grammar + validator (the weakest seam, built first)

**Files:** `scripts/post_review.sh` (create), `hooks/scripts/tests/post_review.test.sh` (create).

**Why first:** the chat→post-review hand-off is the spec's weakest seam — the one place a hollow artifact can enter. Build its anti-placeholder validator before anything consumes it.

**Interface produced (for Task 2, 3):**
- `post_review::validate_summary <file>` — reads a summary body from `<file>`; exit 0 if it satisfies the grammar, exit 1 + stderr reason otherwise.
- **Grammar (concrete, testable):** the body MUST contain either the line `## No findings`, OR all three headings `## Critical`, `## Important`, `## Suggestions`, each followed (before the next `##` or EOF) by at least one line matching `^- ` (a bullet) or the literal line `None`. A body with a heading but an empty section fails. A one-line "review done" fails.

**Steps (TDD per `coderails:test-driven-development`):**
- [ ] Write `post_review.test.sh` failing cases: (a) `## No findings` → pass; (b) all three headings each with `- bullet` → pass; (c) all three headings, one with `None` → pass; (d) `## Critical` with empty section → fail; (e) one-line "review done" → fail; (f) missing `## Suggestions` → fail.
- [ ] Run it; watch all fail (function undefined).
- [ ] Implement `post_review::validate_summary` in `scripts/post_review.sh` with the grammar above (awk/grep section-scan; no `set -e` issues — function returns exit code).
- [ ] Run; watch pass.
- [ ] Commit.

**Verify-criteria:** `bash hooks/scripts/tests/post_review.test.sh` → all 6 assertions pass; a body of literal `review done` exits 1.

---

## Task 2 — Best-effort cache write (`progress.json.review`)

**Files:** `scripts/post_review.sh` (modify — same file as Task 1), `hooks/scripts/tests/post_review.test.sh` (modify).

**Interface consumed:** `post_review::validate_summary` (Task 1); `review_artifact::marker` (Task 0 — the SOLE marker constructor; do NOT re-type the literal here).
**Interface produced (for Task 3):**
- `post_review::write_cache <progress_path> <pr> <head_sha> <url> <author> <iso8601>` — best-effort: if `<progress_path>` exists, writes the `review` cache block via `jq`; if absent, prints a warning to stderr and returns 0 (cache is never required — the PR artifact is the authority).

**Steps (TDD):**
- [ ] Write failing tests: `write_cache` on an existing stub produces a `review` object with `ran:true/pr/head_sha/summary_url/summary_author/posted_at/summary_posted:true`, leaving the six base fields untouched; `write_cache` on a NON-existent path warns to stderr and returns 0 (does not create the file, does not error).
- [ ] Run; watch fail.
- [ ] Implement `post_review::write_cache` when the file exists via **temp-file + mv (NOT in-place — shell jq has no safe in-place mode):** `jq '.review = {…}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"` (clean up `$f.tmp` on jq failure, leaving the original intact). The absent branch warns to stderr + `return 0`. Source `review-artifact.sh` for any marker need; do not construct the marker here.
- [ ] Run; watch pass.
- [ ] Commit.

**Verify-criteria:** after `write_cache` on a stub, `jq '.review.head_sha'` == the passed SHA and `jq '.status'` unchanged; `write_cache /nonexistent/progress.json …` exits 0 with a stderr warning and creates no file.

---

## Task 3 — `/coderails:post-review` command

**Files:** `commands/post-review.md` (create).

**Interface consumed:** `post_review::validate_summary` (Task 1), `review_artifact::marker` (Task 0), `post_review::write_cache` (Task 2); `agentic_loop_path.sh` (existing) for the optional progress.json path; `gh api …/issues/<PR>/comments`, `gh repo view --json nameWithOwner`, `gh pr view --json headRefOid` (existing CLI).

**Independence from `progress.json` (stress-test fix):** the PR artifact is posted **regardless** of whether a `progress.json` exists. The cache write (`write_cache`) is best-effort — a missing ledger warns and continues, never blocks the post. The truth seam does not depend on the ledger.

**This task is prose (a command), verified by inspection — no `.test.sh`.** Per spec, the agent-mediated hand-off lives here; mechanics delegate to `post_review.sh`.

**Command contract (write verbatim into the .md):**
- Frontmatter `allowed-tools`: `Bash(gh pr view*)`, `Bash(gh api*)`, `Bash(gh repo view*)`, `Bash(./scripts/post_review.sh*)`, `Bash(cat*)`, the config-resolve `!` substitution line used by other commands. (NOT `gh pr comment` — the body posts via `gh api` to capture the comment URL/metadata.)
- argument-hint: `<PR#>`.
- Body steps: (1) the agent writes the review-pr findings into a temp summary file, structured per the Task-1 grammar — **explicitly instruct: if review-pr produced no findings, write `## No findings`; never fabricate**; to raise the floor against hollow summaries (stress-test fix 1), **instruct the agent to include review-pr's own finding counts** so a thin summary is visibly inconsistent with the review that ran; (2) run `scripts/post_review.sh validate <tmp>` — abort with the reason if it exits 1; (3) resolve head SHA (`gh pr view <PR> --json headRefOid -q .headRefOid`); (4) build marker via `review_artifact::marker` + prepend to the summary; (5) **post via `gh api` (NOT bare `gh pr comment`), because the post must return the new comment's URL/id/author/timestamp deterministically:** `gh api "repos/{owner}/{repo}/issues/<PR>/comments" -f body=@<body-file> --jq '{url:.html_url,id:.id,author:.user.login,created:.created_at}'` (resolve `{owner}/{repo}` via `gh repo view --json nameWithOwner -q .nameWithOwner`); (6) pass the returned `url`/`author`/`created` into `post_review.sh write-cache` (best-effort; warns if no progress.json); (7) report the posted URL.

**Steps:**
- [ ] Write `commands/post-review.md` with the contract above (model after `commands/push.md` frontmatter style).
- [ ] Add the `validate`/`write-cache` subcommand dispatch to `scripts/post_review.sh` (a `case "$1"` at the bottom calling the Task 1–2 functions).
- [ ] Inspect: frontmatter `allowed-tools` covers every Bash call the body makes; the "never fabricate / write `## No findings`" instruction is present.

**Verify-criteria:** grep `commands/post-review.md` shows the `## No findings` anti-fabrication instruction and a `validate` call before the `gh api …/comments` call (validation precedes posting). The frontmatter `allowed-tools` lists `gh api`/`gh repo view`, NOT `gh pr comment`.

---

## Task 4 — `git-common.sh` gate helpers

**Files:** `scripts/lib/git-common.sh` (modify — add after the `pr::*` block, ~line 47), `hooks/scripts/tests/git-common.test.sh` (modify).

**Interface consumed:** `review_artifact::matches_marker` (Task 0 — the SOLE matcher; do NOT re-type the marker literal here). `git-common.sh` sources `scripts/lib/review-artifact.sh`.
**Interface produced (for Task 5):**
- `pr::head_sha <num>` — `gh pr view "$num" --json headRefOid -q .headRefOid 2>/dev/null`; echoes empty on `gh` failure.
- `pr::has_coderails_review_for_head <num> <sha>` — fetches `gh pr view "$num" --json comments -q '.comments[].body'`; **splits each comment body into lines** (the marker is a single line; iterate `while IFS= read -r line` over the fetched output) and returns exit 0 iff some line satisfies `review_artifact::matches_marker` for `<num>`/`<sha>`. On `gh` failure (fetch returns non-zero / empty) → exit 1 (fail-closed). Distinguish fetch-failure from no-match via a distinct exit code (e.g. 2 = fetch-failed, 1 = fetched-but-no-match) so Task 5 can message them differently.

**Steps (TDD — stub `gh` the way existing git-common tests do):**
- [ ] Write failing tests: stubbed `gh` returning a comment with a matching marker → exit 0; different SHA → exit 1; `v2` marker → exit 1 (fail-closed via the SSOT matcher); no comments → exit 1; `gh` non-zero (fetch failure) → distinct fail-closed signal (exit code/stderr) separable from no-match.
- [ ] Run; watch fail.
- [ ] Implement both helpers, delegating the match to `review_artifact::matches_marker` (no literal marker in this file).
- [ ] Run; watch pass.
- [ ] Commit.

**Verify-criteria:** `bash hooks/scripts/tests/git-common.test.sh` passes including the new cases; a `v2`-marker comment yields exit 1.

---

## Task 5 — `/merge` SHA-match artifact gate (fail-closed)

**Files:** `scripts/merge.sh` (modify — insert in the `OPEN` case before `gh pr merge "$num" --merge`, ~line 46), `hooks/scripts/tests/merge.test.sh` (create — new file in the runner's dir; keeps merge-gate tests distinct from the `git-common.test.sh` helper unit tests).

**Interface consumed:** `pr::head_sha`, `pr::has_coderails_review_for_head` (Task 4).

**Steps (TDD):**
- [ ] Write failing tests: with stubbed helpers — merge proceeds when `has_coderails_review_for_head` is true for the current head; merge **aborts with the "no artifact" message** when the fetch succeeds but no marker matches; merge **aborts with the distinct "GitHub fetch failed" message** when `pr::head_sha` is empty or the comments fetch fails (gh failure). Both fail-closed; different messages.
- [ ] Run; watch fail.
- [ ] Implement: in the `OPEN` branch, before merge — `sha=$(pr::head_sha "$num")`; `[[ -z "$sha" ]] && err "GitHub fetch failed — could not resolve PR head SHA. Retry, or check gh auth/network."` (fetch-failure remedy); then `pr::has_coderails_review_for_head "$num" "$sha"`, branching its two failure signals: fetch-failure → the same "GitHub fetch failed" message; clean no-match → `err "No coderails review artifact for current head $sha — run /coderails:post-review after /pr-review-toolkit:review-pr (or add a 'gh pr merge' permission to bypass)."`. Only the existing `protected`/approval block and this gate precede `gh pr merge`. **No fallback to `progress.json.review`.**
- [ ] Run; watch pass.
- [ ] Commit.

**Verify-criteria:** merge test passes; a fetched-but-no-marker PR is refused with the "no artifact / run post-review" message; a gh-failure path is refused with the distinct "GitHub fetch failed / retry" message; no code path reads `progress.json.review` to allow a merge.

---

## Task 6 — `/workflow` + loop-symmetry wiring (insert `/post-review`)

**Files:** `commands/workflow.md` (modify), `skills/agentic-loop/SKILL.md` (modify).

**This task is prose, verified by inspection.**

**Steps:**
- [ ] `workflow.md`: insert `/coderails:post-review <PR#>` as a new step at the **end of Phase 3** ("Push + Adversarial Review", which currently ends after the `/pr-review-toolkit:review-pr all` at step 2 and `/simplify` at step 2c, ~line 148–158) — i.e. after review/simplify complete and **before Phase 4 "Ship-It" (the interactive pause, ~line 159)**. This places the durable artifact on the PR before the ship-it pause. Also add `SlashCommand(/coderails:post-review)` to the `allowed-tools` (line 2). Update the prose ordering so the chain reads `review-pr → post-review → (Phase 4 ship-it pause) → /merge`.
- [ ] `agentic-loop/SKILL.md`: at Phase 4b, after the `review-pr` invocation, add the instruction to run `/coderails:post-review <PR#>` so the loop posts the same SHA-bound artifact (loop symmetry — same merge gate applies on both paths).
- [ ] Inspect: grep `workflow.md` shows post-review between review and merge; `SKILL.md` Phase 4b references `/coderails:post-review`.

**Verify-criteria:** `grep -n 'post-review' commands/workflow.md skills/agentic-loop/SKILL.md` shows the insertions in both.

---

## Task 7 — Optional `/prep` ledger stub (NON-BLOCKING, nothing depends on it)

**Files:** `commands/prep.md` (modify).

**This task is prose, verified by inspection.** Deferred-guard note: this writes a durable run record for its own sake. **Nothing** — not `/post-review`, not `/merge` — depends on it. It is a nicety, not a gate. No Stop hook enforces it (the guard was dropped per the scope decision).

**Steps:**
- [ ] `prep.md`: after branch creation, before Jira, add a Git-operations step that writes a `progress.json` stub. The path comes from `bash "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.sh"` (the model must NOT compute the path). Stub fields: `schema_version:1`, `session_id`, `status:"in-progress"`, `created` (ISO8601), `authorising_prompt_raw`, `work:[]`, `review:{ran:false,...nulls}`. State in the command prose that this step is best-effort: a failure to write it does **not** abort `/prep`.
- [ ] Inspect: `prep.md` shows the `agentic_loop_path.sh` call (not a hand-computed path) and the "non-blocking / does not abort prep" wording.

**Verify-criteria:** `grep -n 'agentic_loop_path.sh' commands/prep.md` shows the path-resolution call; the surrounding prose marks the step non-blocking.

---

## Task 8 — Docs: hook map + command table

**Files:** `AGENTS.md` (modify), `docs/REFERENCE.md` (modify), `README.md` (modify if it carries the command/hook tables).

**This task is prose, verified by inspection.**

**Steps:**
- [ ] `AGENTS.md`: add `/coderails:post-review` to the workflow command architecture section and the skills↔hooks seam note (post-review → produces the SHA-bound artifact the `/merge` gate requires; document the new gate behaviour on `merge.sh`).
- [ ] `AGENTS.md` enforcement-ceilings section: add the post-review provenance ceiling verbatim from the spec (validates structure, not provenance; auditable not cryptographic). Add the follow-up note: the `review-pr` arm of `enforce_pr_workflow` is expected to demote to a nudge once this gate is live + verified (ordering constraint — never before).
- [ ] `docs/REFERENCE.md` + `README.md`: add `/coderails:post-review` to the command table.
- [ ] Inspect: the sources (AGENTS command section, REFERENCE, README) all name `post-review`.

**Verify-criteria:** `grep -l 'post-review' AGENTS.md docs/REFERENCE.md README.md` non-empty for each. **(No `progress_record_guard` doc work — the guard is deferred out of this slice.)**

---

## Follow-up (NOT in this plan — recorded per spec)

After this ships and is verified live: re-evaluate the `review-pr` arm of `enforce_pr_workflow` and likely demote it from block to nudge (the artifact gate enforces review transitively). **Ordering constraint: only after `/post-review` + the merge gate are live and verified** — never before, or a no-review-enforcement window opens. Tracked as a separate change.
