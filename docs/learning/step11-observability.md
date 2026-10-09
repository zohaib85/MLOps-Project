# Steps 11–13 — Observability: metrics, dashboard, SLOs, alerts

**Goal:** answer three questions from one screen — *is the service meeting its promise?* (SLOs),
*what is the engine doing?* (vLLM internals), *is the hardware the bottleneck?* (GPU/pod) — and get
told automatically, with a runbook link, when the promise is at risk.

## Mental model
```
vLLM pod :8000/metrics ─┐                         ┌─► recording rules (llm:*) ─► alert rules ─► Alertmanager
dcgm-exporter :9400 ────┼─ scraped every 15s by ─► Prometheus                                      (UI only, lab)
kube-state-metrics ─────┘   (targets come from        └─► Grafana dashboard (ConfigMap, via sidecar)
                             ServiceMonitors)
```
- **Prometheus pulls** (scrapes) metrics over HTTP; apps don't push.
- **Prometheus Operator** turns Kubernetes objects into Prometheus config:
  `ServiceMonitor` = "scrape the pods behind this Service", `PrometheusRule` = "load these rules".
  These are CRDs installed by **kube-prometheus-stack** — one Helm chart bundling the operator,
  Prometheus, Alertmanager, Grafana, kube-state-metrics and node-exporter.
- **Metric types:** counter (only goes up — always wrap in `rate()`), gauge (up and down — read as is),
  histogram (`_bucket{le=…}` counters — percentiles via `histogram_quantile`).

## What's where
| File | Role |
|---|---|
| `observability/kube-prometheus-stack-values.yaml` | Stack config: discover monitors in all namespaces, small retention/resources, AKS-unscrapable components off |
| `observability/dcgm-exporter-values.yaml` | GPU exporter: GPU node only (same nodeSelector/toleration as vLLM) |
| `charts/vllm/templates/servicemonitor.yaml` | Scrape our Service's `http` port at `/metrics`; adds a `model_revision` label |
| `charts/vllm/templates/prometheusrule.yaml` | 6 recording rules + 7 alerts; thresholds come from `values.yaml → metrics` |
| `charts/vllm/templates/dashboard-configmap.yaml` + `charts/vllm/dashboards/llm-inference.json` | The dashboard, shipped by Argo CD with the app |
| `charts/vllm/templates/networkpolicy.yaml` | New ingress rule: namespace `monitoring` may reach port `http` |
| `observability/vllm-metrics-v0.29.0.txt`, `platform-metrics.txt` | Inventory of metric names that exist — tests reject anything else |
| `observability/tests/alerts-test.yaml` | promtool unit tests: synthetic series → expected alerts |
| `docs/slo.md`, `docs/runbook.md` | The promise, and what to do when it's broken |
| `app/mock_openai.py` | Mock now speaks vLLM metric names; `MOCK_LATENCY_S` / `MOCK_ERROR_RATE` for drills |
| `scripts/loadgen.py` (`make load`) | Closed-loop traffic so panels and alerts have data |

## Decisions worth explaining in an interview
| Decision | Why |
|---|---|
| Monitoring objects render only if the cluster has `monitoring.coreos.com/v1` (`.Capabilities.APIVersions.Has`) | Argo CD passes the cluster's API list to Helm. App syncs fine before the stack exists; once it's installed, the next sync adds the ServiceMonitor/rules. CI renders with `--api-versions` so they're still validated |
| `serviceMonitorSelectorNilUsesHelmValues: false` | By default Prometheus only picks up monitors labelled with *its own* Helm release. Our app is a different release in another namespace |
| Dashboard as a ConfigMap in the app chart | Grafana's sidecar loads labelled ConfigMaps from all namespaces → dashboard is versioned, reviewed and deployed by GitOps like everything else. No click-ops |
| Alerts on **symptoms** (errors, latency, down) + a few **causes** (queue, KV cache, pending, restarts) | Symptoms page; causes point the runbook at the fix |
| Multi-window burn-rate alert (14.4× over 1h **and** 5m) | Fires fast on real budget burn, ignores blips, resolves quickly once fixed (Google SRE workbook) |
| `or vector(0)` in `LLMEndpointDown` | If the pod is gone, `up` has *no series* — and "no data" never fires an alert. `or vector(0)` turns absence into 0 |
| Recording rules (`llm:*`) | Expensive expressions computed once; alerts and ad-hoc queries reuse them consistently |
| Metric inventory + tests | A dashboard panel with a typo'd metric shows "No data" silently. The test fails instead |
| `sub` → `subf` bug found by promtool | Sprig's `sub` is integer maths: `1 - 0.99 = 1` made the threshold 14.4 (never fires). `test_burn_rate_threshold_follows_slo` guards it |

