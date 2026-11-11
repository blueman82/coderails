# hooks/patches/

These files give the patch text for `hooks/scripts/remember_inject_cap_guard.py`.
The `SessionStart` hook can apply the memory byte limit again after an update removes it from the remember plugin.

**By default, the guard gives a warning only.**
It reports a missing limit one time for each plugin version and changes no plugin files.
The remember plugin has a different maintainer.
To let the guard apply the patch, set `REMEMBER_INJECT_CAP_AUTOWRITE=1` in the `env` block of `settings.json`.
The instructions below apply when that setting is `1`.

| File | Role |
|---|---|
| `remember_inject_cap.vendor.txt` | Block to find. Copy the vendor's `for MFILE` loop before the patch. |
| `remember_inject_cap.patched.txt` | Replacement block. The same loop applies the `REMEMBER_INJECT_MAX_BYTES` limit. |

### Scope: the loop only, not the enclosing `if`

Each block starts and end with the `for MFILE ...; do ... done` loop.
Keep `if [ -n "$HAS_MEMORY" ]; then` and its `fi` out of the two blocks.

The first patch included the full `if` block. A change anywhere in that block could prevent a match.
Version 0.8.9 added a section for rotated archives between `done` and `fi`. The guard found no match and refused the patch.
Versions 0.8.3 and 0.8.9 use the same loop. One patch matches the two versions and preserves the vendor's changes around the loop.

Use the same boundaries in the two patch files.
If you remove lines from `vendor.txt` alone, the result can have a duplicate `if` and a `fi` without a matching `if`.
The guard checks for the `head -c` command. Use `bash -n` to check Bash syntax.

The vendor uses the same `for MFILE in ...` line earlier to calculate `HAS_MEMORY`.
The first loop uses `[ -f "$MFILE" ]` alone. The patch target also uses `&& [ -s "$MFILE" ]`.
The sequence of eight lines matches one time. Do not remove lines.
After a change, use the guard's match procedure to make sure the count is one.

## DO NOT EDIT, REFORMAT, OR COMMENT THESE FILES

The two `.txt` files contain the text for the patch.
The guard reads `vendor.txt` and looks for the same sequence of lines in `session-start-hook.sh`.
An added line, a different indent, a comment that spans different lines, or a removed space at the end can prevent a match.
If the guard finds no match, the guard refuses the patch and asks you to apply it by hand.
If an update changes the block, the guard gives a warning. A patch that uses line numbers or context can change incorrect text without a warning.

Put explanations in this README. Do not add headers, comments about the source, or generator notices to the patch files.

If the cache has the current patched copy, check that the patch result has the same bytes.

## Provenance

The first hand patch changed the file in the cache for a fixed plugin version. The author kept no copy of the file before the patch.
To make `vendor.txt`, the author removed the hand patch from a copy of the cache file.
To make `patched.txt`, the author copied the block from that file after the hand patch.

To do a check of the two blocks, replace `patched.txt` with `vendor.txt` in a copy of the file. Run the guard on the copy.
The result must have the same bytes as the patched file in the cache.
`hooks/scripts/tests/remember_inject_cap_guard_test.py` checks that it is possible to remove and apply the patch with a test file.

## Editing the patch text legitimately

If the vendor changes the loop, make the two files from the new source.
Copy all bytes of the new unpatched loop to `vendor.txt`.
Apply the cap to a copy of the loop for `patched.txt`. Run the tests.

Before you commit, do these checks with the installed plugin file.

1. Use the match procedure in `apply_cap` from `remember_inject_cap_guard.py` to count the new vendor block in `session-start-hook.sh`.
   The count must be `1`.
2. Run the guard with `REMEMBER_INJECT_CAP_AUTOWRITE=1` on a copy of the installed file. Run `bash -n` on that copy to check the syntax.
3. Run the patched loop on one memory file above the limit and one below it.
   Make sure the marker shows only for the file above the limit.

The guard uses `head -c "$REMEMBER_INJECT_MAX_BYTES"` to find the cap.
A change to only the NOTE comment in `patched.txt` has no effect on a copy with the cap.
If a plugin update removes the cap, the guard can apply the full block again.
