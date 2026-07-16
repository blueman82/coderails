#!/bin/bash
# Behavioural test for comment_citation_gate.sh — feeds synthetic PreToolUse
# Write/Edit/MultiEdit payloads and asserts allow vs deny. All state lives in
# the payload strings; no repo state needed (unlike no_edit_on_main.test.sh).
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/comment_citation_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

payload() { # tool file_path new_string -> json
  printf '{"tool_name":"%s","tool_input":{"file_path":%s,"new_string":%s}}' \
    "$1" "$(printf '%s' "$2" | jq -Rs .)" "$(printf '%s' "$3" | jq -Rs .)"
}
payload_write() { # file_path content -> json (Write tool)
  printf '{"tool_name":"Write","tool_input":{"file_path":%s,"content":%s}}' \
    "$(printf '%s' "$1" | jq -Rs .)" "$(printf '%s' "$2" | jq -Rs .)"
}
payload_multiedit() { # file_path new_string1 new_string2 -> json (two edits[])
  printf '{"tool_name":"MultiEdit","tool_input":{"file_path":%s,"edits":[{"new_string":%s},{"new_string":%s}]}}' \
    "$(printf '%s' "$1" | jq -Rs .)" "$(printf '%s' "$2" | jq -Rs .)" "$(printf '%s' "$3" | jq -Rs .)"
}
run() { # payload -> DENY|ALLOW
  local out
  out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}
check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

FILE="hooks/scripts/some_hook.sh"

# ─── Clean edit, no citation ─────────────────────────────────────────────────
check "clean comment, no citation -> allow" ALLOW \
  "$(run "$(payload Edit "$FILE" "# Falls back to \$PWD when .cwd is absent.")")"

# ─── Named ID-family citations (all DENY) ────────────────────────────────────
check "E1: trust baseline -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# E1: trust baseline")")"
check "F4 fix comment -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "// F4 fix: anchor ext")")"
check "CHANGE B2 comment -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# CHANGE B2: per-PR check")")"
check "Task A3 comment -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# Task A3 verifies...")")"
check "per finding TA-I1 -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# per finding TA-I1")")"
check "reviewer finding FH -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# reviewer finding FH")")"
check "eval E2 covers... -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# eval E2 covers...")")"
check "WU5: rewrite target (citation prose) -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# WU5: rewrite target")")"

# ─── Survivor classes (all ALLOW) ────────────────────────────────────────────
check "See PR #42 for context -> allow (durable-artifact survivor)" ALLOW \
  "$(run "$(payload Edit "$FILE" "# See PR #42 for context")")"
check ".md file containing E1: citation text -> allow (markdown scope guard)" ALLOW \
  "$(run "$(payload Edit "README.md" "# E1: trust baseline")")"
check "WU3=pending fixture assignment in .test.sh -> allow (survivor)" ALLOW \
  "$(run "$(payload Edit "hooks/scripts/tests/loop_state_guard_evals.test.sh" "WU3=pending")")"
check "\"WU3\": \"pending\" JSON data field -> allow (survivor)" ALLOW \
  "$(run "$(payload Edit "$FILE" "\"WU3\": \"pending\"")")"
check "P0 alone in a comment -> allow (survivor, not a citation family)" ALLOW \
  "$(run "$(payload Edit "$FILE" "# priority P0")")"
check "P1 alone in a comment -> allow (survivor, not a citation family)" ALLOW \
  "$(run "$(payload Edit "$FILE" "# priority P1")")"

# ─── MultiEdit array iteration (proves every edit[] entry is checked) ────────
check "MultiEdit: one clean + one F1 fix -> deny (checks every edit, not just first)" DENY \
  "$(run "$(payload_multiedit "$FILE" "# clean comment, nothing wrong here" "# F1 fix: guard the anchor")")"

# ─── Write tool content field ─────────────────────────────────────────────────
check "Write tool, content has E1: citation -> deny" DENY \
  "$(run "$(payload_write "$FILE" "# E1: trust baseline")")"
check "Write tool, clean content -> allow" ALLOW \
  "$(run "$(payload_write "$FILE" "# Clean, no citation")")"

