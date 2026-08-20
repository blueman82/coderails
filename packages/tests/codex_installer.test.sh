#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
FAKE_BIN="$TMP/bin"
FAILS=0

cleanup() { rm -R "$TMP"; }
trap cleanup EXIT

pass() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n' "$1"; FAILS=$((FAILS + 1)); }
check() { local label="$1"; shift; if "$@"; then pass "$label"; else fail "$label"; fi; }

mkdir -p "$FAKE_BIN"
for tool in gh git jq; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_BIN/$tool"
  chmod +x "$FAKE_BIN/$tool"
done
printf '#!/usr/bin/env bash\n[[ "${1:-}" == cols ]] && printf "72\\n"\nexit 0\n' > "$FAKE_BIN/tput"
printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_BIN/sleep"
chmod +x "$FAKE_BIN/tput" "$FAKE_BIN/sleep"
cat > "$FAKE_BIN/codex" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == --version ]]; then
  printf 'codex-cli 0.148.0\n'
  exit 0
fi
if [[ "${CODEX_ASSERT_HOME_EXISTS:-0}" -eq 1 && ! -d "${CODEX_HOME:-}" ]]; then
  printf 'CODEX_HOME missing at plugin command: %s\n' "${CODEX_HOME:-<unset>}" >&2
  exit 86
fi
printf '%s\n' "$*" >> "$CODEX_LOG"
EOF
chmod +x "$FAKE_BIN/codex"

run_install() {
  local home="$1" log="$2" output="$3"
  shift 3
  HOME="$home" CODEX_LOG="$log" PATH="$FAKE_BIN:/usr/bin:/bin" \
    bash "$ROOT/install.sh" "$@" > "$output" 2>&1
}

run_explicit_codex_home_install() {
  local home="$1" codex_home="$2" log="$3" output="$4"
  shift 4
  HOME="$home" CODEX_HOME="$codex_home" CODEX_ASSERT_HOME_EXISTS=1 \
    CODEX_LOG="$log" PATH="$FAKE_BIN:/usr/bin:/bin" \
    bash "$ROOT/install.sh" "$@" > "$output" 2>&1
}

agent_names=(
  deploy-safety-reviewer design-scout disposition-scout docs-auditor loop-worker
  preflight-scout proof-author source-auditor spec-reviewer wiki-writer
)
read_only_agents=(
  deploy-safety-reviewer design-scout disposition-scout preflight-scout
  source-auditor spec-reviewer
)

# Default provider and explicit Claude mode must remain identical.
home="$TMP/claude-home"
mkdir -p "$home"
run_install "$home" "$TMP/default.log" "$TMP/default.out" --dry-run
default_rc=$?
run_install "$home" "$TMP/claude.log" "$TMP/claude.out" --provider claude --dry-run
claude_rc=$?
check "default provider matches explicit Claude dry-run" \
  bash -c '[[ "$1" -eq 0 && "$2" -eq 0 ]] && cmp -s "$3" "$4"' _ \
  "$default_rc" "$claude_rc" "$TMP/default.out" "$TMP/claude.out"

# Codex install stays isolated from Claude state and installs every packaged agent.
home="$TMP/codex-home"
log="$TMP/codex.log"
mkdir -p "$home/.claude"
printf 'leave me alone\n' > "$home/.claude/sentinel"
run_install "$home" "$log" "$TMP/codex.out" --provider codex
codex_rc=$?
check "Codex install succeeds" test "$codex_rc" -eq 0
check "Codex mode leaves Claude state untouched" \
  bash -c '[[ "$(find "$1" -type f | wc -l | tr -d " ")" == 1 ]] && grep -qx "leave me alone" "$1/sentinel"' _ \
  "$home/.claude"
check "Codex invokes the required plugin sequence" \
  bash -c '[[ "$(sed -n "1p" "$1")" == "plugin marketplace add $2" && "$(sed -n "2p" "$1")" == "plugin add coderails-codex@coderails" && "$(wc -l < "$1" | tr -d " ")" == 2 ]]' _ \
  "$log" "$ROOT"
check "Codex install explains skipped hooks" \
  grep -Fxq "Codex skips plugin hooks until you review and trust them." "$TMP/codex.out"
check "Codex install explains hook trust" \
  grep -Fxq "Start a fresh Codex session, run /hooks, then review and trust the Coderails hooks." "$TMP/codex.out"

# An explicit, absent CODEX_HOME exists before either plugin command runs.
explicit_home="$TMP/explicit-home"
explicit_codex_home="$TMP/explicit-codex-home"
explicit_log="$TMP/explicit-codex.log"
mkdir -p "$explicit_home"
explicit_started_absent=0
[[ ! -e "$explicit_codex_home" ]] && explicit_started_absent=1
run_explicit_codex_home_install "$explicit_home" "$explicit_codex_home" \
  "$explicit_log" "$TMP/explicit-codex.out" --provider codex
explicit_rc=$?
check "explicit CODEX_HOME exists before plugin commands" \
  bash -c '[[ "$1" -eq 1 && "$2" -eq 0 && -d "$3" && "$(wc -l < "$4" | tr -d " ")" == 2 ]]' _ \
  "$explicit_started_absent" "$explicit_rc" "$explicit_codex_home" "$explicit_log"

