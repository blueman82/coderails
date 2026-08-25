#!/bin/bash
# post_evals_smoke_run.sh — freeze-time smoke recorder: smoke_run,
# _run_recorded (the sandboxed executor), _is_environmental_rc (the shared
# environmental-vs-content exit-code taxonomy).
# Split out of post_evals.sh to keep files under the repo LOC ceiling.
# Sourced by post_evals.sh — not meant to be run directly.
# Note: no set -euo pipefail — sourced; functions return exit codes.


# post_evals::smoke_run <evals_json_path>
# EXECUTES every scripted eval's cmd and negative_control and writes the
# observed exit codes and output excerpts into the file's `smoke` objects,
# overwriting whatever was there.
#
# WHY THIS EXISTS SEPARATELY FROM validate_smoke: validate_smoke checks
# recorded exit codes, which is necessary but not sufficient, because the agent
# writes those numbers. An agent that freezes a cmd for a script it merely
# INTENDS to create records the code it EXPECTS ("1 — the assertion fails until
# I build it"), never having run the command, and walks straight through a
# checker that trusts the field. That is exactly how the real instance-1 defect
# happened, and it is why rule 5 in SKILL.md already says a neutral script
# computes the result and the orchestrator never hand-writes it. This applies
# rule 5 to smoke evidence: run the commands, record what happened.
#
# Recording is NOT judging. This function returns 0 whenever it successfully
# ran the commands and wrote the file, even when what it observed is damning —
# refusing is validate_smoke's job. Keeping the two apart means the recorded
# evidence is the same whether or not anyone later gates on it.
#
# Commands run through _run_recorded's 10s group-killing cap, so a hanging
# command cannot hang the freeze: 127 (not found), 142 (timeout) and signal
# deaths fall out of the real run instead of being typed in by hand.
post_evals::smoke_run() {
    local path="$1"

    if ! command -v jq >/dev/null 2>&1; then
        printf 'post_evals: jq is required to record smoke evidence and was not found\n' >&2
        return 1
    fi

    if [[ ! -f "$path" ]] || ! jq -e . "$path" >/dev/null 2>&1; then
        printf 'post_evals: file not found or invalid JSON: %s\n' "$path" >&2
        return 1
    fi

    # Guard id TYPE. The schema (SKILL.md) defines id as a string ("E1"); the
    # cmd/negative_control lookups below are `select(.id == $id)` against a
    # shell string from `--arg`, which never matches a JSON number. Without
    # this guard a numeric id makes cmd/nc silently empty, so nothing executes
    # and this function still records `smoke: null` and returns 0 — recording
    # success for evidence that was never run. Fail closed instead.
    local bad_id_type
    bad_id_type=$(jq -r '[.evals[]? | select(.mode == "scripted") | select((.id | type) != "string")] | length > 0' "$path")
    if [[ "$bad_id_type" == "true" ]]; then
        printf 'post_evals: smoke_run: a scripted eval has a non-string id (schema requires id to be a string) — refusing.\n' >&2
        return 1
    fi

    local ids
    ids=$(jq -r '[.evals[]? | select(.mode == "scripted") | .id] | .[]' "$path")
    [[ -z "$ids" ]] && return 0

    local id
    while IFS= read -r id; do
        [[ -z "$id" ]] && continue

        local cmd nc
        cmd=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .cmd // ""' "$path")
        nc=$(jq -r --arg id "$id" '.evals[] | select(.id == $id) | .negative_control // ""' "$path")

        local cmd_rc cmd_out nc_rc nc_out
        cmd_rc=""; cmd_out=""; nc_rc=""; nc_out=""

        if [[ -n "$cmd" ]]; then
            cmd_out=$(post_evals::_run_recorded "$cmd")
            cmd_rc="${cmd_out%%:*}"
            cmd_out="${cmd_out#*:}"
        fi
        if [[ -n "$nc" ]]; then
            nc_out=$(post_evals::_run_recorded "$nc")
            nc_rc="${nc_out%%:*}"
            nc_out="${nc_out#*:}"
        fi

        # Write in place via a temp file — a partial write must never leave a
        # corrupted artifact behind.
        local tmp
        tmp=$(mktemp) || return 1
        if ! jq --arg id "$id" \
               --argjson crc "${cmd_rc:-null}" --argjson nrc "${nc_rc:-null}" \
               --arg cout "$cmd_out" --arg nout "$nc_out" '
            (.evals[] | select(.id == $id) | .smoke) = {
                cmd_exit: $crc,
                negative_control_exit: $nrc,
                cmd_output: $cout,
                negative_control_output: $nout
            }' "$path" > "$tmp"; then
            rm -f "$tmp"
            printf 'post_evals: failed to record smoke evidence for eval %s in %s\n' "$id" "$path" >&2
            return 1
        fi
        if ! mv "$tmp" "$path"; then
            rm -f "$tmp"
            printf 'post_evals: failed to write %s\n' "$path" >&2
            return 1
        fi
    done <<< "$ids"

    return 0
}

