#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
EXPECTED='ruby -e '\''require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], aliases: false)'\'' <path>'
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

extract_command() {
    grep -o "ruby -e '[^']*' <path>" "$1"
}

CLAUDE_COMMAND=$(extract_command "$ROOT/commands/init.md")
CODEX_COMMAND=$(extract_command "$ROOT/packages/codex/skills/init/SKILL.md")
[[ "$CLAUDE_COMMAND" == "$EXPECTED" ]]
[[ "$CODEX_COMMAND" == "$EXPECTED" ]]

RUBY_PROGRAM=${CLAUDE_COMMAND#ruby -e \'}
RUBY_PROGRAM=${RUBY_PROGRAM%\' <path>}

validate() {
    ruby -e "$RUBY_PROGRAM" "$1" >/dev/null 2>&1
}

reject() {
    if validate "$1"; then
        printf 'FAIL - accepted %s\n' "$1" >&2
        return 1
    fi
}

printf 'project: example\n' >"$TMP/valid.yaml"
printf 'project: [\n' >"$TMP/malformed.yaml"
printf 'defaults: &defaults\n  project: example\ncopy: *defaults\n' >"$TMP/alias.yaml"
printf '%s\n' '!ruby/object:Object {}' >"$TMP/unsafe.yaml"

validate "$TMP/valid.yaml"
reject "$TMP/malformed.yaml"
reject "$TMP/alias.yaml"
reject "$TMP/unsafe.yaml"
reject "$TMP/missing.yaml"

printf 'PASS\n'
