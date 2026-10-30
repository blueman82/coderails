"""Safe local installer file operations and canonical semantic materialization."""

import os
import tempfile
from pathlib import Path

PROVIDER_SCRIPT_DIRS = ("skills/agentic-loop/scripts", "packages/codex/skills/agentic-loop/scripts")
SHARED_MODULES = (  # packages/graph-semantics/<file>: shared modules plus the spec and policy data they read
    "graph_driver_mode.py",
    "graph_driver_evidence.py",
    "graph_driver_prepublication.py",
    "graph_driver_publication.py",
    "graph_driver_control.py",
    "graph_driver_dispatch.py",
    "graph_driver_process.py",
    "graph_driver_controller.py",
    "graph_driver_transfer.py",
    "graph_semantics.py",
    "node_metadata.py",
    "graph_vocab.py",
    "graph_convert.py",
    "graph_spec.py",
    "graph_contract.py",
    "graph_repair.py",
    "graph-spec.yaml",
    "policy.yaml",
)
SEMANTIC_TARGETS = tuple(
    (f"packages/graph-semantics/{name}", tuple(f"{directory}/{name}" for directory in PROVIDER_SCRIPT_DIRS))
    for name in SHARED_MODULES
)  # (canonical source, provider copies); extend SHARED_MODULES to materialize another shared file


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
