#!/usr/bin/env bash
# coderails uninstall — reverses what install.sh changed in your dotfiles.
# Does NOT remove the plugin itself: run /plugin uninstall coderails for that.
# Does NOT delete your failure_log.md, discipline.log, or memory entries (your data; preserved).

set -u

echo "=== Remove discipline rules from CLAUDE.md ==="
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
if [ -f "$CLAUDE_MD" ] && grep -q "## Self-Checking Discipline" "$CLAUDE_MD"; then
  cp "$CLAUDE_MD" "$CLAUDE_MD.bak.$(date +%s)"
  # Remove from "## Self-Checking Discipline" through end-of-file OR the next column-0 "## " heading.
  awk '/^## Self-Checking Discipline/{flag=1; next} /^## /{if(flag){flag=0}} !flag' "$CLAUDE_MD" > "$CLAUDE_MD.tmp"
  mv "$CLAUDE_MD.tmp" "$CLAUDE_MD"
  echo "  ✓ removed Self-Checking Discipline section (backup at $CLAUDE_MD.bak.*)"
else
  echo "  · not present — nothing to remove"
fi

echo
echo "=== Drop coderails marketplace key from settings.json ==="
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ] && command -v jq >/dev/null 2>&1; then
  cp "$SETTINGS" "$SETTINGS.bak"
  tmp=$(mktemp)
  jq 'del(.extraKnownMarketplaces["coderails"])' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
  echo "  ✓ removed extraKnownMarketplaces.coderails (backup: settings.json.bak)"
else
  echo "  · settings.json or jq missing — skip"
fi

echo
echo "=== Drop coderails key from known_marketplaces.json ==="
# /plugin uninstall coderails doesn't touch this file, same as the old plugins.
KNOWN="$HOME/.claude/plugins/known_marketplaces.json"
if [ -f "$KNOWN" ] && command -v jq >/dev/null 2>&1; then
  cp "$KNOWN" "$KNOWN.bak"
  ktmp=$(mktemp)
  jq 'del(.["coderails"])' "$KNOWN" > "$ktmp" && mv "$ktmp" "$KNOWN"
  echo "  ✓ removed coderails (backup: known_marketplaces.json.bak)"
else
  echo "  · known_marketplaces.json or jq missing — skip"
fi

echo
echo "=== Note: the following are PRESERVED — your data ==="
echo "  · ~/.claude/failure_log.md   (your accumulated observations)"
echo "  · ~/.claude/discipline.log   (diagnostic data)"
echo "  · feedback memory files in ~/.claude/projects/*/memory/"
echo
echo "Delete those manually if you want a full reset."
echo
echo "Then run: /plugin uninstall coderails  (removes the hooks/commands/skills)"
