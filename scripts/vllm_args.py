#!/usr/bin/env python3
"""Render vLLM server arguments (or the pinned image ref) from config/model.yaml.

Keeps config/model.yaml the single source of truth: `make serve` today, Helm values later.

Usage:
    python3 scripts/vllm_args.py             # vLLM CLI args, one per line
    python3 scripts/vllm_args.py --image     # image@digest
    python3 scripts/vllm_args.py --served-name
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "model.yaml"


def load(path: Path) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    rev = str(cfg["model"]["revision"])
    if len(rev) != 40 or any(c not in "0123456789abcdef" for c in rev):
        sys.exit(f"model.revision must be a 40-char commit SHA, got: {rev!r}")
    return cfg


def image_ref(cfg: dict) -> str:
    rt = cfg["runtime"]
    return f"{rt['image']}:{rt['version']}@{rt['digest']}"


def server_args(cfg: dict, gpu_memory_utilization: float | str | None = None) -> list[str]:
    """vLLM CLI args from the model card. Shared by `make serve` and the Helm values generator."""
    m, s = cfg["model"], cfg["serving"]
    gpu_util = gpu_memory_utilization or s["gpu_memory_utilization"]
    return [
        m["id"],  # positional: `vllm serve <model>` (--model is deprecated)
        "--revision",
        m["revision"],
        "--tokenizer-revision",
        m["revision"],
        "--served-model-name",
        m["served_name"],
        "--dtype",
        s["dtype"],
        "--max-model-len",
        str(s["max_model_len"]),
        "--gpu-memory-utilization",
        str(gpu_util),
        "--max-num-seqs",
        str(s["max_num_seqs"]),
        "--seed",
        str(s["seed"]),
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--image", action="store_true")
    g.add_argument("--served-name", action="store_true")
    a = p.parse_args()
    cfg = load(a.config)
    if a.image:
        print(image_ref(cfg))
    elif a.served_name:
        print(cfg["model"]["served_name"])
    else:
        # Laptop GPUs share memory with the desktop; `make serve` passes a local override.
        print("\n".join(server_args(cfg, os.environ.get("GPU_MEMORY_UTILIZATION"))))


if __name__ == "__main__":
    main()
