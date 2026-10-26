"""Resolve the pinned proof sandbox and build a private checkout of committed source."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

SRT_VERSION = "0.0.65"
SRT_CLI_SHA256 = "82f74bc369958fbe014514cd518029a7324b5bd524f34069589d7674efe45dd0"


def runtime_argv(source: Path) -> list[str]:
    """Use the pinned cached CLI by absolute path, never repository npm resolution."""
    node = shutil.which("node")
    cache = (Path.home() / ".npm/_npx").resolve()
    if not node or cache.is_relative_to(source):
        raise OSError("pinned proof sandbox is unavailable")
    executable = Path(node).resolve()
    if executable.is_relative_to(source):
        raise OSError("Node executable resolves inside source checkout")
    for manifest in sorted(cache.glob("*/node_modules/@anthropic-ai/sandbox-runtime/package.json")):
        try:
            package = manifest.parent.resolve(strict=True)
            cli = (package / "dist/cli.js").resolve(strict=True)
            if not package.is_relative_to(cache) or not cli.is_relative_to(package):
                continue
            if json.loads(manifest.read_text()).get("version") != SRT_VERSION:
                continue
            if hashlib.sha256(cli.read_bytes()).hexdigest() == SRT_CLI_SHA256:
                return [str(executable), str(cli)]
        except (OSError, ValueError):
            continue
    raise OSError("pinned proof sandbox is unavailable")


def source_snapshot(cwd: Path, head: str, scratch: Path) -> tuple[Path, Path, str]:
    """Check out HEAD from Git objects, without copying mutable working files."""
    git_command = shutil.which("git")
    if not git_command or Path(git_command).resolve().is_relative_to(cwd.resolve()):
        raise OSError("trusted Git executable is unavailable")
    git = str(Path(git_command).resolve())
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    context = subprocess.run(
        [git, "rev-parse", "--show-toplevel", "HEAD", "HEAD^{tree}"],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    lines = context.stdout.splitlines()
    if context.returncode or len(lines) != 3 or lines[1] != head:
        raise OSError("proof source HEAD changed or is unavailable")
    source = Path(lines[0]).resolve()
    try:
        relative = cwd.resolve().relative_to(source)
    except ValueError as error:
        raise OSError("proof working directory is outside source checkout") from error
    snapshot = scratch / "source"
    safe_git = [git, "-c", "core.hooksPath=/dev/null"]
    clone = subprocess.run(
        [*safe_git, "clone", "--no-local", "--no-checkout", "-q", "--", str(source), str(snapshot)],
        cwd=scratch,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if clone.returncode:
        raise OSError("proof source snapshot could not be created")
    checkout = subprocess.run(
        [*safe_git, "-C", str(snapshot), "checkout", "--detach", "-q", head],
        cwd=scratch,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if checkout.returncode:
        raise OSError("proof source snapshot could not be checked out")
    checked = subprocess.run(
        [git, "-C", str(snapshot), "rev-parse", "HEAD", "HEAD^{tree}"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if checked.returncode or checked.stdout.splitlines() != lines[1:]:
        raise OSError("proof source snapshot does not match HEAD")
    return snapshot / relative, source, lines[2]
