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
check_contains "tgi_check_credentials: empty file -> names CLAUDE_CODE_OAUTH_TOKEN" "missing a non-empty CLAUDE_CODE_OAUTH_TOKEN=" "$out"
check_contains "tgi_check_credentials: empty file -> names MACHINE_USER" "missing a non-empty MACHINE_USER=" "$out"

CREDS_ONE_KEY="$TMP/creds-one-key"
printf 'GH_TOKEN=ghp_fake\n' > "$CREDS_ONE_KEY"
out=$(tgi_check_credentials "$CREDS_ONE_KEY" 2>&1)
rc=$?
check "tgi_check_credentials: only GH_TOKEN -> rc 1" "1" "$rc"
check_not_contains "tgi_check_credentials: only GH_TOKEN -> does not also complain about GH_TOKEN" "missing a non-empty GH_TOKEN=" "$out"
check_contains "tgi_check_credentials: only GH_TOKEN -> names missing CLAUDE_CODE_OAUTH_TOKEN" "missing a non-empty CLAUDE_CODE_OAUTH_TOKEN=" "$out"
check_contains "tgi_check_credentials: only GH_TOKEN -> names missing MACHINE_USER" "missing a non-empty MACHINE_USER=" "$out"

CREDS_TWO_KEYS="$TMP/creds-two-keys"
printf 'GH_TOKEN=ghp_fake\nCLAUDE_CODE_OAUTH_TOKEN=oat-fake\n' > "$CREDS_TWO_KEYS"
out=$(tgi_check_credentials "$CREDS_TWO_KEYS" 2>&1)
rc=$?
check "tgi_check_credentials: two of three keys (no MACHINE_USER) -> rc 1" "1" "$rc"
check_contains "tgi_check_credentials: two of three keys -> names missing MACHINE_USER" "missing a non-empty MACHINE_USER=" "$out"

CREDS_ALL_THREE="$TMP/creds-all-three"
printf 'GH_TOKEN=ghp_fake\nCLAUDE_CODE_OAUTH_TOKEN=oat-fake\nMACHINE_USER=coderails-tier-bot\n' > "$CREDS_ALL_THREE"
out=$(tgi_check_credentials "$CREDS_ALL_THREE" 2>&1)
rc=$?
check "tgi_check_credentials: all three keys -> rc 0" "0" "$rc"
check "tgi_check_credentials: all three keys -> no output" "" "$out"

CREDS_BLANK_VAL="$TMP/creds-blank-val"
printf 'GH_TOKEN=\nCLAUDE_CODE_OAUTH_TOKEN=oat-fake\nMACHINE_USER=coderails-tier-bot\n' > "$CREDS_BLANK_VAL"
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
# tgi_read_machine_user_from_creds — defaults TGI_MACHINE_USER from the
# MACHINE_USER= line already stored in the credentials file, so a re-install
# doesn't demand a value the machine already knows.
# ═══════════════════════════════════════════════════════════════════════════

CREDS_WITH_USER="$TMP/creds-with-machine-user"
printf 'GH_TOKEN=ghp_fake\nCLAUDE_CODE_OAUTH_TOKEN=oat-fake\nMACHINE_USER=coderails-tier-bot\n' > "$CREDS_WITH_USER"
out=$(tgi_read_machine_user_from_creds "$CREDS_WITH_USER" 2>&1)
rc=$?
check "tgi_read_machine_user_from_creds: creds file has MACHINE_USER -> rc 0" "0" "$rc"
check "tgi_read_machine_user_from_creds: creds file has MACHINE_USER -> echoes the login" "coderails-tier-bot" "$out"

out=$(tgi_read_machine_user_from_creds "$CREDS_EMPTY" 2>&1)
rc=$?
check "tgi_read_machine_user_from_creds: creds file has no MACHINE_USER -> rc 1" "1" "$rc"
check "tgi_read_machine_user_from_creds: creds file has no MACHINE_USER -> echoes nothing" "" "$out"

out=$(tgi_read_machine_user_from_creds "$TMP/no-such-creds-xyz" 2>&1)
rc=$?
check "tgi_read_machine_user_from_creds: creds file absent -> rc 1" "1" "$rc"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_render_plist
# ═══════════════════════════════════════════════════════════════════════════

