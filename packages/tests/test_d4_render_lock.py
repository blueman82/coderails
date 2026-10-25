"""A render holds the orders lock while it writes the generated view pair."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from packages.tests.provider_fixture import Provider


class RenderLock(unittest.TestCase):
    """Check render serialization through both installed provider layouts."""

    def test_second_render_cannot_write_between_views(self) -> None:
        """Both providers refuse a second render while the first writes its first view."""
        code = """
import argparse
import json
import sys
from pathlib import Path
from unittest import mock
plugin, repo, session = sys.argv[1:]
sys.path.insert(0, plugin)
from scripts.lib import memory_adapter as ma
from scripts.lib import orders
repo = Path(repo)
args = argparse.Namespace(session=session)
write = ma.write_view
blocked = []
def first_view(path, content, owner):
    if not blocked:
        try:
            orders.cmd_render(args, repo)
        except ValueError as error:
            blocked.append(str(error) == 'lock')
        else:
            blocked.append(False)
    return write(path, content, owner)
with mock.patch.object(ma, 'write_view', side_effect=first_view):
    payload, status = orders.cmd_render(args, repo)
print(json.dumps({'blocked': blocked, 'status': status, 'views': payload.get('view_sha256')}))
"""
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("claude", "codex"):
                with self.subTest(provider=name):
                    provider = Provider(Path(temporary), name)
                    done = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            code,
                            str(provider.plugin),
                            str(provider.path.parent.parent),
                            provider.session,
                        ],
                        cwd=provider.home,
                        env=provider.environment,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(done.returncode, 0, done.stderr)
                    result = json.loads(done.stdout)
                    self.assertEqual((result["blocked"], result["status"]), ([True], 0))
                    self.assertEqual(len(result["views"]), 2)