# post_evals::_run_recorded <command> [timeout_secs] [cwd]
# Runs <command> under a wall-clock cap (default 10s) and echoes
# "<exit_code>:<output excerpt>". stdout and stderr are merged — the tell for a
# broken instrument is usually on stderr (a module-resolution error, a
# not-found message), so dropping it would discard the evidence a human needs.
# [timeout_secs] defaults to 10 (unchanged freeze-time behaviour — every
# existing caller passes one arg). [cwd], if given, runs <command> there
# instead of the caller's own working directory — needed by smoke_verify,
# which must execute inside its detached worktree, not wherever the merge
# gate happens to be invoked from.
#
# THE CAP KILLS THE PROCESS GROUP, not just the direct child. The earlier
# exec-based idiom (`perl -e 'alarm shift; exec ...'`) delivered SIGALRM only
# to the process perl became: a grandchild — the sleep inside `bash hang.sh`,
# a test runner's worker — was never signalled, got reparented to init, and
# kept the inherited stdout pipe open, so the caller's command substitution
# blocked until the orphan exited. Correct exit code (142), broken latency
# bound (observed 30s for a 10s cap). Since check 10 runs this on the merge
# hot path, the bound is load-bearing: the child is made its own process
# group leader (setpgrp) and the alarm handler KILLs the negative PGID, which
# takes the grandchildren and closes the pipe. Timeout still reports 142,
# the documented sentinel, regardless of the KILL. Honest caveat: a
# descendant that detaches into its own session (a daemonizing server)
# escapes the group kill and can still hold the pipe open — the cap bounds
# every ordinary forking shape, not a deliberate daemon.
#
# _run_formula keeps the old exec idiom deliberately: it redirects the
# command's output to /dev/null, so an orphan cannot hold its pipe open and
# the single-process alarm is a sufficient bound there.
#
# STDIN IS REDIRECTED FROM /dev/null, and that is a gate correctness
# property, not tidiness. Every PRODUCTION caller runs this inside a
# `while IFS= read -r ... done <<< "$list"` loop — smoke_run over `$ids`,
# validate_smoke_execution over `$idxs`, smoke_verify over `$indices` — so
# the loop body's stdin IS
# the remaining eval list. An eval whose cmd reads stdin (`cat`, `xargs`,
# a test runner that drains it) consumed that list, and the loop then
# exited early having silently skipped every subsequent eval — while still
# returning 0. In smoke_run that lost the smoke evidence (check 9 catches
# the absence downstream, so it failed closed). In validate_smoke_execution
# (check 10) and smoke_verify it FAILED OPEN: the skipped evals were never
# executed, so a vacuous negative_control that the gate refuses on its own
# (`negative_control: "true"`, "a control that passes proves nothing") was
# silently accepted when any earlier eval ate stdin. Verified by A/B: the
# same artifact exits 1 alone and 0 behind a stdin-consuming eval. An eval
# command needing real stdin should pipe it in explicitly.
#
# [timeout_seconds] exists for the test suite (a real 10s stall per run is
# too slow to assert on); production callers pass nothing and get 10.
#
# The excerpt keeps BOTH ENDS, not just the tail, because the diagnostic line
# sits at a different end depending on the failure. Measured against real
# output from this repo: a test runner's verdict is in the last few lines
# (post_evals.test.sh emits 10886 chars, PASS last), but a node stack trace
# puts "Cannot find module" in the FIRST line and 900+ chars of stack frames
# after it — a tail-only excerpt keeps the frames and discards the error,
# losing exactly the module-resolution tell SKILL.md names. Capping both ends
# also bounds the artifact against a chatty runner.
post_evals::_run_recorded() {
    local command_text="$1" timeout_secs="${2:-10}" cwd="${3:-}" out rc
    # shellcheck disable=SC2016 # single-quoted Perl source, not a shell expansion
    local -r _pg_kill_perl='
        my $t = shift; my $cmd = shift;
        my $pid = fork();
        exit 127 unless defined $pid;
        if ($pid == 0) { setpgrp(0, 0); exec "/bin/bash", "-c", $cmd; exit 127; }
        my $timed_out = 0;
        local $SIG{ALRM} = sub { $timed_out = 1; kill "KILL", -$pid; };
        alarm $t;
        waitpid($pid, 0);
        alarm 0;
        exit 142 if $timed_out;
        exit(($? & 127) ? 128 + ($? & 127) : $? >> 8);
    '
    if [[ -n "$cwd" ]]; then
        # A cd failure here (worktree vanished between `git worktree add` and
        # this call — a race or external rm) must NOT collapse to rc=1: rc=1 is
        # a legitimate content-failure exit, and _is_environmental_rc doesn't
        # cover it, so on the negative_control leg (where rc=1 reads as a pass)
        # a cd failure would fail OPEN. Map "could not enter the dir to run" to
        # 127 (command-not-found), which _is_environmental_rc DOES treat as
        # "never executed" — the honest classification for a command that never
        # ran. The `|| { echo ...; exit 127; }` runs inside the subshell.
        out=$(cd "$cwd" 2>/dev/null || { printf 'cd-failed: %s' "$cwd"; exit 127; }
              perl -e "$_pg_kill_perl" "$timeout_secs" "$command_text" </dev/null 2>&1)
    else
        out=$(perl -e "$_pg_kill_perl" "$timeout_secs" "$command_text" </dev/null 2>&1)
    fi
    rc=$?
    out=$(printf '%s' "$out" | tr '\n' ' ')
    if (( ${#out} > 500 )); then
        out="${out:0:250} [...] ${out: -250}"
    fi
    printf '%s:%s' "$rc" "$out"
}

# post_evals::_is_environmental_rc <exit_code>
# True when an exit code signals the command did not run to a verdict:
# 126 permission denied, 127 command not found, 142 our timeout sentinel,
# and >=128 signal deaths.
#
# validate_discriminating applies the same taxonomy to its fixtures legs but
# deliberately keeps its own inline checks rather than calling this: it reports
# not-found, timeout and crash with three distinct messages naming both legs'
# exit codes, which a shared boolean cannot express. The duplication is the
# price of those diagnostics. If the taxonomy changes, both must change.
post_evals::_is_environmental_rc() {
    local rc="$1"
    [[ "$rc" == "126" || "$rc" == "127" ]] && return 0
    [[ "$rc" =~ ^[0-9]+$ ]] && (( rc >= 128 )) && return 0
    return 1
}
