#!/bin/bash
# PreToolUse hook (Write|Edit|MultiEdit): block NEW session-artifact citations
# in code comments. A comment should state the constraint the code enforces,
# never cite the conversation, PR review, or session artifact that produced it
# — those labels (E1, F4 fix, CHANGE B2, Task A3, TA-I1, "reviewer finding FH",
# "per the plan's step 2", etc.) rot the moment the session ends and nobody
# with just the repo can resolve them. Scope: comment-bearing content fields
# only (new_string/content/edits[].new_string), skipped entirely for .md files
# (markdown is out of scope for this hook). "PR #NN" is a documented survivor
# — it resolves to a durable, checkable GitHub artifact. Emits
# permissionDecision=deny + exit 0, the same idiom as no_edit_on_main.sh.

IFS= read -r -d '' -t 5 input || true

file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

# Markdown is out of scope entirely — check file_path suffix first.
case "$file" in
  *.md) exit 0 ;;
esac

# Gather every content field that could carry a new/changed comment line:
# Edit's new_string, Write's content, and each MultiEdit edits[].new_string.
content=$(printf '%s' "$input" | jq -r '
  [.tool_input.new_string, .tool_input.content] + [.tool_input.edits[]?.new_string]
  | map(select(. != null))
  | .[]
' 2>/dev/null)

[ -z "$content" ] && exit 0

# Citation-phrasing regex. Anchored on the label SHAPE (a following digit for
# CHANGE/Task, a word boundary elsewhere) so schema/noise values (P0, WU3=,
# "WU3", CHANGE the default timeout) don't collide on a bare substring.
# Families: E#, F# fix/:, CHANGE B#/C#, Task A#, TA-I#, "reviewer finding X",
# "eval E#", WU#: (as a citation label, not WU#= assignment or "WU#" JSON key),
# C2, and generic indirect-artifact phrasing (per the plan/design/session).
pattern='\bE[0-9]+:|\bF[0-9]+ (fix|:|design)|CHANGE [BC][0-9]|\bTask A[0-9]+\b|TA-I[0-9]+|reviewer finding|eval E[0-9]+|\bWU[0-9]+:|\bC2\b|per the (plan|design|session)|per F[0-9]+'

# Literal label DATA is not a citation: a value in a JSON fixture, or a label
# string asserted on in a test, cites nothing — it resolves from the repo alone,
# which is the only thing this gate protects. Matching the raw content field
# denied those edits.
#
# Strip the spans that are provably data — text inside quotes — and match what
# remains. This direction is deliberate. The inverse (extract comment spans,
# match only those) cannot be expressed line-at-a-time: a /* */ span carries no
# per-line marker, so every C/JS/TS block comment silently leaves scope and the
# gate stops enforcing there. Stripping quoted spans instead fails SAFE — any
# text not provably a string literal stays in scope, so a comment in any syntax,
# block or line, still fires.
#
# A citation inside a double-quoted string is the deliberate blind spot, and it
# is the exact false positive this fixes. A comment is never inside quotes.
#
# ONLY double quotes are stripped. Single quotes are NOT: an apostrophe in
# ordinary prose (as in "don't" ... "isn't") would pair with the next one and
# swallow the text between them as a fake string span, so a cited label sitting
# in that gap would go silently unenforced. That text is a comment, not a
# string. A single-quoted string literal carrying a label therefore still
# denies; a false positive there is the safe direction, and the fixture and
# test-string cases this targets are JSON, which is double-quoted anyway.
#
# Escaped quotes are neutralised first so they cannot open or close a span.
uncited=$(printf '%s\n' "$content" | sed \
  -e 's/\\"/@/g' \
  -e 's/"[^"]*"/""/g')

match=$(printf '%s\n' "$uncited" | grep -Ei "$pattern" | head -1)

if [ -n "$match" ]; then
  reason="Blocked: comment cites a session-artifact label ($(printf '%s' "$match" | sed 's/^[[:space:]]*//')). State the constraint the code enforces, not the conversation/PR that produced it."
  jq -n --arg r "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
fi

exit 0
