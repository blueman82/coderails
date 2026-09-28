"""Safe local installer file operations and canonical semantic materialization."""

import os
import tempfile
from pathlib import Path

SEMANTIC_TARGETS = (
    "skills/agentic-loop/scripts/graph_semantics.py",
    "packages/codex/skills/agentic-loop/scripts/graph_semantics.py",
)


def atomic_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Replace a sibling temporary file atomically without retaining open descriptors."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".coderails-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def materialize(root: Path, *, dry_run: bool) -> None:
    """Copy canonical semantic source into independent provider distributions."""
    source = root / "packages/graph-semantics/graph_semantics.py"
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Invalid canonical semantic source: {source}")
    pairs = [(source, root / relative) for relative in SEMANTIC_TARGETS]
    output_source = root / "hooks/scripts/test_output.py"
    if output_source.exists() or output_source.is_symlink():
        pairs.append((output_source, root / "packages/codex/hooks/scripts/test_output.py"))
    for origin, target in pairs:
        if origin.is_symlink() or not origin.is_file():
            raise ValueError(f"Invalid canonical source: {origin}")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Invalid materialization target: {target}")
    for origin, target in pairs:
        data = origin.read_bytes()
        if dry_run:
            print(f"would: materialize {origin} → {target}")
        elif not target.exists() or target.read_bytes() != data:
            atomic_bytes(target, data)


def confirm(prompt: str) -> bool:
    """Treat EOF as the default no when offering a local overwrite."""
    try:
        return input(prompt).strip().lower() == "y"
    except EOFError:
        return False
