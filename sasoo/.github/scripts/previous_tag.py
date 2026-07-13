"""Print the highest semver tag strictly below $TAG (empty output if none).

Extracted from the release workflow's "Generate release notes" step: a
column-0 heredoc body inside a YAML block scalar terminates the scalar
early, so the logic lives here instead of inline.
"""
import os
import re
import subprocess

target = os.environ["TAG"]
match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", target)
if not match:
    raise SystemExit(0)

current = tuple(int(part) for part in match.groups())
tags = subprocess.check_output(["git", "tag"], text=True).splitlines()
older = []

for tag in tags:
    parsed = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
    if not parsed:
        continue
    version = tuple(int(part) for part in parsed.groups())
    if version < current:
        older.append((version, tag))

if older:
    print(max(older)[1])
