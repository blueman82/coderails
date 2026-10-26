#!/usr/bin/env python3
"""Make and check a candidate release manifest without changing an installation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib.config import load_config  # noqa: E402
from scripts.lib.git_common import repo_from_url  # noqa: E402

RUNTIME_DIRS = (".claude-plugin/", "agents/", "commands/", "hooks/", "instructions/", "scripts/", "skills/")
ROOT_FILES = frozenset({"AGENTS.md", "config.schema.json", "install.py", "wiki.schema.json"})
CODEX_PREFIX = "packages/codex/"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def digest(data: bytes) -> str:
    """Return one lowercase SHA-256 digest."""
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *arguments: str) -> str:
    """Read one Git value from the selected source checkout."""
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False, timeout=10
    )
    if result.returncode:
        raise ValueError("source_git_unavailable")
    return result.stdout.strip()


def identity(root: Path) -> dict[str, str]:
    """Bind the exact clean checkout, GitHub repository, branch, commit, and tree."""
    if root.is_symlink() or root.resolve() != Path(git(root, "rev-parse", "--show-toplevel")).resolve():
        raise ValueError("source_root_mismatch")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("source_dirty")
    remote = git(root, "remote", "get-url", "origin")
    if not remote.startswith(("git@github.com:", "https://github.com/", "ssh://git@github.com/")):
        raise ValueError("repository_invalid")
    repository = repo_from_url(remote)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository_invalid")
    return {
        "repository": f"github.com/{repository}",
        "ref": git(root, "symbolic-ref", "HEAD"),
        "commit": git(root, "rev-parse", "HEAD"),
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
    }


def _runtime_file(relative: str) -> tuple[str, str] | None:
    """Name tracked plugin files that an installed bundle must contain."""
    if "__pycache__" in Path(relative).parts or relative.endswith(".pyc") or Path(relative).name == ".DS_Store":
        return None
    if relative.startswith(CODEX_PREFIX):
        bundle, path = "codex", relative[len(CODEX_PREFIX) :]
    else:
        bundle, path = "claude", relative
    if not path or "tests" in Path(path).parts or path.endswith(("_test.py", ".test.ts", ".spec.ts")):
        return None
    if bundle == "claude" and path not in ROOT_FILES and not path.startswith(RUNTIME_DIRS):
        return None
    return bundle, path


def source_files(root: Path) -> dict[str, dict[str, str]]:
    """Hash all tracked plugin runtime files; the Git tree binds excluded repository files."""
    ignored = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if ignored.returncode:
        raise ValueError("source_git_unavailable")
    try:
        ignored_paths = [item.decode("utf-8") for item in ignored.stdout.split(b"\0") if item]
    except UnicodeError as error:
        raise ValueError("source_path_invalid") from error
    if any(_runtime_file(path) is not None for path in ignored_paths):
        raise ValueError("source_runtime_untracked")
    raw = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=False, timeout=10)
    if raw.returncode:
        raise ValueError("source_git_unavailable")
    files: dict[str, dict[str, str]] = {"claude": {}, "codex": {}}
    try:
        tracked = [item.decode("utf-8") for item in raw.stdout.split(b"\0") if item]
    except UnicodeError as error:
        raise ValueError("source_path_invalid") from error
    for relative in tracked:
        selected = _runtime_file(relative)
        if selected is None:
            continue
        bundle, path = selected
        source = root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError("source_file_missing")
        files[bundle][path] = digest(source.read_bytes())
    if not all(
        required in files[bundle]
        for bundle, required in (("claude", ".claude-plugin/plugin.json"), ("codex", ".codex-plugin/plugin.json"))
    ) or not all("hooks/hooks.json" in files[bundle] for bundle in files):
        raise ValueError("source_bundle_incomplete")
    return files


def configuration(path: Path) -> dict[str, Any]:
    """Bind exact config bytes and selected effective gate settings, never private values or paths."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("config_missing")
    values, findings = load_config(path)
    if findings:
        raise ValueError("config_invalid")
    integrity = values.get("integrity_review")
    evals = values.get("evals")
    return {
        "sha256": digest(path.read_bytes()),
        "gates": {
            "action_authority": values.get("action_authority"),
            "diff_manifest": values.get("diff_manifest"),
            "eval_level": values.get("eval_level"),
            "review_passes": values.get("review_passes"),
            "sandbox_workers": values.get("sandbox_workers"),
            "integrity_review.enabled": (
                cast("dict[str, object]", integrity).get("enabled") if isinstance(integrity, dict) else None
            ),
            "evals.require_signatures": (
                cast("dict[str, object]", evals).get("require_signatures") if isinstance(evals, dict) else None
            ),
        },
    }


