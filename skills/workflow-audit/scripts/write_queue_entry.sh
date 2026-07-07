#!/bin/bash
# write_queue_entry.sh — write one QueueFileEntry JSON file per propose-verdict
# judge output, for the dashboard's existing approval-queue surface.
#
# Reads one judge-contract verdict object (see
# skills/workflow-audit/references/judge-contract.md) on stdin. On a
# "propose" verdict, writes exactly one file <queue-dir>/<hash>.json and
# prints the hash (bare hex string) to stdout. On any other verdict
# (including "reject"), writes nothing and exits 0 with no stdout — silent
# no-op, not one guard away from a privacy leak.
#
# toolInput is built ONLY from six D2-whitelisted fields drawn from the
# judge-contract vocabulary: cluster_ngram, count, sessions, task_summary,
# proposed_name, proposed_description. Any other field present in the piped
# verdict object is dropped, never copied into toolInput or the written file.
#
# hash = sha256 hex of the canonicalised (sorted-key, compact) toolInput JSON
# — same recipe as assistant-agent's gate/sendGate.ts hashInput/canonicalise
# (sha256(JSON.stringify(sortKeysDeep(toolInput)))); `jq -S -c` produces the
# same canonical form for this flat toolInput shape (no nested objects).
#
# PRIVACY INVARIANT: the written file's toolInput never contains anything
# beyond the six whitelisted fields — no verbatim transcript prose, no file
# contents, no reconstructed intent.
set -u

QUEUE_DIR="$HOME/.claude/coderails-dashboard/queue"
COUNT=""
SESSIONS=""

usage() {
  cat <<'EOF'
Usage: write_queue_entry.sh --queue-dir <dir> --count N --sessions '<json-array>' [--help]

Reads one judge-contract verdict object (JSON) on stdin:
  {"cluster_ngram":[...],"verdict":"propose"|"reject","reject_reason":"",
   "task_summary":"...","proposed_name":"...","proposed_description":"..."}

On verdict:"propose", writes exactly one file <queue-dir>/<hash>.json (a
QueueFileEntry: {hash, toolName, toolInput, createdAt, status:"pending"})
and prints the hash (bare hex string) to stdout. toolName is always
"workflow-audit:propose-skill". toolInput contains ONLY the six D2-whitelisted
fields (cluster_ngram, count, sessions, task_summary, proposed_name,
proposed_description) — any other field in the piped verdict object is
dropped, never copied through.

On any other verdict (e.g. "reject"), writes nothing and exits 0 with no
stdout.

  --queue-dir <dir>   Directory to write the queue file into (created if
                      missing). Default: ~/.claude/coderails-dashboard/queue
  --count N           Integer count from the originating cluster.
  --sessions '<json>' JSON array of session-id strings from the originating
                      cluster.
  --help              Show this help and exit.

Errors (stderr): jq_parse_error:stdin for malformed/non-object stdin input.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --queue-dir) QUEUE_DIR="${2:-}"; shift 2 ;;
    --count) COUNT="${2:-}"; shift 2 ;;
    --sessions) SESSIONS="${2:-}"; shift 2 ;;
    --help) usage; exit 0 ;;
    *) printf 'unknown_arg:%s\n' "$1" >&2; exit 1 ;;
  esac
done

# Sanitise --count (house contract: fall back rather than crash on non-numeric).
case "$COUNT" in (''|*[!0-9]*) COUNT=0;; esac

# --sessions must be a JSON array; fall back to an empty array on anything else.
SESSIONS_VALID=$(printf '%s' "$SESSIONS" | jq -ce 'if type == "array" then . else empty end' 2>/dev/null)
if [ -z "$SESSIONS_VALID" ]; then
  SESSIONS_VALID='[]'
fi

# Read the verdict object from stdin — must be a JSON object, same guard
# cluster_ngrams.sh applies to its own per-line input.
VERDICT_INPUT=$(cat)
VERDICT=$(printf '%s' "$VERDICT_INPUT" | jq -ce 'if type == "object" then . else empty end' 2>/dev/null)
if [ -z "$VERDICT" ]; then
  printf 'jq_parse_error:stdin\n' >&2
  exit 1
fi

# Silent no-op on any verdict other than "propose" — the script itself must
# refuse to write a reject-verdict row even if ever called on one directly.
IS_PROPOSE=$(printf '%s' "$VERDICT" | jq -r 'if .verdict == "propose" then "yes" else "no" end')
if [ "$IS_PROPOSE" != "yes" ]; then
  exit 0
fi

# Build toolInput from ONLY the six D2-whitelisted fields — structural
# whitelist via explicit jq -n field construction, so any other field present
# on $VERDICT (e.g. a stray raw_transcript_line) is never copied through.
TOOL_INPUT=$(printf '%s' "$VERDICT" | jq -c --argjson count "$COUNT" --argjson sessions "$SESSIONS_VALID" '{
  cluster_ngram: (.cluster_ngram // []),
  count: $count,
  sessions: $sessions,
  task_summary: (.task_summary // ""),
  proposed_name: (.proposed_name // ""),
  proposed_description: (.proposed_description // "")
}')

# hash = sha256 hex of canonicalised (sorted-key, compact) toolInput —
# matches assistant-agent sendGate.ts's hashInput(toolInput) exactly for this
# flat (no-nested-object) shape.
CANONICAL=$(printf '%s' "$TOOL_INPUT" | jq -S -c .)
HASH=$(printf '%s' "$CANONICAL" | shasum -a 256 | awk '{print $1}')

mkdir -p "$QUEUE_DIR"

CREATED_AT=$(date +%s%3N 2>/dev/null)
case "$CREATED_AT" in (''|*[!0-9]*) CREATED_AT=$(($(date +%s) * 1000)) ;; esac

jq -n \
  --arg hash "$HASH" \
  --argjson toolInput "$TOOL_INPUT" \
  --argjson createdAt "$CREATED_AT" \
  '{hash: $hash, toolName: "workflow-audit:propose-skill", toolInput: $toolInput, createdAt: $createdAt, status: "pending"}' \
  > "$QUEUE_DIR/$HASH.json"

printf '%s\n' "$HASH"
exit 0
