#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
DRY_RUN=0
MEMORY_TARGET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --memory-target) MEMORY_TARGET="${2:-}"; shift 2 ;;
    *) printf 'Unknown arg: %s\n' "$1" >&2; exit 1 ;;
  esac
done

# ── ANSI ──────────────────────────────────────────────────────────────────────
R='\033[0;31m'   BR='\033[1;31m'
G='\033[0;32m'   BG='\033[1;32m'
Y='\033[1;33m'
C='\033[0;36m'   BC='\033[1;36m'
M='\033[0;35m'   BM='\033[1;35m'
W='\033[1;37m'   DIM='\033[2m'
BLINK='\033[5m'  BOLD='\033[1m'
NC='\033[0m'

COLS=$(tput cols 2>/dev/null || echo 72)
INTERACTIVE=0
[[ -t 1 ]] && INTERACTIVE=1

# ── Helpers ───────────────────────────────────────────────────────────────────
center() {
  local text="$1" bare
  bare=$(printf '%s' "$text" | sed 's/\x1b\[[0-9;]*m//g')
  local pad=$(( (COLS - ${#bare}) / 2 ))
  printf "%${pad}s%b\n" "" "$text"
}

hline() { printf "${DIM}%${COLS}s${NC}\n" | tr ' ' '─'; }
dline() { printf "${C}%${COLS}s${NC}\n"  | tr ' ' '═'; }

box_top()    { printf "${C}╔"; printf '═%.0s' $(seq 1 $((COLS-2))); printf "╗${NC}\n"; }
box_bottom() { printf "${C}╚"; printf '═%.0s' $(seq 1 $((COLS-2))); printf "╝${NC}\n"; }
box_line() {
  local content="$1"
  local bare visible_len pad
  bare=$(printf '%b' "$content" | sed 's/\x1b\[[0-9;]*m//g')
  visible_len=${#bare}
  local inner=$((COLS - 4))
  pad=$((inner - visible_len))
  [[ $pad -lt 0 ]] && pad=0
  printf "${C}║${NC} %b%${pad}s ${C}║${NC}\n" "$content" ""
}
box_blank()  { printf "${C}║${NC}%$((COLS-2))s${C}║${NC}\n" ""; }

progress_bar() {
  local label="$1" filled="${2:-20}" total=20
  local bar="" i
  for ((i=0; i<filled; i++));  do bar+="█"; done
  for ((i=filled; i<total; i++)); do bar+="░"; done
  local pct=$(( filled * 100 / total ))
  printf "  ${BG}%-18s${NC} ${C}[${BG}%s${C}]${NC} ${W}%3d%%${NC}\n" "$label" "$bar" "$pct"
}

spin_check() {
  local label="$1" cmd="$2"
  local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
  if [[ "$INTERACTIVE" -eq 1 ]]; then
    local i=0
    while ! eval "$cmd" &>/dev/null; do
      printf "\r  ${BC}%s${NC} checking %-10s" "${frames[$((i % 10))]}" "$label"
      sleep 0.08
      ((i++))
      if [[ $i -gt 50 ]]; then break; fi
    done
    printf "\r%60s\r" ""
  fi
}

flash_ok()  { printf "  ${BG}[ ✔ FOUND    ]${NC}  ${W}%s${NC}\n" "$1"; }
flash_err() { printf "  ${BR}[ ✘ MISSING  ]${NC}  ${R}%s${NC}  →  ${Y}brew install %s${NC}\n" "$1" "$1"; }
flash_dry() { printf "  ${BC}[ ⟳ DRY-RUN  ]${NC}  ${W}would: %s${NC}\n" "$1"; }
flash_warn(){ printf "  ${Y}[ ⚠ CONFLICT ]${NC}  %s\n" "$1"; }
flash_cp()  { printf "  ${BG}[ ✔ COPIED   ]${NC}  ${W}%s${NC}\n" "$1"; }
flash_skip(){ printf "  ${DIM}[ · SKIP     ]${NC}  ${DIM}%s${NC}\n" "$1"; }

# ── Matrix rain intro (interactive only) ──────────────────────────────────────
matrix_rain() {
  [[ "$INTERACTIVE" -eq 0 ]] && return
  local chars='ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ01'
  local rows=10 cols=$COLS
  tput civis 2>/dev/null || true
  local r c ch
  for ((r=0; r<rows; r++)); do
    for ((c=0; c<cols; c++)); do
      ch="${chars:$((RANDOM % ${#chars})):1}"
      if (( RANDOM % 4 == 0 )); then
        printf "${BG}%s${NC}" "$ch"
      else
        printf "${G}%s${NC}" "$ch"
      fi
    done
    printf '\n'
    sleep 0.04
  done
  tput cvvis 2>/dev/null || true
  sleep 0.2
  for ((r=0; r<rows; r++)); do tput cuu1 2>/dev/null; tput el 2>/dev/null; done
}

# ── Title card ────────────────────────────────────────────────────────────────
print_title() {
  printf '\n'
  dline
  printf '\n'
  center "${BG} ██████╗ ██████╗ ██████╗ ███████╗██████╗  █████╗ ██╗██╗     ███████╗${NC}"
  center "${G}██╔════╝██╔═══██╗██╔══██╗██╔════╝██╔══██╗██╔══██╗██║██║     ██╔════╝${NC}"
  center "${BG}██║     ██║   ██║██║  ██║█████╗  ██████╔╝███████║██║██║     ███████╗${NC}"
  center "${G}██║     ██║   ██║██║  ██║██╔══╝  ██╔══██╗██╔══██║██║██║     ╚════██║${NC}"
  center "${BG}╚██████╗╚██████╔╝██████╔╝███████╗██║  ██║██║  ██║██║███████╗███████║${NC}"
  center "${G} ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝╚══════╝${NC}"
  printf '\n'
  center "${BC}▸▸  W O R K F L O W   +   G U A R D R A I L S  ◂◂${NC}"
  center "${DIM}claude code plugin  •  v1.0.0${NC}"
  printf '\n'
  dline
  printf '\n'
  if [[ "$DRY_RUN" -eq 1 ]]; then
    center "${BLINK}${Y}★  D R Y   R U N   M O D E  ★${NC}"
    center "${W}simulating all operations — nothing will change${NC}"
    printf '\n'
  fi
}

# ── Victory screen ────────────────────────────────────────────────────────────
victory() {
  printf '\n'
  dline
  printf '\n'
  if [[ "$INTERACTIVE" -eq 1 ]]; then
    local stars=('★' '✦' '✧' '✶' '✷' '✸' '✹')
    local colors=("$BG" "$BC" "$BM" "$Y" "$W")
    local i
    for i in 1 2 3; do
      local s="${stars[$((RANDOM % ${#stars[@]}))]}"
      local col="${colors[$((RANDOM % ${#colors[@]}))]}"
      center "${col}${s}  INSTALL COMPLETE  ${s}${NC}"
      sleep 0.15
      tput cuu1 2>/dev/null; tput el 2>/dev/null
    done
  fi
  center "${BG}✔  INSTALL COMPLETE${NC}"
  printf '\n'
  dline
}

# ── Claude Code steps box ────────────────────────────────────────────────────
print_claude_steps() {
  printf '\n'
  box_top
  box_blank
  box_line "$(printf "${BM}  ▶  RESTART CLAUDE CODE, THEN RUN IN ORDER:${NC}")"
  box_blank
  box_line "$(printf "  ${BC}1.${NC}  /plugin install ${W}coderails@coderails${NC}")"
  box_line "$(printf "  ${BC}2.${NC}  /plugin install ${W}pr-review-toolkit@claude-plugins-official${NC}")"
  box_line "$(printf "  ${BC}3.${NC}  ${W}/reload-plugins${NC}")"
  box_blank
  box_line "$(printf "${Y}  ▶  PER PROJECT (for any repo not configured above):${NC}")"
  box_blank
  box_line "$(printf "  ${BC}4.${NC}  ${W}/coderails:init${NC}  ${DIM}(scaffolds workflow.config.yaml per project)${NC}")"
  box_line "$(printf "  ${BC}5.${NC}  ${W}/coderails:test-gate-setup${NC}  ${DIM}(optional test gate)${NC}")"
  box_blank
  box_bottom
  printf '\n'
  printf "  ${DIM}marketplace already registered by this script — restart picks it up${NC}\n"
  printf "  ${BC}Full docs:${NC}  ${W}%s/README.md${NC}\n\n" "$PLUGIN_DIR"
}

# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

matrix_rain
print_title

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
printf "${BOLD}  SYSTEM CHECK${NC}\n"
hline
missing=0
total_tools=3
idx=0

for tool in gh jq git; do
  idx=$((idx + 1))
  spin_check "$tool" "command -v $tool"
  progress_bar "$tool" $((idx * 20 / total_tools))
  sleep 0.1
  if command -v "$tool" &>/dev/null; then
    flash_ok "$tool"
  else
    flash_err "$tool"
    missing=1
  fi
done

printf '\n'

if [[ "$missing" -eq 1 ]]; then
  hline
  center "${BR}✘  PREFLIGHT FAILED — install missing tools and re-run${NC}"
  hline
  printf '\n'
  exit 1
fi

progress_bar "ALL SYSTEMS" 20
printf '\n'

# ── 1b. Migration scan — old plugins must be uninstalled from the REPL first ──
# A shell script cannot uninstall a Claude Code plugin: only `/plugin uninstall`
# deregisters it (clears installed_plugins.json + the cache dir the hooks fire
# from). So if the superseded plugins are still installed we fail fast with the
# exact commands to run, rather than half-migrating into double-firing hooks.
printf "${BOLD}  MIGRATION SCAN${NC}\n"
hline

INSTALLED="$HOME/.claude/plugins/installed_plugins.json"
old_plugins=()
if [[ -f "$INSTALLED" ]]; then
  while IFS= read -r key; do
    [[ -n "$key" ]] && old_plugins+=("$key")
  done < <(jq -r '.plugins // {} | keys[]
                  | select(startswith("claude-guardrails@") or startswith("workflow-tools@"))' \
                 "$INSTALLED" 2>/dev/null)
fi

if [[ ${#old_plugins[@]} -gt 0 ]]; then
  printf '\n'
  center "${Y}⚠  SUPERSEDED PLUGINS STILL INSTALLED${NC}"
  printf '\n'
  for p in "${old_plugins[@]}"; do
    flash_warn "$p"
  done
  printf '\n'
  printf "  ${W}coderails replaces these. They must be removed first — and only${NC}\n"
  printf "  ${W}Claude Code can do it (a script can't deregister a plugin).${NC}\n"
  printf '\n'
  printf "  ${BC}In Claude Code, run:${NC}\n"
  for p in "${old_plugins[@]}"; do
    printf "      ${W}/plugin uninstall %s${NC}\n" "${p%@*}"
  done
  printf '\n'
  printf "  ${DIM}Then re-run this installer.${NC}\n"
  printf '\n'
  hline
  center "${BR}✘  MIGRATION REQUIRED — uninstall above, then re-run${NC}"
  hline
  printf '\n'
  exit 1
fi

center "${BG}✔  NO SUPERSEDED PLUGINS — CLEAR TO INSTALL${NC}"
printf '\n'

# ── 2. Conflict check ─────────────────────────────────────────────────────────
printf "${BOLD}  CONFLICT SCAN${NC}\n"
hline

COMMANDS_DIR="$HOME/.claude/commands"
conflicts=()
for cmd in workflow.md init.md prep.md push.md merge.md \
           assumptions.md notchecked.md disconfirm.md verify.md test-gate-setup.md; do
  [[ -f "$COMMANDS_DIR/$cmd" ]] && conflicts+=("$cmd")
done

if [[ ${#conflicts[@]} -gt 0 ]]; then
  printf '\n'
  center "${Y}⚠  EXISTING COMMAND FILES DETECTED${NC}"
  printf '\n'
  for f in "${conflicts[@]}"; do
    flash_warn "$COMMANDS_DIR/$f"
  done
  printf '\n'
  printf "  ${W}Plugin commands are namespaced (e.g. /coderails:workflow).${NC}\n"
  printf "  ${W}Overwrite to keep bare /workflow /prep /push /merge invocation.${NC}\n"
  printf '\n'

  if [[ "$DRY_RUN" -eq 1 ]]; then
    for cmd in "${conflicts[@]}"; do
      flash_dry "cp $PLUGIN_DIR/commands/$cmd → $COMMANDS_DIR/$cmd"
    done
  else
    if [[ "$INTERACTIVE" -eq 1 ]]; then
      printf "  ${BLINK}${Y}► PRESS [y] TO OVERWRITE  /  ANY OTHER KEY TO SKIP ◄${NC}  "
    else
      printf "  Overwrite? [y/N] "
    fi
    read -r answer || answer="n"   # EOF (non-interactive/piped) → skip, don't abort
    printf '\n'
    # Lowercase via tr, not ${answer,,} — the latter is bash 4+ only and macOS
    # ships bash 3.2 as /bin/bash, where it errors with "bad substitution".
    answer=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')
    if [[ "$answer" == "y" ]]; then
      for cmd in "${conflicts[@]}"; do
        cp "$PLUGIN_DIR/commands/$cmd" "$COMMANDS_DIR/$cmd"
        flash_cp "$cmd"
        sleep 0.1
      done
    else
      center "${Y}skipped — existing commands unchanged${NC}"
    fi
  fi
else
  center "${BG}✔  NO CONFLICTS FOUND${NC}"
fi

printf '\n'

# ── 3. chmod scripts ──────────────────────────────────────────────────────────
printf "${BOLD}  ARMING SCRIPTS${NC}\n"
hline

for script in scripts/push.sh scripts/merge.sh scripts/lib/git-common.sh \
              hooks/scripts/lib/agentic_loop_path.sh \
              hooks/scripts/lib/loop_state_common.sh \
              hooks/scripts/loop_state_guard.sh \
              hooks/scripts/loop_stall_guard.sh \
              hooks/scripts/inject_context.sh hooks/scripts/discipline_catchup.sh \
              hooks/scripts/check_confidence_labels.sh hooks/scripts/check_verify_loop.sh \
              hooks/scripts/destructive_bash_gate.sh hooks/scripts/test_gate.sh \
              hooks/scripts/inject_bootstrap.sh; do
  if [[ "$DRY_RUN" -eq 1 ]]; then
    flash_dry "chmod +x $PLUGIN_DIR/$script"
  else
    chmod +x "$PLUGIN_DIR/$script"
    flash_ok "$script"
  fi
  sleep 0.05
done

printf '\n'

# ── 4. Register marketplace + strip stale marketplace state ───────────────────
# The old plugins register a marketplace in THREE places that survive
# `/plugin uninstall`: settings.json:extraKnownMarketplaces, the REPL's own
# known_marketplaces.json, and (sometimes) a cache dir under plugins/marketplaces/.
# `/plugin uninstall` clears installed_plugins.json + the plugin cache but none of
# these. The migration scan (stage 1b) guarantees the plugins are already
# uninstalled by the time we get here, so it's safe to strip all three now.
printf "${BOLD}  REGISTERING MARKETPLACE${NC}\n"
hline

SETTINGS="$HOME/.claude/settings.json"
KNOWN="$HOME/.claude/plugins/known_marketplaces.json"
MKT_DIR="$HOME/.claude/plugins/marketplaces"

if [[ "$DRY_RUN" -eq 1 ]]; then
  flash_dry "merge extraKnownMarketplaces.coderails → $SETTINGS"
  flash_dry "  source.path = $PLUGIN_DIR"
  flash_dry "drop stale keys (settings + known_marketplaces): workflow-tools, claude-guardrails"
  flash_dry "remove empty stale marketplace cache dirs under $MKT_DIR (if any)"
else
  [[ -f "$SETTINGS" ]] || printf '{}\n' > "$SETTINGS"
  cp "$SETTINGS" "$SETTINGS.bak"
  tmp=$(mktemp)
  # Add coderails; strip the two superseded keys from the old separate installs.
  jq --arg path "$PLUGIN_DIR" '
      .extraKnownMarketplaces["coderails"] = {"source": {"source": "directory", "path": $path}}
      | del(.extraKnownMarketplaces["workflow-tools"], .extraKnownMarketplaces["claude-guardrails"])
    ' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
  flash_ok "registered coderails (backup: settings.json.bak)"
  flash_ok "removed stale settings keys: workflow-tools, claude-guardrails"

  # Mirror the strip in the REPL's own marketplace registry — `/plugin uninstall`
  # never touches this file, so the old marketplace lingers otherwise.
  if [[ -f "$KNOWN" ]]; then
    cp "$KNOWN" "$KNOWN.bak"
    ktmp=$(mktemp)
    jq 'del(.["workflow-tools"], .["claude-guardrails"])' "$KNOWN" > "$ktmp" && mv "$ktmp" "$KNOWN"
    flash_ok "removed stale known_marketplaces keys (backup: known_marketplaces.json.bak)"
  fi

  # Remove leftover marketplace cache dirs ONLY if they are genuinely empty
  # (contain zero files). Catches both a normal stale dir and the botched
  # literal-"$HOME" dir a past directory-source install can leave behind.
  # Guarded hard: never remove a dir that still holds files.
  if [[ -d "$MKT_DIR" ]]; then
    removed_any=0
    while IFS= read -r -d '' d; do
      base="$(basename "$d")"
      case "$base" in
        *claude-guardrails*|*workflow-tools*|'"$HOME'*)
          if [[ -z "$(find "$d" -type f -print -quit 2>/dev/null)" ]]; then
            # `-type d -empty -delete` removes the empty tree bottom-up and
            # physically cannot delete a dir that still holds a file — a hard
            # backstop to the -type f guard above. No `rm -rf`.
            find "$d" -depth -type d -empty -delete 2>/dev/null
            [[ ! -d "$d" ]] && { flash_ok "removed empty stale cache dir: $base"; removed_any=1; }
          else
            flash_skip "kept (not empty): $base"
          fi
          ;;
      esac
    done < <(find "$MKT_DIR" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
    [[ "$removed_any" -eq 0 ]] && flash_skip "no stale marketplace cache dirs"
  fi
fi

printf '\n'

# ── 5. Discipline rules → CLAUDE.md (idempotent append) ────────────────────────
printf "${BOLD}  DISCIPLINE RULES → CLAUDE.md${NC}\n"
hline

CLAUDE_MD="$HOME/.claude/CLAUDE.md"
DISCIPLINE_FILE="$PLUGIN_DIR/instructions/self-checking-discipline.md"

if [[ "$DRY_RUN" -eq 1 ]]; then
  flash_dry "append '## Self-Checking Discipline' section → $CLAUDE_MD"
elif grep -q "## Self-Checking Discipline" "$CLAUDE_MD" 2>/dev/null; then
  flash_skip "already present in CLAUDE.md (idempotent)"
else
  printf '\n' >> "$CLAUDE_MD"
  sed -n '/^## Self-Checking Discipline/,$p' "$DISCIPLINE_FILE" >> "$CLAUDE_MD"
  flash_ok "appended discipline rules"
fi

printf '\n'

# ── 6. Memory seeds ────────────────────────────────────────────────────────────
printf "${BOLD}  MEMORY SEEDS${NC}\n"
hline

if [[ -z "$MEMORY_TARGET" ]]; then
  CWD_SAN="$(printf '%s' "$PWD" | sed 's|/|-|g')"
  MEMORY_TARGET="$HOME/.claude/projects/${CWD_SAN}/memory"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  flash_dry "mkdir -p $MEMORY_TARGET"
  for f in "$PLUGIN_DIR"/starter-memory/feedback_*.md; do
    flash_dry "cp $(basename "$f") → $MEMORY_TARGET/ (skip if exists)"
  done
else
  mkdir -p "$MEMORY_TARGET"
  for f in "$PLUGIN_DIR"/starter-memory/feedback_*.md; do
    fname=$(basename "$f")
    dest="$MEMORY_TARGET/$fname"
    if [[ -f "$dest" ]]; then
      flash_skip "$fname (already present)"
    else
      cp "$f" "$dest"
      flash_cp "$fname"
    fi
  done
  printf "  ${DIM}target: %s${NC}\n" "$MEMORY_TARGET"
fi

printf '\n'

# ── 7. Failure-log template ────────────────────────────────────────────────────
printf "${BOLD}  FAILURE-LOG TEMPLATE${NC}\n"
hline

if [[ "$DRY_RUN" -eq 1 ]]; then
  flash_dry "cp failure_log.md → $HOME/.claude/failure_log.md (skip if exists)"
else
  dest="$HOME/.claude/failure_log.md"
  if [[ -f "$dest" ]]; then
    flash_skip "failure_log.md (already present, preserving your data)"
  else
    cp "$PLUGIN_DIR/templates/failure_log.md" "$dest"
    flash_cp "failure_log.md"
  fi
fi

printf '\n'

# ── 8. Claude Code steps ──────────────────────────────────────────────────────
print_claude_steps
victory
