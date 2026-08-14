#!/usr/bin/env bash
# Safe behavioural coverage for setup.sh's gh failure/recovery branch.
# Uses command stubs and cancellation; never reaches sudo, credentials, or network.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SETUP="$REPO_ROOT/scripts/integrity-gate/setup.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
check() {
    if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails + 1)); fi
}
check_contains() {
    if printf '%s' "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected to contain: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails + 1)); fi
}

make_bin() {
    local bin="$1"
    mkdir -p "$bin"
    for tool in jq curl git; do
        printf '#!/bin/bash\nexit 0\n' > "$bin/$tool"
        chmod +x "$bin/$tool"
    done
    cp "$TMP/gh" "$bin/gh"
    chmod +x "$bin/gh"
}

# Initial gh failure, Enter-driven recovery, and a failed retry: auth is not tried.
SCENARIO="$TMP/cancel"
mkdir -p "$SCENARIO"
cat > "$TMP/gh" <<'EOF'
#!/bin/bash
case "$1 ${2:-}" in
  auth\ login) : > "$SCENARIO/auth-login"; exit 0 ;;
  repo\ view) exit 1 ;;
  *) exit 1 ;;
esac
EOF
FAKEBIN="$SCENARIO/bin"
make_bin "$FAKEBIN"
out=$(printf '\n' | SCENARIO="$SCENARIO" PATH="$FAKEBIN:/usr/bin:/bin" /bin/bash "$SETUP" --dry-run 2>&1)
rc=$?
check 'gh failure + failed retry returns failure' 1 "$rc"
check_contains 'failed retry names the GitHub access failure' 'gh retry failed; check GitHub connectivity and repository access' "$out"
[[ ! -e "$SCENARIO/auth-login" ]] && printf 'ok   - failed retry does not invoke gh auth login\n' || { printf 'FAIL - failed retry invoked gh auth login\n'; fails=$((fails + 1)); }

# Initial gh failure, successful Enter-driven recovery, and successful retry.
SCENARIO="$TMP/recover"
mkdir -p "$SCENARIO"
cat > "$TMP/gh" <<'EOF'
#!/bin/bash
case "$1 ${2:-}" in
  auth\ login) : > "$SCENARIO/auth-login"; exit 0 ;;
  repo\ view)
    count_file="$SCENARIO/repo-view-count"
    count=0; [[ -f "$count_file" ]] && count=$(<"$count_file")
    count=$((count + 1)); printf '%s\n' "$count" > "$count_file"
    (( count == 1 )) && exit 1
    printf 'octo/coderails\n'
    ;;
  *) exit 1 ;;
esac
EOF
FAKEBIN="$SCENARIO/bin"
make_bin "$FAKEBIN"
out=$(printf '\n' | SCENARIO="$SCENARIO" PATH="$FAKEBIN:/usr/bin:/bin" /bin/bash "$SETUP" --dry-run 2>&1)
rc=$?
check 'successful Enter-driven recovery returns success' 0 "$rc"
check_contains 'successful recovery reports resolved repository' 'for octo/coderails' "$out"
check_contains 'successful recovery reaches dry-run output' 'Would configure the product-neutral integrity gate' "$out"
check 'successful recovery does not invoke gh auth login' 0 "$(test -f "$SCENARIO/auth-login" && printf 1 || printf 0)"
check 'successful recovery retries repo view once' 2 "$(<"$SCENARIO/repo-view-count")"

# gh repo view succeeds, the first ruleset read is malformed JSON, recovery
# succeeds, the retry returns [], and ruleset creation is cancelled.
SCENARIO="$TMP/ruleset-recover"
mkdir -p "$SCENARIO"
cat > "$TMP/gh" <<'EOF'
#!/bin/bash
if [[ "$1" == auth && "${2:-}" == login ]]; then
    : > "$SCENARIO/auth-login"
    exit 0
fi
if [[ "$1" == repo && "${2:-}" == view ]]; then
    printf 'octo/coderails\n'
    exit 0
fi
if [[ "$1" == api && "${2:-}" == repos/octo/coderails/rulesets\?per_page=100 ]]; then
    count_file="$SCENARIO/ruleset-read-count"
    count=0; [[ -f "$count_file" ]] && count=$(<"$count_file")
    count=$((count + 1)); printf '%s\n' "$count" > "$count_file"
    if (( count == 1 )); then printf '{not-json\n'; else printf '[]\n'; fi
    exit 0
fi
if [[ "$1" == api && "${2:-}" == repos/octo/coderails/rulesets && "${3:-}" == --method ]]; then
    : > "$SCENARIO/ruleset-create"
    exit 1
fi
exit 1
EOF
FAKEBIN="$SCENARIO/bin"
mkdir -p "$FAKEBIN"
for tool in curl git; do
    printf '#!/bin/bash\nexit 0\n' > "$FAKEBIN/$tool"
    chmod +x "$FAKEBIN/$tool"
done
cat > "$FAKEBIN/jq" <<'EOF'
#!/bin/bash
if [[ "$*" == *'type == "array"'* ]]; then
    input=$(cat)
    [[ "$input" == '[]' ]]
    exit $?
fi
if [[ "${1:-}" == -n ]]; then
    printf '{}\n'
else
    cat >/dev/null
fi
EOF
chmod +x "$FAKEBIN/jq"
cp "$TMP/gh" "$FAKEBIN/gh"
chmod +x "$FAKEBIN/gh"
out=$(printf '\n\n' | SCENARIO="$SCENARIO" PATH="$FAKEBIN:/usr/bin:/bin" /bin/bash "$SETUP" 2>&1)
rc=$?
check 'malformed ruleset JSON + recovery + creation cancellation returns failure' 1 "$rc"
check_contains 'malformed ruleset JSON prompts recovery' 'Could not read valid JSON from GitHub' "$out"
check_contains 'recovered ruleset read reaches creation prompt' 'ruleset creation cancelled; validator installation not started' "$out"
check 'malformed ruleset JSON recovery does not invoke gh auth login' 0 "$(test -f "$SCENARIO/auth-login" && printf 1 || printf 0)"
check 'malformed ruleset JSON recovery rereads rulesets once' 2 "$(<"$SCENARIO/ruleset-read-count")"
check 'cancelled creation does not call ruleset POST' 0 "$(test -f "$SCENARIO/ruleset-create" && printf 1 || printf 0)"

exit "$fails"
