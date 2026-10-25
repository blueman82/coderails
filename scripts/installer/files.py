"""Safe local installer file operations and canonical semantic materialization."""

import os
import tempfile
from pathlib import Path

PROVIDER_SCRIPT_DIRS = ("skills/agentic-loop/scripts", "packages/codex/skills/agentic-loop/scripts")
SHARED_MODULES = ("graph_semantics", "node_metadata", "graph_vocab", "graph_convert")
SEMANTIC_TARGETS = tuple(
    (f"packages/graph-semantics/{name}.py", tuple(f"{directory}/{name}.py" for directory in PROVIDER_SCRIPT_DIRS))
    for name in SHARED_MODULES
)  # (canonical source, provider copies); extend SHARED_MODULES to materialize another shared module


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
    """Copy each canonical shared source into its independent provider distributions."""
    pairs = [(root / source, root / target) for source, targets in SEMANTIC_TARGETS for target in targets]
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
