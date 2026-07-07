#!/bin/bash
# End-to-end test for the workflow-audit mechanical pipeline: scan_transcripts.sh
# piped into cluster_ngrams.sh over a synthetic corpus. Exercises the full
# scan|cluster pipeline (not each script's unit behaviour in isolation — see
# scan_transcripts.test.sh / cluster_ngrams.test.sh for that), the privacy
# invariant end-to-end, the no-approval/no-creation property, and residual
# edge cases flagged during WU1 review but not yet pinned by a test.
set -u
set -o pipefail
SCAN_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scan_transcripts.sh"
CLUSTER_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/cluster_ngrams.sh"
REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
fails=0
check() { # desc, expected, actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected: %s\n      actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_contains() { # desc, haystack, needle
  if printf '%s' "$2" | grep -qF "$3"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected to contain: %s\n      actual: %s\n' "$1" "$3" "$2"; fails=$((fails+1)); fi
}
check_not_contains() { # desc, haystack, needle
  if printf '%s' "$2" | grep -qF "$3"; then
    printf 'FAIL - %s\n      must NOT contain: %s\n      actual: %s\n' "$1" "$3" "$2"; fails=$((fails+1))
  else printf 'ok   - %s\n' "$1"
  fi
}

# Builds one synthetic transcript file at $1 with the given repeated tool-use
# sequence (git log / git push / prime skill), plus one bare-string user
# content record and one bookkeeping record type — mirrors a real session's
# mixed record shapes without depending on any real transcript.
make_session() {
  local file="$1"
  {
    printf '{"type":"custom-title","title":"synthetic e2e session"}\n'
    printf '{"type":"user","message":{"role":"user","content":"a bare string content field"},"timestamp":"2026-07-06T10:00:00Z"}\n'
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"git log --oneline"}}]},"timestamp":"2026-07-06T10:00:01Z"}\n'
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"git push origin"}}]},"timestamp":"2026-07-06T10:00:02Z"}\n'
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Skill","input":{"skill":"prime"}}]},"timestamp":"2026-07-06T10:00:03Z"}\n'
    printf '{"type":"last-prompt","prompt":"resume cache text that must never be read"}\n'
  } > "$file"
}

# ═══════════════════════════════════════════════════════════════════════════
# 1. Pipeline produces a known cluster from a synthetic multi-session corpus
# ═══════════════════════════════════════════════════════════════════════════
TMP1=$(mktemp -d)
trap 'rm -rf "$TMP1"' EXIT
mkdir -p "$TMP1/proj-e2e-a" "$TMP1/proj-e2e-b" "$TMP1/proj-e2e-c"
make_session "$TMP1/proj-e2e-a/e2e00000-0000-0000-0000-00000000000a.jsonl"
make_session "$TMP1/proj-e2e-b/e2e00000-0000-0000-0000-00000000000b.jsonl"
make_session "$TMP1/proj-e2e-c/e2e00000-0000-0000-0000-00000000000c.jsonl"

PIPELINE_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP1" bash "$SCAN_SCRIPT" --all-projects --days 36500 | bash "$CLUSTER_SCRIPT" --min-sessions 3)
PIPELINE_RC=$?
check "e2e pipeline (scan|cluster) exits 0" "0" "$PIPELINE_RC"

TRIGRAM=$(printf '%s' "$PIPELINE_OUT" | jq -c '.clusters[] | select(.n == 3 and .ngram == ["Bash:git log","Bash:git push","Skill:prime"])')
check "e2e pipeline surfaces the expected trigram cluster" '["Bash:git log","Bash:git push","Skill:prime"]' \
  "$(printf '%s' "$TRIGRAM" | jq -c '.ngram')"
check "e2e trigram cluster count == 3" "3" "$(printf '%s' "$TRIGRAM" | jq -r '.count')"
check "e2e trigram cluster sessions == exact sorted set of the 3 synthetic session ids" \
  '["e2e00000-0000-0000-0000-00000000000a","e2e00000-0000-0000-0000-00000000000b","e2e00000-0000-0000-0000-00000000000c"]' \
  "$(printf '%s' "$TRIGRAM" | jq -c '.sessions | sort')"

# ═══════════════════════════════════════════════════════════════════════════
# 2. Sentinel privacy (negative control): a secret planted in a Bash command's
#    arguments must survive in the raw fixture but never reach scan or cluster
#    output — only the whitelisted two-token head does.
# ═══════════════════════════════════════════════════════════════════════════
TMP2=$(mktemp -d)
mkdir -p "$TMP2/proj-sent-a" "$TMP2/proj-sent-b" "$TMP2/proj-sent-c"
make_sentinel_session() {
  local file="$1"
  {
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"curl -H Authorization:SENTINEL_sk_live_99xyz https://api.example.com/v1/thing"}}]},"timestamp":"2026-07-06T11:00:00Z"}\n'
    printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read"}]},"timestamp":"2026-07-06T11:00:01Z"}\n'
  } > "$file"
}
SENT_FILE_A="$TMP2/proj-sent-a/sent0000-0000-0000-0000-00000000000a.jsonl"
SENT_FILE_B="$TMP2/proj-sent-b/sent0000-0000-0000-0000-00000000000b.jsonl"
SENT_FILE_C="$TMP2/proj-sent-c/sent0000-0000-0000-0000-00000000000c.jsonl"
make_sentinel_session "$SENT_FILE_A"
make_sentinel_session "$SENT_FILE_B"
make_sentinel_session "$SENT_FILE_C"

