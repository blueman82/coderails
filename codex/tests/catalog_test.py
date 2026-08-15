#!/usr/bin/env python3
"""Self-check for one-to-one native Codex catalog routing."""

from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
from codex.catalog import CatalogError, all_routes, resolve  # noqa: E402


def main() -> int:
    routes = all_routes(root=ROOT)
    assert len(routes) == 46, len(routes)
    assert len({route.path for route in routes}) == len(routes)
    assert {route.kind for route in routes} == {"skills", "agents", "commands"}
    assert resolve("cite-check", kind="skills") == ROOT / "codex/skills/cite-check.md"
    assert resolve("disposition-scout", kind="agents") == ROOT / ".codex/skills/disposition-scout/SKILL.md"
    for bad in ("missing-route", "catalog"):
        try:
            resolve(bad, root=ROOT)
        except CatalogError:
            pass
        else:
            raise AssertionError(f"unexpectedly resolved {bad}")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "skills").mkdir()
        (root / "codex/skills").mkdir(parents=True)
        index = ROOT / "skills/index.yaml"
        text = index.read_text(encoding="utf-8")
        (root / "skills/index.yaml").write_text(text, encoding="utf-8")
        shutil.copy(ROOT / "codex/skills/cite-check.md", root / "codex/skills/cite-check.md")
        planned = text.replace("path: codex/skills/cite-check.md\n      status: active", "path: codex/skills/cite-check.md\n      status: planned")
        (root / "skills/index.yaml").write_text(planned, encoding="utf-8")
        try:
            resolve("cite-check", kind="skills", root=root)
        except CatalogError:
            pass
        else:
            raise AssertionError("planned route resolved")
        missing = text.replace("path: codex/skills/cite-check.md", "path: codex/skills/missing.md")
        (root / "skills/index.yaml").write_text(missing, encoding="utf-8")
        try:
            resolve("cite-check", kind="skills", root=root)
        except CatalogError:
            pass
        else:
            raise AssertionError("missing route resolved")
    print(f"PASS: {len(routes)} distinct native Codex routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