## Run it — kind (no GPU, mock engine)
```bash
make kind-up && make kind-deploy           # or Argo CD: make argocd-install argocd-apps kind-load
make monitoring-install                    # ~3-5 min
make kind-deploy                           # re-render: CRDs now exist → ServiceMonitor/rules/dashboard appear
kubectl -n llm get servicemonitor,prometheusrule,configmap

make prom-ui        # http://localhost:9090 → Status ▸ Targets: llm-vllm UP; Alerts: 7 rules, inactive
make grafana-ui     # http://localhost:3000, admin / $(make grafana-password) → "LLM inference — …"
make load           # in another terminal: traffic → panels move (GPU row stays empty on kind)
```
(Using Argo CD instead of `kind-deploy`? Hit *Refresh* in the UI after `monitoring-install`.)

### Drill: make an alert fire (kind)
The mock takes fault-injection settings from `mock.faults` in the chart values.
GitOps way (a real change, reviewed and reverted like any other):
```yaml
# deploy/envs/kind/values.yaml
mock:
  faults: { MOCK_ERROR_RATE: "0.3" }   # 30% of chat requests return 500
```
Quick way (helm-installed release): `helm upgrade llm charts/vllm -n llm --reuse-values --set-string mock.faults.MOCK_ERROR_RATE=0.3`.

Then `make load LOAD_ARGS="--concurrency 4 --duration 600"` and watch Prometheus ▸ Alerts:
`LLMErrorBudgetFastBurn` goes *pending* → *firing* after ~2 min. Follow its runbook link, "fix" it
by removing the fault, and watch it resolve. Same with `MOCK_LATENCY_S: "6"` → `LLMLatencyP95High` (10 min).

## Run it — AKS (session B)
```bash
make infra-up && make gpu-on
make monitoring-install && make dcgm-install
# Argo CD syncs llm-aks; vLLM loads the model on the T4
make prom-ui        # targets: llm-vllm and dcgm-exporter UP
make grafana-ui     # all three rows populated
make load LOAD_ARGS="--concurrency 8 --duration 300"
```
Capture screenshots for `docs/evidence/` — then `make gpu-off` / `make infra-down`.

## Things to try (learning)
1. Prometheus UI: `rate(http_requests_total[1m])` vs `http_requests_total` — why is the raw counter useless on a graph?
2. `histogram_quantile(0.95, sum by (le) (rate(vllm:e2e_request_latency_seconds_bucket[5m])))` — remove `sum by (le)` and see what breaks.
3. `make rules-test`, then change `values: '0+6x120'` to `'0+1x120'` in the first test and read the failure.
4. Delete the NetworkPolicy's monitoring rule (render locally) — what would Targets show? (Hint: *context deadline exceeded*.)
5. `kubectl -n llm delete pod -l app.kubernetes.io/name=vllm` — which alert would fire if the pod never came back, and after how long?

## Self-check
- Counter vs gauge vs histogram — one vLLM example of each?
- Why does a burn-rate alert use two windows?
- Why can't an alert on `up == 0` catch a pod that has been deleted?
- What does the ServiceMonitor select — pods or Services? And which port name must match?
- Where would you add a Slack receiver, and why isn't one configured here?
