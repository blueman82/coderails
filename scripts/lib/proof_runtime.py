"""Resolve the pinned proof sandbox and build a private checkout of committed source."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

SRT_VERSION = "0.0.65"
SRT_CLI_SHA256 = "82f74bc369958fbe014514cd518029a7324b5bd524f34069589d7674efe45dd0"
TRUSTED_PATH = "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin"


def trusted_executable(name: str, source: Path) -> str:
    """Resolve controller binaries from fixed system locations, never inherited PATH."""
    choices = {
        "git": ("/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"),
        "node": ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"),
    }
    current = source.resolve()
    root = next((parent for parent in (current, *current.parents) if (parent / ".git").exists()), current)
    for candidate in choices[name]:
        try:
            binary = Path(candidate).resolve(strict=True)
            if binary.is_file() and os.access(binary, os.X_OK) and not binary.is_relative_to(root):
                return str(binary)
        except OSError:
            continue
    raise OSError(f"trusted {name} executable is unavailable")


def git_environment() -> dict[str, str]:
    """Keep repository Git settings and inherited helper paths out of controller Git calls."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, PATH=TRUSTED_PATH)
    return environment


def runtime_argv(source: Path) -> list[str]:
    """Use the pinned cached CLI by absolute path, never repository npm resolution."""
    node = trusted_executable("node", source)
    cache = (Path.home() / ".npm/_npx").resolve()
    current = source.resolve()
    root = next((parent for parent in (current, *current.parents) if (parent / ".git").exists()), current)
    if cache.is_relative_to(root):
        raise OSError("pinned proof sandbox is unavailable")
    for manifest in sorted(cache.glob("*/node_modules/@anthropic-ai/sandbox-runtime/package.json")):
        try:
            package = manifest.parent.resolve(strict=True)
            cli = (package / "dist/cli.js").resolve(strict=True)
            if not package.is_relative_to(cache) or not cli.is_relative_to(package):
                continue
            if json.loads(manifest.read_text()).get("version") != SRT_VERSION:
                continue
            if hashlib.sha256(cli.read_bytes()).hexdigest() == SRT_CLI_SHA256:
                return [node, str(cli)]
        except (OSError, ValueError):
            continue
    raise OSError("pinned proof sandbox is unavailable")


def source_snapshot(cwd: Path, head: str, scratch: Path) -> tuple[Path, Path, str]:
    """Check out HEAD from Git objects, without copying mutable working files."""
    git = trusted_executable("git", cwd)
    environment = git_environment()
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
    entries = subprocess.run(
        [git, "-C", str(snapshot), "ls-files", "--stage", "-z"],
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if entries.returncode or any(item.startswith(b"120000 ") for item in entries.stdout.split(b"\0")):
        raise OSError("proof source snapshot has a tracked symlink or unreadable index")
    return snapshot / relative, source, lines[2]
