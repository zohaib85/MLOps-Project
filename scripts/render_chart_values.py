#!/usr/bin/env python3
"""Generate charts/vllm/values-model.yaml from config/model.yaml.

config/model.yaml stays the single source of truth; this file is the Helm-facing copy.
CI fails if the committed copy drifts (tests/unit/test_chart.py). Regenerate with `make values`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vllm_args  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "charts" / "vllm" / "values-model.yaml"
HEADER = (
    "# GENERATED from config/model.yaml by scripts/render_chart_values.py — do not edit.\n"
    "# Regenerate with: make values\n"
)


def build(cfg: dict) -> dict:
    m, rt = cfg["model"], cfg["runtime"]
    return {
        "model": {
            "id": m["id"],
            "revision": m["revision"],
            "servedName": m["served_name"],
        },
        "vllm": {
            "image": {
                "repository": rt["image"],
                "tag": rt["version"],
                "digest": rt["digest"],
            },
            # Same function as `make serve`, without the laptop-only memory override.
            "args": vllm_args.server_args(cfg),
        },
    }


def render(cfg: dict) -> str:
    return HEADER + yaml.safe_dump(build(cfg), sort_keys=False)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    a = p.parse_args()
    content = render(vllm_args.load(vllm_args.DEFAULT_CONFIG))
    if a.check:
        if not OUT.exists() or OUT.read_text() != content:
            sys.exit(f"{OUT.relative_to(REPO_ROOT)} is stale — run `make values`")
        print("values-model.yaml is up to date")
        return
    OUT.write_text(content)
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