all_agents_ok=1
for name in "${agent_names[@]}"; do
  source_agent="$ROOT/packages/codex/agents/$name.toml"
  installed_agent="$home/.codex/agents/$name.toml"
  [[ -f "$source_agent" && ! -L "$source_agent" ]] || all_agents_ok=0
  [[ -f "$installed_agent" && ! -L "$installed_agent" ]] || all_agents_ok=0
  cmp -s "$source_agent" "$installed_agent" || all_agents_ok=0
  grep -Fxq '# Managed by Coderails Codex plugin' "$source_agent" || all_agents_ok=0
  grep -Eq '^name = ".+"$' "$source_agent" || all_agents_ok=0
  grep -Eq '^description = ".+"$' "$source_agent" || all_agents_ok=0
  grep -q '^developer_instructions = """$' "$source_agent" || all_agents_ok=0
  if [[ " ${read_only_agents[*]} " == *" $name "* ]]; then
    [[ "$(grep -c '^sandbox_mode = "read-only"$' "$source_agent")" -eq 1 ]] || all_agents_ok=0
  else
    ! grep -q '^sandbox_mode = ' "$source_agent" || all_agents_ok=0
  fi
  ! grep -Eiq 'claude|pr-review-toolkit|/security-review' "$source_agent" || all_agents_ok=0
done
[[ "$(find "$ROOT/packages/codex/agents" -maxdepth 1 -type f -name '*.toml' | wc -l | tr -d ' ')" == 10 ]] || all_agents_ok=0
check "all ten native Codex agents have safe provider-native settings" test "$all_agents_ok" -eq 1

# A byte-identical reinstall must not rewrite agent files.
before_inode=$(stat -f '%i' "$home/.codex/agents/loop-worker.toml")
run_install "$home" "$log" "$TMP/idempotent.out" --provider codex
after_inode=$(stat -f '%i' "$home/.codex/agents/loop-worker.toml")
check "byte-identical agents are skipped without rewrite" test "$before_inode" = "$after_inode"

# A managed local copy gets one backup and an atomic refresh.
managed="$home/.codex/agents/loop-worker.toml"
printf '\nstale managed copy\n' >> "$managed"
run_install "$home" "$log" "$TMP/update.out" --provider codex
update_rc=$?
backup_count=$(find "$home/.codex/agents" -maxdepth 1 -type f -name 'loop-worker.toml.coderails-backup-*' | wc -l | tr -d ' ')
backup_file=$(find "$home/.codex/agents" -maxdepth 1 -type f -name 'loop-worker.toml.coderails-backup-*' -print -quit)
check "managed agent update makes one backup" \
  bash -c '[[ "$1" -eq 0 && "$2" == 1 ]] && cmp -s "$3" "$4" && grep -q "stale managed copy" "$5"' _ \
  "$update_rc" "$backup_count" "$ROOT/packages/codex/agents/loop-worker.toml" "$managed" "$backup_file"

# Any unrelated collision refuses the whole agent/plugin operation before changes.
home="$TMP/collision-home"
log="$TMP/collision.log"
mkdir -p "$home/.codex/agents"
printf 'unrelated local agent\n' > "$home/.codex/agents/design-scout.toml"
if run_install "$home" "$log" "$TMP/collision.out" --provider codex; then
  collision_rc=0
else
  collision_rc=$?
fi
collision_files=$(find "$home/.codex/agents" -maxdepth 1 -type f | wc -l | tr -d ' ')
check "unrelated collision refuses atomically" \
  bash -c '[[ "$1" -ne 0 && "$2" == 1 && ! -e "$3" ]] && grep -qx "unrelated local agent" "$4"' _ \
  "$collision_rc" "$collision_files" "$log" "$home/.codex/agents/design-scout.toml"
check "failed Codex install does not show hook trust steps" \
  test "$(grep -Fc "Start a fresh Codex session, run /hooks" "$TMP/collision.out")" -eq 0

# Invalid providers and Claude-only options fail clearly.
home="$TMP/invalid-home"
mkdir -p "$home"
if run_install "$home" "$TMP/invalid.log" "$TMP/invalid.out" --provider other --dry-run; then invalid_rc=0; else invalid_rc=$?; fi
check "invalid provider is rejected" \
  bash -c '[[ "$1" -ne 0 ]] && grep -qi "invalid provider" "$2"' _ "$invalid_rc" "$TMP/invalid.out"
if run_install "$home" "$TMP/options.log" "$TMP/options.out" --provider codex --memory-target "$TMP/memory" --dry-run; then options_rc=0; else options_rc=$?; fi
check "Claude-only options are rejected in Codex mode" \
  bash -c '[[ "$1" -ne 0 ]] && grep -qi "Claude-only" "$2"' _ "$options_rc" "$TMP/options.out"

# Dry-run performs checks and reports actions without writes or Codex calls.
home="$TMP/dry-home"
log="$TMP/dry.log"
mkdir -p "$home"
run_install "$home" "$log" "$TMP/dry.out" --provider codex --dry-run
dry_rc=$?
check "Codex dry-run writes and invokes nothing" \
  bash -c '[[ "$1" -eq 0 && ! -e "$2/.codex" && ! -e "$3" ]] && grep -Fq "codex plugin marketplace add" "$4" && grep -Fq "coderails-codex@coderails" "$4"' _ \
  "$dry_rc" "$home" "$log" "$TMP/dry.out"
check "Codex dry-run describes hook trust" \
  grep -Fq "would: after installation, start a fresh Codex session, run /hooks, and review and trust the Coderails hooks; Codex skips plugin hooks until then." "$TMP/dry.out"

if [[ "$FAILS" -eq 0 ]]; then
  printf 'PASS\n'
  exit 0
fi
printf 'FAILED (%s)\n' "$FAILS"
exit 1
