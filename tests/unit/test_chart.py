"""Chart tests: render the Helm chart per environment and assert the properties we rely on.

Requires `helm` on PATH (or HELM=/path/to/helm); skipped otherwise.
"""
import os
import shutil
import subprocess

import pytest
import yaml

import render_chart_values
import vllm_args

HELM = os.environ.get("HELM") or shutil.which("helm")
pytestmark = pytest.mark.skipif(not HELM, reason="helm not installed")
ENVS = ["kind", "aks"]


def render(repo_root, env, *extra):
    cmd = [HELM, "template", "llm", str(repo_root / "charts/vllm"), "-n", "llm",
           "-f", str(repo_root / "charts/vllm/values-model.yaml"),
           "-f", str(repo_root / f"deploy/envs/{env}/values.yaml"), *extra]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def kind_of(docs, kind):
    return [d for d in docs if d["kind"] == kind]


def deployment(docs):
    (dep,) = kind_of(docs, "Deployment")
    return dep, dep["spec"]["template"]["spec"], dep["spec"]["template"]["spec"]["containers"][0]


def test_generated_values_in_sync(repo_root, model_cfg):
    committed = (repo_root / "charts/vllm/values-model.yaml").read_text()
    assert committed == render_chart_values.render(model_cfg), "run `make values`"


@pytest.mark.parametrize("env", ENVS)
def test_helm_lint(repo_root, env):
    subprocess.run([HELM, "lint", "--strict", str(repo_root / "charts/vllm"),
                    "-f", str(repo_root / "charts/vllm/values-model.yaml"),
                    "-f", str(repo_root / f"deploy/envs/{env}/values.yaml")],
                   check=True, capture_output=True)


@pytest.mark.parametrize("env", ENVS)
def test_secure_by_default(repo_root, env):
    docs = render(repo_root, env)
    _, pod, c = deployment(docs)
    psc, sc = pod["securityContext"], c["securityContext"]
    assert psc["runAsNonRoot"] is True and psc["runAsUser"] != 0
    assert psc["seccompProfile"]["type"] == "RuntimeDefault"
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"]["drop"] == ["ALL"]
    assert pod["automountServiceAccountToken"] is False
    (sa,) = kind_of(docs, "ServiceAccount")
    assert sa["automountServiceAccountToken"] is False


@pytest.mark.parametrize("env", ENVS)
def test_single_gpu_safe_rollout_and_probes(repo_root, env):
    dep, _, c = deployment(render(repo_root, env))
    assert dep["spec"]["strategy"]["type"] == "Recreate"
    for p in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert c[p]["httpGet"]["path"] == "/health"
    s = c["startupProbe"]
    assert s["periodSeconds"] * s["failureThreshold"] >= 300, "allow >= 5 min for model load"


@pytest.mark.parametrize("env", ENVS)
def test_network_policy(repo_root, env):
    (np,) = kind_of(render(repo_root, env), "NetworkPolicy")
    assert set(np["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    egress = np["spec"]["egress"]
    assert any(p.get("port") == 53 for rule in egress for p in rule.get("ports", []))
    blocks = [peer["ipBlock"] for rule in egress for peer in rule.get("to", []) if "ipBlock" in peer]
    assert all("169.254.169.254/32" in b.get("except", []) for b in blocks)


@pytest.mark.parametrize("env", ENVS)
def test_only_server_pods_match_selectors(repo_root, env):
    """Regression: the helm-test pod once matched the Service + NetworkPolicy selectors,
    so its own requests were blocked by the server's egress rules (and could be routed to itself)."""
    docs = render(repo_root, env)
    (svc,) = kind_of(docs, "Service")
    (np,) = kind_of(docs, "NetworkPolicy")
    selectors = [svc["spec"]["selector"], np["spec"]["podSelector"]["matchLabels"]]
    dep, _, _ = deployment(docs)
    pod_label_sets = {"server": dep["spec"]["template"]["metadata"]["labels"]}
    pod_label_sets |= {p["metadata"]["name"]: p["metadata"]["labels"] for p in kind_of(docs, "Pod")}

    def matches(sel, labels):
        return all(labels.get(k) == v for k, v in sel.items())

    for name, labels in pod_label_sets.items():
        for sel in selectors:
            assert matches(sel, labels) == (name == "server"), f"{name} vs selector {sel}"


def test_aks_runs_pinned_vllm_on_gpu(repo_root, model_cfg):
    docs = render(repo_root, "aks")
    dep, pod, c = deployment(docs)
    rt = model_cfg["runtime"]
    assert c["image"] == f"{rt['image']}:{rt['version']}@{rt['digest']}"
    assert c["args"][:-4] == vllm_args.server_args(model_cfg)
    assert c["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert pod["nodeSelector"] == {"workload": "gpu"}
    assert {"key": "sku", "operator": "Equal", "value": "gpu", "effect": "NoSchedule"} in pod["tolerations"]
    env = {e["name"]: e.get("value") for e in c["env"]}
    assert env["HF_HOME"].startswith("/models")
    vols = {v["name"]: v for v in pod["volumes"]}
    assert vols["shm"]["emptyDir"]["medium"] == "Memory"
    assert "persistentVolumeClaim" in vols["model-cache"]
    assert dep["metadata"]["annotations"]["llm-platform/model-revision"] == model_cfg["model"]["revision"]


def test_kind_runs_mock_without_gpu(repo_root, model_cfg):
    _, pod, c = deployment(render(repo_root, "kind"))
    assert "nvidia.com/gpu" not in c["resources"].get("limits", {})
    assert "tolerations" not in pod
    env = {e["name"]: e.get("value") for e in c["env"]}
    assert env["MOCK_SERVED_NAME"] == model_cfg["model"]["served_name"]
    assert env["MOCK_ROOT"] == model_cfg["model"]["id"]


def test_api_key_from_secret(repo_root):
    _, _, c = deployment(render(repo_root, "aks", "--set", "auth.existingSecret=vllm-auth"))
    (key,) = [e for e in c["env"] if e["name"] == "VLLM_API_KEY"]
    assert key["valueFrom"]["secretKeyRef"] == {"name": "vllm-auth", "key": "api-key"}


def test_vllm_requires_digest(repo_root):
    with pytest.raises(subprocess.CalledProcessError) as e:
        render(repo_root, "aks", "--set", "vllm.image.digest=")
    assert "pin images by digest" in e.value.stderr
