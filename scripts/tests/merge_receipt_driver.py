"""Child-process driver for merge receipt tests."""

DRIVER = """
import contextlib, os, sys, time
from pathlib import Path
from unittest import mock
sys.path.insert(0, os.environ["REPO_ROOT"])
from scripts import merge
from scripts.lib import action_receipt as ar
from scripts.lib import receipt_gate
from scripts.lib import git_common as git

fields = {"state": "OPEN", "headRefOid": os.environ["SHA"], "title": "t", "headRefName": "feature"}
patches = [
    mock.patch.object(git, "require_repo"), mock.patch.object(git, "main", return_value="main"),
    mock.patch.object(git, "protected", return_value=False), mock.patch.object(git, "sync_main_branch"),
    mock.patch.object(git, "pr_field", side_effect=lambda n, name, fb="": fields.get(name, fb)),
    mock.patch.object(git, "pr_num", return_value="7"),
    mock.patch.object(merge, "verify_gates", return_value=os.environ["SHA"]),
    mock.patch.object(merge.manifest_policy, "gate"),
    mock.patch.object(merge, "cleanup"),
]
if os.environ.get("DELAY_PERMITS"):
    real_permits = receipt_gate.permits
    def delayed_permits(*args, **kwargs):
        verdict = real_permits(*args, **kwargs)
        time.sleep(0.3)
        return verdict
    patches.append(mock.patch.object(receipt_gate, "permits", side_effect=delayed_permits))
if os.environ.get("NO_SEAM"):  # negative control: the seam call removed
    patches.append(mock.patch.object(merge, "require_merge_receipt", return_value=None))
if os.environ.get("BARRIER"):  # isolate the O_EXCL claim from the separate session-budget lock
    patches.append(mock.patch.object(receipt_gate.merge_budget, "lock", return_value=contextlib.nullcontext(True)))
def rendezvous(tag):  # both processes arrive before either goes on
    if not os.environ.get("BARRIER"):
        return
    Path(os.environ["BARRIER"], f"{tag}-{os.getpid()}").write_text("")
    deadline = time.time() + 15
    while len(list(Path(os.environ["BARRIER"]).glob(f"{tag}-*"))) < 2 and time.time() < deadline:
        time.sleep(0.01)
if os.environ.get("NAIVE_CLAIM"):  # negative control: exists()-then-write instead of O_EXCL
    def naive(path):
        marker = path.with_suffix(".consumed")
        seen = marker.exists()
        rendezvous("chk")
        if seen:
            return False
        marker.write_text("")
        return True
    patches += [mock.patch.object(ar, "consume", side_effect=naive),
                mock.patch.object(ar, "execute", side_effect=lambda p: True)]
elif os.environ.get("BARRIER"):  # both finish the is-it-consumed check before either claims
    real = ar.is_consumed
    def waiting(path):
        seen = real(path)
        rendezvous("in")
        return seen
    patches.append(mock.patch.object(ar, "is_consumed", side_effect=waiting))
for patch in patches:
    patch.start()
target = os.environ.get("MERGE_TARGET", "7")
sys.argv[0] = str(Path(os.environ["PLUGIN_ROOT"]) / "scripts/merge.py")
args = [target]
if not os.environ.get("NO_EXPECTED"):
    args.extend(["--expected-head", os.environ.get("EXPECTED_SHA", os.environ["SHA"])])
raise SystemExit(merge.main(args))
"""