TEMPLATE="$REPO_ROOT/scripts/tier-gate/com.coderails.tier-gate.plist.template"
rendered=$(tgi_render_plist "$TEMPLATE" "/etc/coderails-tier-gate/tier-gate-runner.sh" "/etc/coderails-tier-gate/credentials" "octo/some-repo")
check_contains "tgi_render_plist: substitutes runner path" "<string>/etc/coderails-tier-gate/tier-gate-runner.sh</string>" "$rendered"
check_contains "tgi_render_plist: substitutes creds path" "<string>/etc/coderails-tier-gate/credentials</string>" "$rendered"
check_contains "tgi_render_plist: substitutes repo slug into TIER_GATE_REPO" "<string>octo/some-repo</string>" "$rendered"
check_not_contains "tgi_render_plist: no placeholder tokens remain (runner)" "__TIER_GATE_RUNNER_PATH__" "$rendered"
check_not_contains "tgi_render_plist: no placeholder tokens remain (creds)" "__TIER_GATE_CREDS_PATH__" "$rendered"
check_not_contains "tgi_render_plist: no placeholder tokens remain (repo)" "__TIER_GATE_REPO__" "$rendered"
check_contains "tgi_render_plist: preserves unrelated template content" "<string>com.coderails.tier-gate</string>" "$rendered"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_resolve_repo_slug — resolves the owner/repo slug rendered into the plist's
# TIER_GATE_REPO. Uses an injectable gh stub (like tgi_check_machine_user_
# collaborator's [gh_bin]) so it's testable without a real gh/network.
# ═══════════════════════════════════════════════════════════════════════════

GH_SLUG_OK="$TMP/gh-slug-ok"
cat > "$GH_SLUG_OK" <<'EOF'
#!/bin/bash
echo "blueman82/coderails"
EOF
chmod +x "$GH_SLUG_OK"
out=$(tgi_resolve_repo_slug "$GH_SLUG_OK" 2>&1)
rc=$?
check "tgi_resolve_repo_slug: gh returns owner/repo -> rc 0" "0" "$rc"
check "tgi_resolve_repo_slug: gh returns owner/repo -> echoes the slug" "blueman82/coderails" "$out"

GH_SLUG_EMPTY="$TMP/gh-slug-empty"
cat > "$GH_SLUG_EMPTY" <<'EOF'
#!/bin/bash
echo ""
EOF
chmod +x "$GH_SLUG_EMPTY"
out=$(tgi_resolve_repo_slug "$GH_SLUG_EMPTY" 2>&1)
rc=$?
check "tgi_resolve_repo_slug: gh returns empty -> rc 1 (fail loudly, never blank)" "1" "$rc"
check "tgi_resolve_repo_slug: gh returns empty -> echoes nothing" "" "$out"

GH_SLUG_FAIL="$TMP/gh-slug-fail"
cat > "$GH_SLUG_FAIL" <<'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$GH_SLUG_FAIL"
out=$(tgi_resolve_repo_slug "$GH_SLUG_FAIL" 2>&1)
rc=$?
check "tgi_resolve_repo_slug: gh call fails -> rc 1" "1" "$rc"

GH_SLUG_MALFORMED="$TMP/gh-slug-malformed"
cat > "$GH_SLUG_MALFORMED" <<'EOF'
#!/bin/bash
echo "not-a-valid-slug"
EOF
chmod +x "$GH_SLUG_MALFORMED"
out=$(tgi_resolve_repo_slug "$GH_SLUG_MALFORMED" 2>&1)
rc=$?
check "tgi_resolve_repo_slug: gh returns a malformed slug -> rc 1 (never renders junk)" "1" "$rc"

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
# tgi_same_file — resolved-path comparison guarding the creds install copy
# against `install: src and dst are the same file` when TGI_CREDS_SRC
# defaults to the install destination (the normal re-install case).
# ═══════════════════════════════════════════════════════════════════════════

SAME_A="$TMP/same-file-a"
printf 'creds\n' > "$SAME_A"
out=$(tgi_same_file "$SAME_A" "$SAME_A" 2>&1)
rc=$?
check "tgi_same_file: identical path -> rc 0 (same file)" "0" "$rc"

SAME_B="$TMP/same-file-b"
printf 'other\n' > "$SAME_B"
out=$(tgi_same_file "$SAME_A" "$SAME_B" 2>&1)
rc=$?
check "tgi_same_file: two distinct files -> rc 1 (different)" "1" "$rc"