# Prove the sentinel is genuinely present in the raw fixture (input sanity —
# a vacuous pass would occur if the fixture never contained it in the first place).
check_contains "sentinel IS present in the raw fixture (input sanity, proves detector could fire)" \
  "$(cat "$SENT_FILE_A")" "SENTINEL_sk_live_99xyz"

SCAN_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP2" bash "$SCAN_SCRIPT" --all-projects --days 36500)
check_not_contains "sentinel ABSENT from scan output" "$SCAN_OUT" "SENTINEL_sk_live_99xyz"
check_contains "scan output still carries the whitelisted two-token head" "$SCAN_OUT" '"head":"curl -H"'

CLUSTER_OUT=$(printf '%s' "$SCAN_OUT" | bash "$CLUSTER_SCRIPT" --min-sessions 3)
check_not_contains "sentinel ABSENT from cluster output" "$CLUSTER_OUT" "SENTINEL_sk_live_99xyz"
check_contains "cluster output surfaces the head-only event string" "$CLUSTER_OUT" "Bash:curl -H"
rm -rf "$TMP2"

# ═══════════════════════════════════════════════════════════════════════════
# 3. No approval => no creation: the mechanical pipeline (scan+cluster) alone
#    must never create a SKILL.md anywhere, under a sandboxed HOME, and must
#    never create a new directory under the repo's own skills/. This pins that
#    skill creation is gated entirely behind the SKILL.md's human-approval
#    step (workflow-audit/SKILL.md section 6) — the pipeline scripts have no
#    creation capability at all.
# ═══════════════════════════════════════════════════════════════════════════
SANDBOX_HOME=$(mktemp -d)
mkdir -p "$SANDBOX_HOME/.claude/projects/proj-noapprove"
make_session "$SANDBOX_HOME/.claude/projects/proj-noapprove/noap0000-0000-0000-0000-00000000000a.jsonl"
make_session "$SANDBOX_HOME/.claude/projects/proj-noapprove/noap0000-0000-0000-0000-00000000000b.jsonl"
make_session "$SANDBOX_HOME/.claude/projects/proj-noapprove/noap0000-0000-0000-0000-00000000000c.jsonl"

SKILLMD_BEFORE=$(find "$SANDBOX_HOME" -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ')
REPO_SKILLS_DIRS_BEFORE=$(find "$REPO_ROOT/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

HOME="$SANDBOX_HOME" WORKFLOW_AUDIT_ROOT="$SANDBOX_HOME/.claude/projects" bash "$SCAN_SCRIPT" --all-projects --days 36500 \
  | HOME="$SANDBOX_HOME" bash "$CLUSTER_SCRIPT" --min-sessions 3 >/dev/null

SKILLMD_AFTER=$(find "$SANDBOX_HOME" -name 'SKILL.md' 2>/dev/null | wc -l | tr -d ' ')
REPO_SKILLS_DIRS_AFTER=$(find "$REPO_ROOT/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)

check "mechanical pipeline alone creates zero SKILL.md files under sandbox HOME" "0" "$SKILLMD_AFTER"
check "sandbox HOME SKILL.md count unchanged (before == after)" "$SKILLMD_BEFORE" "$SKILLMD_AFTER"
check "repo skills/ directory listing unchanged (no new skill dirs created)" "$REPO_SKILLS_DIRS_BEFORE" "$REPO_SKILLS_DIRS_AFTER"
rm -rf "$SANDBOX_HOME"

# ═══════════════════════════════════════════════════════════════════════════
# 4. Clean no-candidates path: a corpus with no repeated n-grams across
#    sessions must yield an empty clusters array, exit 0, and no jq_parse_error.
# ═══════════════════════════════════════════════════════════════════════════
TMP4=$(mktemp -d)
mkdir -p "$TMP4/proj-noclust-a" "$TMP4/proj-noclust-b" "$TMP4/proj-noclust-c"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read"}]},"timestamp":"2026-07-06T12:00:00Z"}\n' \
  > "$TMP4/proj-noclust-a/nocl0000-0000-0000-0000-00000000000a.jsonl"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write"}]},"timestamp":"2026-07-06T12:00:00Z"}\n' \
  > "$TMP4/proj-noclust-b/nocl0000-0000-0000-0000-00000000000b.jsonl"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep"}]},"timestamp":"2026-07-06T12:00:00Z"}\n' \
  > "$TMP4/proj-noclust-c/nocl0000-0000-0000-0000-00000000000c.jsonl"

