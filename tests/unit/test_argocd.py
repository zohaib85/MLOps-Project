"""Argo CD manifests stay consistent with the repo layout and the AppProject guardrails."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_URL = "https://github.com/zohaib85/MLOps-Project.git"


def load(repo_root, name):
    return yaml.safe_load((repo_root / "deploy/argocd" / name).read_text())


@pytest.mark.parametrize("app_file,env", [("app-kind.yaml", "kind"), ("app-aks.yaml", "aks")])
def test_application_points_at_real_files(repo_root, app_file, env):
    app = load(repo_root, app_file)
    src = app["spec"]["source"]
    assert src["repoURL"] == REPO_URL
    assert src["targetRevision"] == "main"
    chart_dir = repo_root / src["path"]
    assert (chart_dir / "Chart.yaml").exists()
    files = src["helm"]["valueFiles"]
    assert files[0] == "values-model.yaml"
    assert any(f.endswith(f"deploy/envs/{env}/values.yaml") for f in files)
    for f in files:
        resolved = (chart_dir / f).resolve()
        assert resolved.exists(), f"{f} does not exist"
        assert Path(repo_root).resolve() in resolved.parents, f"{f} escapes the repo"


@pytest.mark.parametrize("app_file", ["app-kind.yaml", "app-aks.yaml"])
def test_application_within_project_guardrails(repo_root, app_file):
    app, proj = load(repo_root, app_file), load(repo_root, "project.yaml")
    assert app["spec"]["project"] == proj["metadata"]["name"]
    assert app["spec"]["source"]["repoURL"] in proj["spec"]["sourceRepos"]
    dest = app["spec"]["destination"]
    assert {"server": dest["server"], "namespace": dest["namespace"]} in proj["spec"]["destinations"]
    policy = app["spec"]["syncPolicy"]["automated"]
    assert policy["prune"] and policy["selfHeal"]


def test_project_allows_every_kind_the_chart_renders(repo_root):
    """If the chart starts rendering a new kind, the AppProject must allow it or Argo CD will refuse."""
    helm = os.environ.get("HELM") or shutil.which("helm")
    if not helm:
        pytest.skip("helm not installed")
    out = subprocess.run(
        [
            helm,
            "template",
            "llm",
            str(repo_root / "charts/vllm"),
            "-f",
            str(repo_root / "charts/vllm/values-model.yaml"),
            "-f",
            str(repo_root / "deploy/envs/aks/values.yaml"),
            "--set",
            "test.enabled=false",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    rendered = {
        (d["apiVersion"].split("/")[0] if "/" in d["apiVersion"] else "", d["kind"])
        for d in yaml.safe_load_all(out)
        if d
    }
    allowed = {
        (r["group"], r["kind"]) for r in load(repo_root, "project.yaml")["spec"]["namespaceResourceWhitelist"]
    }
    assert rendered <= allowed, f"not allowed by AppProject: {rendered - allowed}"