# ─── Fail-open on malformed/empty stdin ──────────────────────────────────────
check "empty stdin -> allow (fail-open)" ALLOW \
  "$(run "")"
check "malformed JSON stdin -> allow (fail-open)" ALLOW \
  "$(run "not valid json {{{")"

# ─── Punctuation-wrapped citations must not evade detection ─────────────────
check "(C2, anti-stall) parenthesis-wrapped -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# (C2, anti-stall) shared with loop_stall_guard.sh")")"
check "...(per F3 design): parenthesis-wrapped -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# fallback logic...(per F3 design):")")"

# ─── Generic indirect-artifact phrasing (not a named ID family) ─────────────
check "per the plan's step 2 -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# per the plan's step 2")")"
check "per the design doc -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# per the design doc")")"

# ─── False-positive guards (substring collisions must NOT fire) ─────────────
check "\"priority\":\"P0\" inside JSON-fixture content -> allow" ALLOW \
  "$(run "$(payload Edit "$FILE" "{\"priority\":\"P0\"}")")"
check "CHANGE the default timeout (no trailing digit) -> allow" ALLOW \
  "$(run "$(payload Edit "$FILE" "# CHANGE the default timeout")")"

# ─── Non-comment lines must NOT fire: the gate polices COMMENTS, not code ────
# Regression: the gate matched anywhere in the content field, so literal label
# data in JSON fixtures and label strings asserted on in tests were read as
# comment citations. Both are data the repo can resolve on its own.
check "E1: as a JSON fixture VALUE (not a comment) -> allow" ALLOW \
  "$(run "$(payload_write "fixtures/evals.json" "{\"evals\":[{\"id\":\"E1:\",\"desc\":\"gate blocks\"}]}")")"
check "reviewer finding asserted as a test STRING (not a comment) -> allow" ALLOW \
  "$(run "$(payload Edit "hooks/scripts/tests/x.test.sh" "assert_eq \"\$out\" \"reviewer finding\"")")"
check "WU1: inside a shell string literal (not a comment) -> allow" ALLOW \
  "$(run "$(payload Edit "$FILE" "msg=\"WU1: pending\"")")"
check "code line with trailing comment citation -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "foo=1  # E1: reviewer finding said guard this")")"

# ─── Block comments must stay in scope (regression: a comment-span extractor
# ─── silently dropped every /* */ line, disabling the gate for C/JS/TS/Java) ──
check "C block comment citation, trailing -> deny" DENY \
  "$(run "$(payload Edit "src/x.c" "int x; /* E1: reviewer finding */")")"
check "C block comment citation, opener line -> deny" DENY \
  "$(run "$(payload Edit "src/x.c" "/* E1: reviewer finding said guard this")")"
check "JS block comment, per the plan -> deny" DENY \
  "$(run "$(payload Edit "src/x.js" "const x = 1; /* per the plan */")")"
check "block comment continuation line -> deny" DENY \
  "$(run "$(payload Edit "src/x.c" " * per the design doc")")"
check "// line comment citation -> deny" DENY \
  "$(run "$(payload Edit "src/x.ts" "// E1: reviewer finding")")"

# ─── Apostrophes in prose must not form a fake string span ───────────────────
# Regression: stripping single-quoted spans made two ordinary prose apostrophes
# pair up and swallow the citation between them, silently unenforcing a comment
# written in plain English. Only double quotes delimit strings here.
APOS="'"
check "prose apostrophes around a citation -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# don${APOS}t cite E1: because it isn${APOS}t resolvable")")"
check "prose apostrophes around per-the-plan -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# it${APOS}s per the plan, don${APOS}t change it")")"
check "single-quoted literal with a label -> deny (safe direction)" DENY \
  "$(run "$(payload Edit "$FILE" "msg=${APOS}E1: pending${APOS}")")"

# ─── A second comment marker must not drop the citation before it ────────────
check "two # markers, citation before the second -> deny" DENY \
  "$(run "$(payload Edit "$FILE" "# E1: x # y")")"
check "two // markers, citation before the second -> deny" DENY \
  "$(run "$(payload Edit "src/x.js" "// E1: x // y")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
