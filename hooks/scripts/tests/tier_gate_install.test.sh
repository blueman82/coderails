#!/bin/bash
# Behavioural tests for scripts/tier-gate/install.sh — preflight predicates,
# plist rendering, and the diff-before-promote computation. These are the
# parts of install.sh with no root/sudo/interactive side effect (see the
# file's own header comment): the test sources it (main-guard prevents the
# real sudo-install path from running) and calls the pure functions directly.
# Never runs sudo, never touches /etc or /Library/LaunchDaemons for real.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
INSTALLER="$REPO_ROOT/scripts/tier-gate/install.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
check() { # desc expected actual
    if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_contains() { # desc pattern haystack
    if printf '%s' "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected to contain: %s\n  actual: %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_not_contains() { # desc pattern haystack
    if printf '%s' "$3" | grep -qF "$2"; then
        printf 'FAIL - %s\n  expected NOT to contain: %s\n  actual: %s\n' "$1" "$2" "$3"; fails=$((fails+1))
    else printf 'ok   - %s\n' "$1"
    fi
}

# ─── Source the installer (main-guard prevents the sudo path from running) ───
source "$INSTALLER"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_check_tools
# ═══════════════════════════════════════════════════════════════════════════

# Build a fake PATH directory with only some tools present, to control
# command -v resolution without touching the real PATH tools.
FAKEBIN="$TMP/fakebin"
mkdir -p "$FAKEBIN"
for t in gh jq curl; do
    printf '#!/bin/bash\nexit 0\n' > "$FAKEBIN/$t"
    chmod +x "$FAKEBIN/$t"
done

out=$(PATH="$FAKEBIN" tgi_check_tools 2>&1)
rc=$?
check "tgi_check_tools: all present -> rc 0" "0" "$rc"
check "tgi_check_tools: all present -> no output" "" "$out"

rm "$FAKEBIN/jq"
out=$(PATH="$FAKEBIN" tgi_check_tools 2>&1)
rc=$?
check "tgi_check_tools: jq missing -> rc 1" "1" "$rc"
check_contains "tgi_check_tools: jq missing -> named message" 'missing required tool "jq"' "$out"
check_not_contains "tgi_check_tools: jq missing -> gh not also named" 'missing required tool "gh"' "$out"

out=$(PATH="/nonexistent-dir-xyz" tgi_check_tools 2>&1)
rc=$?
check "tgi_check_tools: none present -> rc 1" "1" "$rc"
check_contains "tgi_check_tools: none present -> names gh" 'missing required tool "gh"' "$out"
check_contains "tgi_check_tools: none present -> names jq" 'missing required tool "jq"' "$out"
check_contains "tgi_check_tools: none present -> names curl" 'missing required tool "curl"' "$out"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_check_credentials
# ═══════════════════════════════════════════════════════════════════════════

CREDS_MISSING="$TMP/no-such-creds"
out=$(tgi_check_credentials "$CREDS_MISSING" 2>&1)
rc=$?
check "tgi_check_credentials: file absent -> rc 1" "1" "$rc"
check_contains "tgi_check_credentials: file absent -> named message" "credentials file not found at $CREDS_MISSING" "$out"

CREDS_EMPTY="$TMP/creds-empty"
: > "$CREDS_EMPTY"
out=$(tgi_check_credentials "$CREDS_EMPTY" 2>&1)
rc=$?
check "tgi_check_credentials: empty file -> rc 1" "1" "$rc"
check_contains "tgi_check_credentials: empty file -> names GH_TOKEN" "missing a non-empty GH_TOKEN=" "$out"
check_contains "tgi_check_credentials: empty file -> names ANTHROPIC_API_KEY" "missing a non-empty ANTHROPIC_API_KEY=" "$out"

CREDS_ONE_KEY="$TMP/creds-one-key"
printf 'GH_TOKEN=ghp_fake\n' > "$CREDS_ONE_KEY"
out=$(tgi_check_credentials "$CREDS_ONE_KEY" 2>&1)
rc=$?
check "tgi_check_credentials: only GH_TOKEN -> rc 1" "1" "$rc"
check_not_contains "tgi_check_credentials: only GH_TOKEN -> does not also complain about GH_TOKEN" "missing a non-empty GH_TOKEN=" "$out"
check_contains "tgi_check_credentials: only GH_TOKEN -> names missing ANTHROPIC_API_KEY" "missing a non-empty ANTHROPIC_API_KEY=" "$out"

CREDS_BOTH="$TMP/creds-both"
printf 'GH_TOKEN=ghp_fake\nANTHROPIC_API_KEY=sk-ant-fake\n' > "$CREDS_BOTH"
out=$(tgi_check_credentials "$CREDS_BOTH" 2>&1)
rc=$?
check "tgi_check_credentials: both keys -> rc 0" "0" "$rc"
check "tgi_check_credentials: both keys -> no output" "" "$out"

CREDS_BLANK_VAL="$TMP/creds-blank-val"
printf 'GH_TOKEN=\nANTHROPIC_API_KEY=sk-ant-fake\n' > "$CREDS_BLANK_VAL"
out=$(tgi_check_credentials "$CREDS_BLANK_VAL" 2>&1)
rc=$?
check "tgi_check_credentials: blank GH_TOKEN value -> rc 1 (not just key presence)" "1" "$rc"
check_contains "tgi_check_credentials: blank GH_TOKEN value -> named message" "missing a non-empty GH_TOKEN=" "$out"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_check_machine_user_collaborator
# ═══════════════════════════════════════════════════════════════════════════

out=$(tgi_check_machine_user_collaborator "" 2>&1)
rc=$?
check "tgi_check_machine_user_collaborator: empty login -> rc 1" "1" "$rc"
check_contains "tgi_check_machine_user_collaborator: empty login -> named message" "no machine-user login provided" "$out"

GH_STUB_OK="$TMP/gh-collab-ok"
cat > "$GH_STUB_OK" <<'EOF'
#!/bin/bash
exit 0
EOF
chmod +x "$GH_STUB_OK"
out=$(tgi_check_machine_user_collaborator "coderails-tier-bot" "$GH_STUB_OK" 2>&1)
rc=$?
check "tgi_check_machine_user_collaborator: gh reports collaborator -> rc 0" "0" "$rc"
check "tgi_check_machine_user_collaborator: gh reports collaborator -> no output" "" "$out"

GH_STUB_404="$TMP/gh-collab-404"
cat > "$GH_STUB_404" <<'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$GH_STUB_404"
out=$(tgi_check_machine_user_collaborator "not-a-collaborator" "$GH_STUB_404" 2>&1)
rc=$?
check "tgi_check_machine_user_collaborator: gh reports not-found -> rc 1" "1" "$rc"
check_contains "tgi_check_machine_user_collaborator: gh reports not-found -> named message" 'machine user "not-a-collaborator" is not resolvable as a collaborator' "$out"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_render_plist
# ═══════════════════════════════════════════════════════════════════════════

TEMPLATE="$REPO_ROOT/scripts/tier-gate/com.coderails.tier-gate.plist.template"
rendered=$(tgi_render_plist "$TEMPLATE" "/etc/coderails-tier-gate/tier-gate-runner.sh" "/etc/coderails-tier-gate/credentials")
check_contains "tgi_render_plist: substitutes runner path" "<string>/etc/coderails-tier-gate/tier-gate-runner.sh</string>" "$rendered"
check_contains "tgi_render_plist: substitutes creds path" "<string>/etc/coderails-tier-gate/credentials</string>" "$rendered"
check_not_contains "tgi_render_plist: no placeholder tokens remain (runner)" "__TIER_GATE_RUNNER_PATH__" "$rendered"
check_not_contains "tgi_render_plist: no placeholder tokens remain (creds)" "__TIER_GATE_CREDS_PATH__" "$rendered"
check_contains "tgi_render_plist: preserves unrelated template content" "<string>com.coderails.tier-gate</string>" "$rendered"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_diff_before_promote
# ═══════════════════════════════════════════════════════════════════════════

REPO_COPY="$TMP/repo-runner.sh"
printf '#!/bin/bash\necho hello\n' > "$REPO_COPY"

NO_INSTALLED="$TMP/no-such-installed-runner.sh"
out=$(tgi_diff_before_promote "$REPO_COPY" "$NO_INSTALLED" "runner" 2>&1)
rc=$?
check "tgi_diff_before_promote: no installed copy -> rc 0 (first install)" "0" "$rc"
check_contains "tgi_diff_before_promote: no installed copy -> says first install" "no installed copy yet" "$out"

INSTALLED_SAME="$TMP/installed-runner-same.sh"
cp "$REPO_COPY" "$INSTALLED_SAME"
out=$(tgi_diff_before_promote "$REPO_COPY" "$INSTALLED_SAME" "runner" 2>&1)
rc=$?
check "tgi_diff_before_promote: identical -> rc 0" "0" "$rc"
check_contains "tgi_diff_before_promote: identical -> says no change" "no change" "$out"

INSTALLED_DIFF="$TMP/installed-runner-diff.sh"
printf '#!/bin/bash\necho TAMPERED\n' > "$INSTALLED_DIFF"
out=$(tgi_diff_before_promote "$REPO_COPY" "$INSTALLED_DIFF" "runner" 2>&1)
rc=$?
check "tgi_diff_before_promote: differs -> rc 1 (must gate on confirmation)" "1" "$rc"
check_contains "tgi_diff_before_promote: differs -> flags DIFFERS" "DIFFERS from installed copy" "$out"
check_contains "tgi_diff_before_promote: differs -> shows the actual delta" "TAMPERED" "$out"

# ═══════════════════════════════════════════════════════════════════════════
echo "───"
if [[ "$fails" -eq 0 ]]; then echo "PASS"; exit 0
else echo "FAILED ($fails)"; exit 1
fi
