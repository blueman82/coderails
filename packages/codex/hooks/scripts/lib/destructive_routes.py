"""Safe alternatives emitted for permanent destructive-command denials."""

ROUTES = {
    "git-reset-hard": (
        "Safe route: park the commits first with 'git branch backup/<desc> <ref>', then use 'git reset "
        "--keep <ref>' instead of --hard — --keep applies the same move but REFUSES (errors out) rather"
        " than clobbering when it would discard uncommitted working-tree changes, and the backup branch"
        " keeps the moved-past commits recoverable either way."
    ),
    "rm-rf": (
        "Safe route: for a single file, use 'unlink <file>' instead of rm -rf. For a directory or "
        "multiple files, move the target into a temp dir (e.g. 'mkdir -p /tmp/trash && mv <target> "
        "/tmp/trash/') instead of deleting it outright."
    ),
    "git-push-force": (
        "Safe route: use 'git push --force-with-lease' instead of a naked --force — it refuses to "
        "overwrite a remote ref that has moved since your last fetch. Note --force-with-lease is ALSO "
        "blocked by this hook by default; add the exact line 'git-push-force-with-lease' to "
        ".codex/destructive_allowlist in the target repo to opt in before using it."
    ),
    "git-clean-force": (
        "Safe route: preview what would be removed first with 'git clean -n' (dry-run — lists targets, "
        "deletes nothing), or use 'git clean -i' for an interactive prompt per file/directory. Both are"
        " already permitted by this hook; only the force forms (-f/--force) are blocked."
    ),
    "find-delete": (
        "Safe route: there is no safe equivalent for the deletion itself. Preview the exact match set "
        "first by replacing -delete with -print (or -print0 piped to xargs -0 ls) and reviewing the "
        "list before deleting any other way. To allow this pattern, add a Bash permission rule to "
        "settings.json."
    ),
    "truncate-size": (
        "Safe route: there is no safe equivalent — truncate destroys file content in place. Back up the"
        " file first ('cp <file> <file>.bak') if you need to recover it, or find a non-destructive way "
        "to achieve the goal (e.g. rotate the log instead of truncating it). To allow this pattern, add"
        " a Bash permission rule to settings.json."
    ),
    "secure-wipe-delete": (
        "Safe route: there is no safe equivalent — shred exists specifically to make content "
        "unrecoverable. If you only meant to delete the file (not securely wipe it), move it to a temp "
        "dir instead ('mkdir -p /tmp/trash && mv <file> /tmp/trash/'). To allow shred itself, add a "
        "Bash permission rule to settings.json."
    ),
    "drop-table": (
        "Safe route: there is no safe equivalent — DROP permanently destroys the object and its data. "
        "Take a backup/dump first if the data must be recoverable, and confirm you're pointed at the "
        "intended database before running any destructive DDL directly. To allow this pattern, add a "
        "Bash permission rule to settings.json."
    ),
    "truncate-table": (
        "Safe route: there is no safe equivalent — TRUNCATE TABLE removes all rows and is not "
        "equivalent in safety to a scoped DELETE. Take a backup/dump first if the data must be "
        "recoverable. To allow this pattern, add a Bash permission rule to settings.json."
    ),
    "dd-if": (
        "Safe route: there is no safe equivalent — dd writes raw bytes to its target with no "
        "confirmation. Double-check the of= target device/file before running it directly, and confirm "
        "it isn't a mounted disk. To allow this pattern, add a Bash permission rule to settings.json."
    ),
    "mkfs-format": (
        "Safe route: there is no safe equivalent — mkfs reformats a filesystem and destroys existing "
        "data on it. Confirm the target device is correct (not a mounted or in-use disk) before running"
        " it directly. To allow this pattern, add a Bash permission rule to settings.json."
    ),
    "chmod-r-777": (
        "Safe route: use narrower recursive bits instead of a blanket 777 — 'chmod -R u+rwX,go+rX "
        "<path>' grants the owner read/write (and execute only on directories/already-executable files)"
        " while giving group/other read access, without making everything world-writable and world-"
        "executable."
    ),
    "dotenv-access": (
        "Safe route: don't read or write the secret file itself. To check whether a key is SET without "
        "revealing it, test the variable after loading it in a subshell (e.g. 'set -a; . ./.env; set "
        '+a; [ -n "$MY_KEY" ] && echo set\') — note that still requires an allow rule, so prefer asking '
        "the owner. To see the SHAPE of the file without its values, read the committed template "
        "instead ('cat .env.example'), which this hook already permits. To add or change a value, edit "
        "the file by hand outside the session. To allow this pattern, add a Bash permission rule to "
        "settings.json."
    ),
    "git-commit-no-verify": (
        "Safe route: fix the failing pre-commit hook and re-run 'git commit' without --no-verify, "
        "rather than bypassing it — the hook exists to catch something before commit. If the hook "
        "itself is broken (not the change), fix the hook, don't skip it."
    ),
}