SAME_LINK="$TMP/same-file-link"
ln -sf "$SAME_A" "$SAME_LINK"
out=$(tgi_same_file "$SAME_A" "$SAME_LINK" 2>&1)
rc=$?
check "tgi_same_file: symlink to same target -> rc 0 (same file)" "0" "$rc"

SAME_HARDLINK="$TMP/same-file-hardlink"
ln -f "$SAME_A" "$SAME_HARDLINK"
out=$(tgi_same_file "$SAME_A" "$SAME_HARDLINK" 2>&1)
rc=$?
check "tgi_same_file: hardlink to same inode -> rc 0 (same file, what install itself checks)" "0" "$rc"

mkdir -p "$TMP/subdir"
SAME_DOTDOT="$TMP/subdir/../same-file-a"
out=$(tgi_same_file "$SAME_A" "$SAME_DOTDOT" 2>&1)
rc=$?
check "tgi_same_file: non-canonical ../ path to same file -> rc 0 (same file)" "0" "$rc"

out=$(tgi_same_file "$SAME_A" "$TMP/no-such-file-xyz" 2>&1)
rc=$?
check "tgi_same_file: dst does not exist -> rc 1 (never same, install proceeds)" "1" "$rc"

# ═══════════════════════════════════════════════════════════════════════════
# tgi_other_instance_labels — shared-install-root warning: names OTHER
# installed tier-gate plists (any repo) so the confirmation prompt surfaces
# them without requiring the operator to have read docs/comments first.
# ═══════════════════════════════════════════════════════════════════════════

OTHER_DIR="$TMP/other-plists"
mkdir -p "$OTHER_DIR"

THIS_PLIST="$OTHER_DIR/com.coderails.tier-gate.plist"
cat > "$THIS_PLIST" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.coderails.tier-gate</string>
</dict></plist>
EOF

OTHER_PLIST="$OTHER_DIR/com.coderails.tier-gate.assistant-agent.plist"
cat > "$OTHER_PLIST" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.coderails.tier-gate.assistant-agent</string>
</dict></plist>
EOF

if command -v /usr/libexec/PlistBuddy >/dev/null 2>&1; then
    out=$(tgi_other_instance_labels "$THIS_PLIST" "$OTHER_DIR/com.coderails.tier-gate*.plist" 2>&1)
    check "tgi_other_instance_labels: excludes plist_dest, echoes only the other Label" "com.coderails.tier-gate.assistant-agent" "$out"

    out=$(tgi_other_instance_labels "$THIS_PLIST" "$THIS_PLIST" 2>&1)
    check "tgi_other_instance_labels: only plist_dest matches glob -> no output" "" "$out"

    out=$(tgi_other_instance_labels "$TMP/no-such-plist" "$TMP/no-plists-here-*.plist" 2>&1)
    check "tgi_other_instance_labels: no matching plists -> no output" "" "$out"
else
    printf 'skip - tgi_other_instance_labels tests (PlistBuddy not available on this host)\n'
fi

# ═══════════════════════════════════════════════════════════════════════════
# tgi_classify_mode — honest MODE line from the ruleset preflight probe
# ═══════════════════════════════════════════════════════════════════════════

out=$(tgi_classify_mode '[]')
check "tgi_classify_mode: empty ruleset array -> audit" "MODE: audit (server leg absent) — verdict unforgeable, merge gate local-only and bypassable" "$out"

out=$(tgi_classify_mode '[{"type":"pull_request"}]')
check "tgi_classify_mode: non-empty ruleset array -> enforced" "MODE: enforced" "$out"

out=$(tgi_classify_mode '')
check "tgi_classify_mode: empty/unreadable response -> audit (honest under-claim, never enforced)" "MODE: audit (server leg absent) — verdict unforgeable, merge gate local-only and bypassable" "$out"

out=$(tgi_classify_mode 'not json')
check "tgi_classify_mode: malformed response -> audit (honest under-claim, never enforced)" "MODE: audit (server leg absent) — verdict unforgeable, merge gate local-only and bypassable" "$out"

# ═══════════════════════════════════════════════════════════════════════════
echo "───"
if [[ "$fails" -eq 0 ]]; then echo "PASS"; exit 0
else echo "FAILED ($fails)"; exit 1
fi
