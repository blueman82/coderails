"""Preserve tracked executable modes and the release-archive executable fallback."""

import subprocess
from pathlib import Path


def arm_scripts(root: Path, *, dry_run: bool) -> None:
    """Honor index modes and retain executable fallback for untracked or archive files."""
    paths = set((root / "scripts").rglob("*.py"))
    paths.update((root / "hooks/scripts").rglob("*.py"))
    paths.update((root / "skills").glob("*/scripts/*.py"))
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            continue
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-s", "--", str(path.relative_to(root))],
            capture_output=True,
            text=True,
            check=False,
        )
        mode = result.stdout.split()[0] if result.stdout.strip() else ""
        executable = mode == "100755" if mode in {"100644", "100755"} else True
        if dry_run:
            print(
                f"would: chmod {'+x' if executable else '-x'} {path}"
                + (f" ({mode} in index)" if mode else " (not in index)")
            )
        else:
            current = path.stat().st_mode & 0o777
            path.chmod(current | 0o111 if executable else current & ~0o111)
