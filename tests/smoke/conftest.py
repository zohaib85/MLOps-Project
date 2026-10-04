"""Smoke-test fixtures: talk to a running OpenAI-compatible endpoint and record run metadata."""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.smoke)


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="session")
def client(base_url):
    headers = {}
    if key := os.environ.get("VLLM_API_KEY"):
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(base_url=base_url, headers=headers, timeout=60) as c:
        try:
            c.get("/health")
        except httpx.ConnectError:
            pytest.exit(f"No endpoint at {base_url} — start it with `make serve`", returncode=2)
        yield c


PROMPT_SET = os.environ.get("PROMPT_SET", "smoke-v2")


@pytest.fixture(scope="session")
def prompt_set(repo_root) -> dict:
    return yaml.safe_load((repo_root / "app" / "prompts" / f"{PROMPT_SET}.yaml").read_text())


@pytest.fixture(scope="session")
def run_record(repo_root, model_cfg, base_url, prompt_set):
    """Collects results during the session; written to results/raw/ at the end.

    Ties every smoke run to model id + revision + image + prompt-set version.
    """
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "model_id": model_cfg["model"]["id"],
        "model_revision": model_cfg["model"]["revision"],
        "served_name": model_cfg["model"]["served_name"],
        "image": f"{model_cfg['runtime']['image']}:{model_cfg['runtime']['version']}"
        f"@{model_cfg['runtime']['digest']}",
        "prompt_set": prompt_set["version"],
        "results": [],
    }
    yield record
    out_dir = Path(os.environ.get("RESULTS_DIR", repo_root / "results" / "raw"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"smoke-{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(record, indent=2))
    print(f"\nSmoke run record: {path}")
