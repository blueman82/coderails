#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/integrity-gate-runner.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0
ok() { printf 'ok - %s\n' "$1"; }
check() { if [[ "$2" == "$3" ]]; then ok "$1"; else printf 'FAIL - %s: expected %s got %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }

SHA=0123456789012345678901234567890123456789
BODY="<!-- coderails-eval-summary v1 pr=7 head_sha=$SHA result=GO verification_level=1 -->
\`\`\`json
{\"schema_version\":1,\"task_ref\":\"7\",\"frozen_sha\":\"base\",\"head_sha\":\"$SHA\",\"evals\":[]}
\`\`\`"
tg_pr_head_sha() { printf '%s' "$SHA"; }
tg_newest_eval() { printf '%s' "$BODY"; }
tg_should_gate() { return 0; }
tg_statuses() { printf '[]'; }
tg_pr_comments() { printf '%s\n' "$(printf '%s' "<!-- coderails-review-summary v1 pr=7 head_sha=$SHA -->" | base64)"; }
tg_extract_evals_json() { printf '%s\n' '{"schema_version":1,"task_ref":"7","frozen_sha":"base","head_sha":"'$SHA'","evals":[]}'; }
tg_gh_get() {
  case "$1" in
    pulls/7/files*) printf '[{"filename":"scripts/example.sh"}]' ;;
    pulls/7) printf 'diff --git a/scripts/example.sh b/scripts/example.sh\n+x\n' ;;
  esac
}
tg_post_status() { printf '%s %s\n' "$2" "$3" >> "$TMP/statuses"; return 0; }

out=$(tg_gate_pr 7); rc=$?
check 'valid evidence passes' 0 "$rc"
check 'valid evidence posts success' success "$(tail -1 "$TMP/statuses" | awk '{print $1}')"
grep -q 'integrity=pass' "$TMP/statuses" && ok 'success is an integrity attestation' || { echo 'FAIL - missing integrity attestation'; fails=$((fails+1)); }

tg_has_review() { return 1; }
: > "$TMP/statuses"
out=$(tg_gate_pr 7); rc=$?
check 'missing review fails' 1 "$rc"
grep -q 'review_evidence_missing' "$TMP/statuses" && ok 'missing review is named' || { echo 'FAIL - missing review reason'; fails=$((fails+1)); }

tg_has_review() { return 0; }
tg_gh_get() { case "$1" in pulls/7/files*) printf '[{"filename":"scripts/integrity-gate/evil.sh"}]';; pulls/7) printf 'diff';; esac; }
: > "$TMP/statuses"
out=$(tg_gate_pr 7); rc=$?
check 'policy path fails closed' 0 "$rc"
grep -q 'integrity=fail' "$TMP/statuses" && ok 'policy failure is not a pass' || { echo 'FAIL - policy failure status'; fails=$((fails+1)); }

exit "$fails"
