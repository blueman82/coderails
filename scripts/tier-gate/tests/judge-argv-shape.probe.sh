#!/bin/bash
# judge-argv-shape.probe.sh <runner-path>
#
# Frozen acceptance probe for the tier-gate judge's argv shape. Drives the REAL
# tg_judge_call_claude from the runner under test and observes the argv it
# actually builds, via a stub `claude` binary of this probe's own making.
#
# Deliberately independent of hooks/scripts/tests/tier_gate_runner.test.sh:
# that suite's J11 is edited by the same change this probe grades, so reusing
# its stub, its CLAUDE_ARGV_LOG, or its expected count would share an oracle
# with the implementation. This probe brings its own instrument.
#
# Asserts SHAPE, never the literal element count — the count lives in J11,
# which is a test, not an eval. Checks:
#   1. --max-turns is followed by exactly "2"
#   2. --disallowedTools is present
#   3. it is followed by >= 10 tool-name elements, NONE containing a comma
#      (this is what separates the validated ten-argv-element spelling from
#      the comma-joined single-argument form, which was never run against the
#      judge and is therefore not what ships)
#
# Exit 0 = shape satisfied. Non-zero = not satisfied (content reason).
# Usage: judge-argv-shape.probe.sh [path-to-tier-gate-runner.sh]

set -uo pipefail

RUNNER="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/tier-gate-runner.sh}"

if [[ ! -f "$RUNNER" ]]; then
    echo "PROBE ERROR: runner not found: $RUNNER" >&2
    exit 2
fi

TMP=$(mktemp -d) || { echo "PROBE ERROR: mktemp failed" >&2; exit 2; }
trap 'rm -rf "$TMP"' EXIT

ARGV_LOG="$TMP/argv.log"

# Stub claude: records its own argv NUL-delimited, then emits a well-formed
# envelope so the caller's parse path stays happy. NUL-delimited because the
# -p prompt is multi-line and a newline delimiter would split one element.
STUB="$TMP/claude-stub"
cat > "$STUB" <<STUBEOF
#!/bin/bash
for a in "\$@"; do printf '%s\0' "\$a"; done >> "$ARGV_LOG"
printf '%s\n' '{"type":"result","is_error":false,"result":"{\\"verdict\\":\\"legitimate\\",\\"reason\\":\\"probe\\"}"}'
STUBEOF
chmod +x "$STUB"

# Source the runner for its functions only. It is a daemon script; guard
# against it running its poll loop by sourcing in a subshell-safe way and
# relying on the file's own no-main-on-source structure.
JUDGE_HOME="$TMP/home"
mkdir -p "$JUDGE_HOME"

# shellcheck disable=SC1090
TIER_GATE_CLAUDE_BIN="$STUB" \
TIER_GATE_JUDGE_HOME="$JUDGE_HOME" \
TIER_GATE_WATCHDOG_TIMEOUT=10 \
TIER_GATE_FORCE_POLLING_WATCHDOG=1 \
bash -c '
    source "$1" >/dev/null 2>&1
    if ! declare -F tg_judge_call_claude >/dev/null; then
        echo "PROBE ERROR: tg_judge_call_claude not defined after source" >&2
        exit 2
    fi
    tg_judge_call_claude "probe-token" "probe prompt" >/dev/null 2>&1
' _ "$RUNNER"
rc=$?

if [[ $rc -eq 2 ]]; then
    echo "PROBE ERROR: could not drive tg_judge_call_claude" >&2
    exit 2
fi

if [[ ! -s "$ARGV_LOG" ]]; then
    echo "FAIL: stub claude was never invoked - no argv captured" >&2
    exit 1
fi

argv=()
while IFS= read -r -d '' el; do argv+=("$el"); done < "$ARGV_LOG"

fail=0

# 1. --max-turns followed by exactly "2"
mt=""
for ((i=0; i<${#argv[@]}; i++)); do
    if [[ "${argv[$i]}" == "--max-turns" ]]; then mt="${argv[$((i+1))]}"; break; fi
done
if [[ -z "$mt" ]]; then
    echo "FAIL: --max-turns absent from judge argv" >&2
    fail=1
elif [[ "$mt" != "2" ]]; then
    echo "FAIL: --max-turns is '$mt', expected '2'" >&2
    fail=1
else
    echo "ok - --max-turns 2"
fi

# 2 + 3. --disallowedTools present, followed by >=10 comma-free elements
dt_idx=-1
for ((i=0; i<${#argv[@]}; i++)); do
    if [[ "${argv[$i]}" == "--disallowedTools" || "${argv[$i]}" == "--disallowed-tools" ]]; then
        dt_idx=$i; break
    fi
done

if (( dt_idx < 0 )); then
    echo "FAIL: --disallowedTools absent from judge argv" >&2
    fail=1
else
    echo "ok - --disallowedTools present"
    names=0
    for ((i=dt_idx+1; i<${#argv[@]}; i++)); do
        el="${argv[$i]}"
        [[ "$el" == --* ]] && break
        if [[ "$el" == *,* ]]; then
            echo "FAIL: denylist element '$el' contains a comma - this is the comma-joined form, not the validated ten-element spelling" >&2
            fail=1
            break
        fi
        names=$((names+1))
    done
    if (( names < 10 )); then
        echo "FAIL: only $names denylist tool-name elements, expected >= 10 separate elements" >&2
        fail=1
    else
        echo "ok - $names separate comma-free denylist elements"
    fi
fi

if (( fail )); then
    echo "PROBE: FAIL" >&2
    exit 1
fi
echo "PROBE: PASS"
exit 0
