#!/usr/bin/env python3
"""Write deploy/envs/aks/harness-image.yaml (CI-owned) with a freshly published image digest.

Usage: bump_harness_image.py --repository ghcr.io/owner/llm-platform-harness --tag sha-abc123 \
           --digest sha256:...
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "deploy" / "envs" / "aks" / "harness-image.yaml"
TEMPLATE = """\
# CI-OWNED — written by .github/workflows/ci.yml (scripts/bump_harness_image.py) on main.
# Harness image used by `helm test` on AKS. Humans don't edit this file; Git history is the audit log.
mock:
  image:
    repository: {repository}
    tag: {tag}
    digest: "{digest}"
"""


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--repository", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--digest", required=True)
    a = p.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", a.digest):
        sys.exit(f"not a sha256 digest: {a.digest!r}")
    content = TEMPLATE.format(repository=a.repository.lower(), tag=a.tag, digest=a.digest)
    changed = not OUT.exists() or OUT.read_text() != content
    OUT.write_text(content)
    print(f"{'updated' if changed else 'unchanged'}: {OUT.name} -> {a.digest}")


if __name__ == "__main__":
    main()
