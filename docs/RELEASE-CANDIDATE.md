# Check a release candidate

Use this procedure after the source PRs merge. A draft PR and a local test do not make an installed release.

## Save the old state

Stop new graph work. Record the installed Claude and Codex plugin versions. Save the matching plugin files, workflow configuration, graph state, evaluation and proof files, retrospective files, and Muninn database. Keep the files in one dated backup. Record a SHA-256 hash for each backup file.

Keep the old plugin code with the old state. A code rollback alone cannot make a converted state readable by an older plugin.

## Check the source

Use a clean checkout of the reviewed merge commit. Supply the workflow configuration file by path. The manifest stores its hash and selected gate settings. It does not store the configuration path or private values.

```sh
python3 scripts/release_manifest.py snapshot --source-root . --config <config-path> > ../coderails-candidate.json
python3 install.py --provider claude --dry-run
python3 install.py --provider codex --dry-run
```

The output is a **candidate**. Review its repository, branch, commit, tree, gate settings, and file hashes. Do not use a pre-merge candidate as the final release record.

Copy each graph state to a private scratch directory. Run `graph.py convert --check` on each copy. If the check accepts it, run `convert` on the copy. Confirm that `progress.json.pre-convert` equals the original copy. Start a new process and run `graph.py inspect` on the converted copy. Conversion refuses an open wave, an invalid or future schema, and damaged dispatch records. Do not convert the live state during this check.

## Check the installed plugins

After the owner installs both providers, trusts the new Codex hooks, and starts fresh sessions, check explicit installed bundle paths:

```sh
python3 scripts/release_manifest.py verify ../coderails-candidate.json --source-root . --config <config-path> --claude-installed <claude-plugin-path> --codex-installed <codex-plugin-path>
python3 scripts/installed_parity.py --require-both --source-root . --claude-installed <claude-plugin-path> --codex-installed <codex-plugin-path>
```

The manifest check refuses an absent provider, a changed source commit or branch, a changed configuration, a missing or changed tracked runtime file, and an extra runtime file. It also refuses links inside an installed runtime path and ignored runtime files in the source checkout. This includes an ignored `node_modules` directory under a plugin runtime path. Python cache files in `__pycache__` are excluded; they can be rebuilt from the tracked source. The parity check reports extra installed files too. The manifest list excludes tests and non-runtime repository files; the Git tree hash binds the complete source checkout.

Run real allowed and denied control checks in fresh Claude and Codex sessions. Check a full loop, recovery, publication, and teardown. Capture real transcript observations only after the owner approves that capture. Run the Muninn restart and round-trip check with the owner. Record unavailable results as unavailable.

## Roll back

Stop both providers before rollback. Preserve the new state and its logs. Restore the prior plugin code **with the matching prior state and Muninn database backup**, then restart both providers. Keep the converted state and its `.pre-convert` copy for investigation. If new work changed the state after cutover, do not overwrite it with an older backup; stop and make a state-specific recovery plan.