NOCLUST_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP4" bash "$SCAN_SCRIPT" --all-projects --days 36500 2>/tmp/e2e_noclust_scan.err | bash "$CLUSTER_SCRIPT" --min-sessions 3 2>/tmp/e2e_noclust_cluster.err)
NOCLUST_RC=$?
check "no-candidates corpus -> pipeline exits 0" "0" "$NOCLUST_RC"
check "no-candidates corpus -> empty clusters array" "[]" "$(printf '%s' "$NOCLUST_OUT" | jq -c '.clusters')"
NOCLUST_STDERR=$(cat /tmp/e2e_noclust_scan.err /tmp/e2e_noclust_cluster.err 2>/dev/null)
check_not_contains "no-candidates corpus -> no jq_parse_error on stderr" "$NOCLUST_STDERR" "jq_parse_error"
rm -f /tmp/e2e_noclust_scan.err /tmp/e2e_noclust_cluster.err
rm -rf "$TMP4"

# ═══════════════════════════════════════════════════════════════════════════
# 5. WU1 residual edge cases (verified by hand during review, pinned here)
# ═══════════════════════════════════════════════════════════════════════════

# 5a. --last-sessions N where N exceeds available sessions: graceful, returns
#     all available sessions rather than erroring or padding.
TMP5A=$(mktemp -d)
mkdir -p "$TMP5A/proj-fewer"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read"}]},"timestamp":"2026-07-01T00:00:00Z"}\n' \
  > "$TMP5A/proj-fewer/5a000000-0000-0000-0000-00000000000a.jsonl"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write"}]},"timestamp":"2026-07-02T00:00:00Z"}\n' \
  > "$TMP5A/proj-fewer/5a000000-0000-0000-0000-00000000000b.jsonl"
FEWER_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP5A" bash "$SCAN_SCRIPT" --project proj-fewer --last-sessions 50)
FEWER_RC=$?
FEWER_COUNT=$(printf '%s' "$FEWER_OUT" | jq -s 'length')
check "--last-sessions N > available sessions -> exits 0" "0" "$FEWER_RC"
check "--last-sessions N > available sessions -> returns all available (2), not an error" "2" "$FEWER_COUNT"
rm -rf "$TMP5A"

# 5b. Empty project dir: skipped cleanly, no crash, no output, no stderr error.
TMP5B=$(mktemp -d)
mkdir -p "$TMP5B/proj-empty"
EMPTY_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP5B" bash "$SCAN_SCRIPT" --project proj-empty --days 36500 2>&1 >/dev/null)
EMPTY_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP5B" bash "$SCAN_SCRIPT" --project proj-empty --days 36500 2>/dev/null)
EMPTY_RC=$?
check "empty project dir -> exits 0" "0" "$EMPTY_RC"
check "empty project dir -> no session output" "" "$EMPTY_OUT"
check_not_contains "empty project dir -> no jq_parse_error" "$EMPTY_ERR" "jq_parse_error"
rm -rf "$TMP5B"

# 5c. Unicode in a Bash command head: no crash, head preserved (first two
#     whitespace tokens, byte-for-byte, not mangled by the tokenizer).
TMP5C=$(mktemp -d)
mkdir -p "$TMP5C/proj-unicode"
printf '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"echo café-日本語 --flag"}}]},"timestamp":"2026-07-06T13:00:00Z"}\n' \
  > "$TMP5C/proj-unicode/5c000000-0000-0000-0000-00000000000a.jsonl"
UNICODE_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP5C" bash "$SCAN_SCRIPT" --project proj-unicode --days 36500)
UNICODE_RC=$?
check "unicode Bash command -> scan exits 0 (no crash)" "0" "$UNICODE_RC"
check_contains "unicode Bash command -> head preserves the unicode tokens" "$UNICODE_OUT" '"head":"echo café-日本語"'
UNICODE_CLUSTER_IN=$(printf '%s\n%s\n%s\n' \
  "$(printf '%s' "$UNICODE_OUT" | jq -c '.session_id="uc-1"')" \
  "$(printf '%s' "$UNICODE_OUT" | jq -c '.session_id="uc-2"')" \
  "$(printf '%s' "$UNICODE_OUT" | jq -c '.session_id="uc-3"')")
# single-event sessions can't form an n>=2 gram; just confirm cluster_ngrams.sh
# doesn't crash or corrupt the unicode string when it does pass through.
UNICODE_CLUSTER_OUT=$(printf '%s\n' "$UNICODE_CLUSTER_IN" | bash "$CLUSTER_SCRIPT" --min-sessions 3)
UNICODE_CLUSTER_RC=$?
check "unicode event string -> cluster_ngrams.sh exits 0 (no crash)" "0" "$UNICODE_CLUSTER_RC"
rm -rf "$TMP5C"

# ═══════════════════════════════════════════════════════════════════════════
[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