def snapshot(root: Path, config: Path) -> dict[str, Any]:
    """Return a candidate; a later review must approve a merged release separately."""
    return {
        "schema_version": 1,
        "status": "candidate",
        **identity(root),
        "config": configuration(config),
        "files": source_files(root),
    }


def verify(manifest: object, root: Path, config: Path, claude: Path, codex: Path) -> None:
    """Refuse a changed source, config, or missing/changed installed runtime file."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest_invalid")
    record = cast("dict[str, object]", manifest)
    if record.get("schema_version") != 1 or record.get("status") != "candidate":
        raise ValueError("manifest_invalid")
    fresh_identity = identity(root)
    for field, current in fresh_identity.items():
        if record.get(field) != current:
            raise ValueError(f"{field}_changed")
    if record.get("config") != configuration(config):
        raise ValueError("config_changed")
    recorded_files = record.get("files")
    if not isinstance(recorded_files, dict):
        raise ValueError("manifest_files_changed")
    bundle_files = cast("dict[str, object]", recorded_files)
    if set(bundle_files) != {"claude", "codex"}:
        raise ValueError("manifest_files_changed")
    current_files = source_files(root)
    for bundle, expected in current_files.items():
        recorded = bundle_files.get(bundle)
        if not isinstance(recorded, dict):
            raise ValueError("manifest_files_changed")
        recorded = cast("dict[str, object]", recorded)
        if set(recorded) != set(expected):
            raise ValueError("manifest_files_changed")
        for relative, actual_sha in expected.items():
            stored_sha = recorded[relative]
            if not isinstance(stored_sha, str) or not SHA256.fullmatch(stored_sha) or stored_sha != actual_sha:
                raise ValueError("source_file_changed")
    for bundle, installed in (("claude", claude), ("codex", codex)):
        if installed.is_symlink() or not installed.is_dir():
            raise ValueError(f"{bundle}_install_missing")
        if installed.resolve().is_relative_to(root.resolve()):
            raise ValueError("installed_is_source")
        for candidate in installed.rglob("*"):
            relative = candidate.relative_to(installed).as_posix()
            source_relative = f"{CODEX_PREFIX}{relative}" if bundle == "codex" else relative
            selected = _runtime_file(source_relative)
            if selected is None:
                continue
            if candidate.is_symlink():
                raise ValueError("installed_path_symlink")
            if candidate.is_file() and selected[1] not in current_files[bundle]:
                raise ValueError("installed_file_extra")
        for relative, expected_sha in current_files[bundle].items():
            target = installed
            for part in Path(relative).parts:
                target /= part
                if target.is_symlink():
                    raise ValueError("installed_path_symlink")
            if not target.is_file():
                raise ValueError("installed_file_missing")
            if digest(target.read_bytes()) != expected_sha:
                raise ValueError("installed_file_changed")


def main(arguments: list[str] | None = None) -> int:
    """Print a candidate or check one against explicit installed roots."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--source-root", type=Path, required=True)
        command.add_argument("--config", type=Path, required=True)
        if name == "verify":
            command.add_argument("manifest", type=Path)
            command.add_argument("--claude-installed", type=Path, required=True)
            command.add_argument("--codex-installed", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        if args.command == "snapshot":
            print(json.dumps(snapshot(args.source_root, args.config), sort_keys=True, indent=2))
        else:
            verify(
                json.loads(args.manifest.read_text()),
                args.source_root,
                args.config,
                args.claude_installed,
                args.codex_installed,
            )
            print("candidate matches the source and both installed bundles")
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"release_manifest: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
