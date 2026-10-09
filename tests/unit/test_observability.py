"""Monitoring stays consistent: rules and dashboard only use metrics that exist, alerts have runbooks,
and the chart wires scraping (ServiceMonitor + NetworkPolicy) the way Prometheus expects.

Metric inventories: observability/vllm-metrics-v0.29.0.txt (from vLLM source at the pinned tag) and
observability/platform-metrics.txt (kube-state-metrics, cAdvisor, dcgm-exporter).
"""

import json
import re

import pytest
from test_chart import HELM, kind_of, render

API = ("--api-versions", "monitoring.coreos.com/v1")
# PromQL keywords/functions that look like metric names to the simple tokenizer below.
PROMQL_WORDS = {
    "sum", "max", "min", "avg", "count", "rate", "increase", "histogram_quantile", "clamp_min", "vector",
    "by", "without", "and", "or", "unless", "on", "ignoring", "le", "label_values", "bool",
}  # fmt: skip


def known_metrics(repo_root):
    names = set()
    for f in ("vllm-metrics-v0.29.0.txt", "platform-metrics.txt"):
        for line in (repo_root / "observability" / f).read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                names.add(line.strip())
    return names


def metric_names(expr):
    """Identifiers in a PromQL expression that are not labels, keywords, functions or durations."""
    expr = re.sub(r"\{[^}]*\}", "", expr)  # drop label matchers
    expr = re.sub(r'"[^"]*"', "", expr)  # drop strings
    expr = re.sub(r"\[[^\]]*\]", "", expr)  # drop range selectors
    expr = re.sub(r"\b(by|without|on|ignoring)\s*\([^)]*\)", "", expr)  # drop grouping label lists
    expr = re.sub(r"(?<![A-Za-z0-9_:])\d+(\.\d+)?(e[+-]?\d+)?", "", expr)  # drop numbers (1e-9, 0.95)
    tokens = re.findall(r"[A-Za-z_:][A-Za-z0-9_:]*", expr)
    return {t for t in tokens if t not in PROMQL_WORDS and not t.startswith("llm:")}


def rule_docs(repo_root, env="aks"):
    return render(repo_root, env, *API)


@pytest.fixture(scope="module")
def rules(repo_root):
    if not HELM:
        pytest.skip("helm not installed")
    (pr,) = kind_of(rule_docs(repo_root), "PrometheusRule")
    return [r for g in pr["spec"]["groups"] for r in g["rules"]]


@pytest.fixture(scope="module")
def dashboard(repo_root):
    return json.loads((repo_root / "charts/vllm/dashboards/llm-inference.json").read_text())


def dashboard_exprs(dash):
    exprs = [t["expr"] for p in dash["panels"] for t in p.get("targets", [])]
    # Variable queries are Grafana's label_values(<selector>, <label>): check the selector only.
    for v in dash["templating"]["list"]:
        if v["type"] == "query":
            exprs.append(re.fullmatch(r"label_values\((.*), *\w+\)", v["query"]["query"]).group(1))
    return exprs


def test_tokenizer_sanity():
    assert metric_names('sum by (le) (rate(vllm:x_bucket{a="b"}[5m]))') == {"vllm:x_bucket"}
    assert metric_names("llm:errors:ratio_rate1h > 0.144 and up == 0") == {"up"}
    assert metric_names("clamp_min(sum(rate(x_total[1h])), 1e-9)") == {"x_total"}


def test_rules_reference_only_known_metrics(repo_root, rules):
    known = known_metrics(repo_root)
    recorded = {r["record"] for r in rules if "record" in r}
    for r in rules:
        unknown = metric_names(r["expr"]) - known
        assert not unknown, f"{r.get('record') or r.get('alert')}: unknown metrics {unknown}"
        used_recordings = set(re.findall(r"(?<![a-z])llm:[a-z0-9_:]+", r["expr"]))
        assert used_recordings <= recorded, f"undefined recording rule(s) {used_recordings - recorded}"


def test_dashboard_references_only_known_metrics(repo_root, dashboard):
    known = known_metrics(repo_root)
    for expr in dashboard_exprs(dashboard):
        assert not metric_names(expr) - known, f"unknown metrics in: {expr}"


def test_every_alert_has_severity_and_runbook_anchor(repo_root, rules):
    runbook = (repo_root / "docs/runbook.md").read_text().lower()
    alerts = [r for r in rules if "alert" in r]
    assert len(alerts) >= 5
    for a in alerts:
        assert a["labels"]["severity"] in {"critical", "warning"}
        url = a["annotations"]["runbook_url"]
        anchor = url.split("#", 1)[1]
        assert anchor == a["alert"].lower()
        assert f"## {a['alert'].lower()}" in runbook, f"docs/runbook.md has no '## {a['alert']}' section"


def test_burn_rate_threshold_follows_slo(rules):
    """14.4x burn of a 1% budget = 0.144. Guards against integer maths in the template (sub vs subf)."""
    (fast,) = [r for r in rules if r.get("alert") == "LLMErrorBudgetFastBurn"]
    assert "> 0.144" in fast["expr"]


def test_dashboard_layout(dashboard):
    rows = [p["title"].split(" ")[0] for p in dashboard["panels"] if p["type"] == "row"]
    assert rows == ["Service", "Inference", "Resources"]
    ids = [p["id"] for p in dashboard["panels"]]
    assert len(ids) == len(set(ids))
    for p in dashboard["panels"]:
        if p["type"] == "timeseries":
            n = len(p["targets"]) > 1 or len(p["fieldConfig"]["overrides"]) > 1
            assert p["options"]["legend"]["showLegend"] == n, f"{p['title']}: legend iff >1 series"


@pytest.mark.skipif(not HELM, reason="helm not installed")
@pytest.mark.parametrize("env", ["kind", "aks"])
def test_monitoring_objects_render_when_crds_exist(repo_root, env):
    docs = render(repo_root, env, *API)
    (sm,) = kind_of(docs, "ServiceMonitor")
    (svc,) = kind_of(docs, "Service")
    assert sm["spec"]["selector"]["matchLabels"].items() <= svc["metadata"]["labels"].items()
    assert sm["spec"]["endpoints"][0]["port"] == svc["spec"]["ports"][0]["name"]
    assert kind_of(docs, "PrometheusRule")
    (cm,) = kind_of(docs, "ConfigMap")
    assert cm["metadata"]["labels"]["grafana_dashboard"] == "1"
    json.loads(cm["data"]["llm-inference.json"])


@pytest.mark.skipif(not HELM, reason="helm not installed")
def test_monitoring_crds_absent_means_no_crd_objects(repo_root):
    """Argo CD can sync the app before kube-prometheus-stack exists (no CRDs → objects skipped)."""
    kinds = {d["kind"] for d in render(repo_root, "aks")}
    assert not kinds & {"ServiceMonitor", "PrometheusRule"}


@pytest.mark.skipif(not HELM, reason="helm not installed")
def test_networkpolicy_admits_prometheus(repo_root):
    (np,) = kind_of(render(repo_root, "aks", *API), "NetworkPolicy")
    sources = [
        f["namespaceSelector"]["matchLabels"]
        for rule in np["spec"]["ingress"]
        for f in rule.get("from", [])
        if "namespaceSelector" in f
    ]
    assert {"kubernetes.io/metadata.name": "monitoring"} in sources
