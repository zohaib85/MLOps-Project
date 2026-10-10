# Skill gaps — self-study plan: Helm, Rego (policy as code), GitHub Actions

Purpose: come back to this after the build. Each section uses **this repo's real files** as the
learning material, so you learn the tool from code you already own.
Suggested order: **Helm → Prometheus → GitHub Actions → Rego**. ~3–4 h each.
**Hands-on labs (you do the work, Claude reviews): [hands-on-plan.md](hands-on-plan.md).** This file is the concept reference.

---

## 1. Helm

### Mental model
Helm = **templating + packaging + release tracking** for Kubernetes YAML.
```
chart (templates + defaults)  +  values files (per environment)  ──render──►  plain K8s YAML  ──apply──►  cluster
                                                                                         └─ Helm records a "release" (revision 1, 2, 3…)
```
Kubernetes never sees Helm templates — only the rendered YAML.

### Core concepts → where they are in this repo
| Concept | What it is | Look at |
|---|---|---|
| Chart | A folder: `Chart.yaml` (name, version), `values.yaml` (defaults), `templates/` | `charts/vllm/` |
| Values | Inputs; later `-f` files override earlier ones | `values.yaml` → `values-model.yaml` → `deploy/envs/aks/values.yaml` |
| Template | Go-template YAML: `{{ .Values.x }}`, `{{ if }}`, `{{ range }}`, `{{ include }}`, `| nindent 4` | `templates/deployment.yaml` |
| Helpers (`_helpers.tpl`) | Reusable named snippets (`define` / `include`) — names, labels, image ref | `templates/_helpers.tpl` |
| `fail` | Stop rendering with an error (we enforce digest pinning) | `vllm.image` in `_helpers.tpl` |
| Release | An installed instance of a chart; has revisions you can roll back | `helm history llm -n llm` |
| Hooks / tests | Resources run at lifecycle points; `helm test` runs `helm.sh/hook: test` pods | `templates/tests/test-health.yaml` |
| NOTES.txt | Message printed after install | `templates/NOTES.txt` |

### Commands to master
```bash
helm template llm charts/vllm -f charts/vllm/values-model.yaml -f deploy/envs/kind/values.yaml   # render only
helm lint --strict charts/vllm -f ...                         # static checks
helm upgrade --install llm charts/vllm -n llm --create-namespace -f ... --wait
helm list -A ; helm history llm -n llm
helm get values llm -n llm ; helm get manifest llm -n llm      # what's actually deployed
helm rollback llm 1 -n llm                                     # back to revision 1
helm test llm -n llm --logs
helm uninstall llm -n llm
```

### Exercises (do them on kind)
1. Render the chart and find where `.Values.probes.startup.failureThreshold` ends up. Change it with `--set` and diff.
2. Add a value `podAnnotations: {team: ml}` via a new values file — confirm it appears on the pod.
3. Break the image digest (`--set vllm.image.digest=`) and read the `fail` message. Find the line that produces it.
4. Upgrade with a change, then `helm history` + `helm rollback`. Watch the pod get recreated.
5. Explain why `strategy: Recreate` is in `deployment.yaml` (hint: one GPU).
6. Read `{{- ... }}` vs `{{ ... }}` — what does the dash do? Why `nindent` not `indent`?

### Self-check
- Values precedence when passing three `-f` files and a `--set`?
- Difference between `helm template` and `helm install --dry-run`?
- What does Helm store in the cluster for each release (hint: a Secret per revision)?
- Why did our helm-test pod break when it reused the chart's labels? (Service/NetworkPolicy selectors)

### Resources
- Helm docs — Chart Template Guide: https://helm.sh/docs/chart_template_guide/
- Helm docs — Best practices: https://helm.sh/docs/chart_best_practices/
- Go template + Sprig functions reference: https://helm.sh/docs/chart_template_guide/function_list/

---

## 2. GitHub Actions

### Mental model
```
Git event (push / pull_request / manual)
  └─► GitHub finds workflows in .github/workflows/*.yml whose `on:` matches
        └─► each JOB gets a fresh VM ("runner") ─► STEPS run in order ─► ✅/❌ on the commit/PR
```
Jobs run **in parallel** unless linked with `needs:`. Nothing is shared between jobs except via
`outputs`, artifacts or caches.

### Mapping to what you know
| GitHub Actions | Azure Pipelines | Jenkins |
|---|---|---|
| workflow file | pipeline YAML | Jenkinsfile |
| `on:` | `trigger:` / `pr:` | build triggers |
| job / `runs-on` | job / agent pool | stage / agent |
| step: `run:` | script step | `sh` |
| step: `uses:` (action) | task (`HelmInstaller@1`) | plugin |
| `needs:` | `dependsOn:` | stage order |
| `if:` | `condition:` | `when {}` |
| `secrets.GITHUB_TOKEN` + `permissions:` | `System.AccessToken` + scopes | credentials |
| `${{ github.sha }}` | `$(Build.SourceVersion)` | `${GIT_COMMIT}` |

### How `uses:` works (the "magic install")
`uses: azure/setup-helm@<sha>` = download that GitHub repo at that commit, read its `action.yml`
(`inputs`, `outputs`, `runs.using: node24 | docker | composite`), run its code with your `with:` inputs.
`setup-helm` downloads `helm-vX.tar.gz` from get.helm.sh, extracts it, and adds it to `PATH` for later steps.
→ That's why actions are pinned to **commit SHAs**: you're running someone else's code.

### Walk through our workflow (`.github/workflows/ci.yml`)
| Job | Teaches |
|---|---|
| `test` | checkout → setup tools → `run: make lint/test` (CI calls the same Make targets you run locally) |
| `manifests` | Installing tools by hand (`curl | tar`, `$GITHUB_PATH`), running third-party scanners |
| `secrets` | `fetch-depth: 0` (full history), passing `GITHUB_TOKEN` via `env:` |
| `image` | `needs:`, job-level `permissions:`, `if:` on steps (push only on main), step `id` + `outputs` |
| `bump` | Using another job's outputs (`needs.image.outputs.digest`), committing from CI |

### Exercises
1. Add a `workflow_dispatch` input (e.g. `skip_scan: boolean`) and use it in an `if:`.
2. Add a job `matrix` running `make test` on Python 3.11 and 3.12.
3. Make a deliberate lint error on a branch, open a PR, read the failing log, fix, watch it go green.
4. Read the `action.yml` of `actions/checkout` at the pinned SHA. List its inputs.
5. Turn on branch protection: require `test`, `manifests`, `secrets`, `image` before merge.
6. Explain why PRs build the image but never push it.

### Self-check
- Why does every job start with `actions/checkout`?
- What can `GITHUB_TOKEN` do in our `bump` job, and why only there?
- Tag vs SHA pinning — what attack does SHA pinning prevent?
- What happens to an in-progress run when you push again (our `concurrency:` block)?

### Resources
- Workflow syntax: https://docs.github.com/actions/writing-workflows/workflow-syntax-for-github-actions
- Contexts & expressions (`${{ }}`): https://docs.github.com/actions/writing-workflows/choosing-what-your-workflow-does/accessing-contextual-information-about-workflow-runs
- Security hardening for Actions: https://docs.github.com/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
- Creating actions (to understand `action.yml`): https://docs.github.com/actions/sharing-automations/creating-actions/about-custom-actions

---

## 3. Prometheus / PromQL

### Mental model
```
app :8000/metrics (plain text)  ◄── scraped every 15s ──  Prometheus (time-series DB + rule engine)
                                                              ├─► recording rules → alert rules → Alertmanager (routing)
                                                              └─► Grafana (queries PromQL, draws panels)
```
- **Pull, not push:** apps expose `/metrics`; Prometheus fetches it. A missing target is itself a signal (`up`).
- **Series = name + labels:** `http_requests_total{handler="/v1/chat/completions",status="5xx"}` — every label combination is its own series.
- **On Kubernetes:** the Prometheus Operator turns `ServiceMonitor` / `PrometheusRule` objects into Prometheus config.

### Core concepts → where they are in this repo
| Concept | What it is | Look at |
|---|---|---|
| Counter / gauge / histogram | Only up / up-and-down / bucketed counts | `observability/vllm-metrics-v0.29.0.txt` |
| `rate()` | Per-second increase of a counter over a window | every `rate(...[5m])` in `prometheusrule.yaml` |
| `histogram_quantile` | Percentile estimate from buckets | `llm:e2e_latency_seconds:p95_5m` |
| Aggregation | `sum by (status) (...)`, `max(...)` | dashboard queries |
| Recording rule | Pre-computed query stored as a new series | `llm:*` rules |
| Alert rule + `for:` | Condition that must hold for a duration before firing | `LLM*` alerts |
| Absent data | No series ≠ 0; `or vector(0)` | `LLMEndpointDown` |
| ServiceMonitor | "Scrape the pods behind Services with these labels, on this port name" | `templates/servicemonitor.yaml` |
| promtool | Lint + unit-test rules offline | `make rules-test`, `observability/tests/alerts-test.yaml` |

### Self-check
- Counter vs gauge vs histogram — one vLLM example of each?
- Why does a burn-rate alert use two windows?
- Why can't `up == 0` catch a deleted pod?
- What does a ServiceMonitor select, and which port name must match?

### Resources
- Querying basics: https://prometheus.io/docs/prometheus/latest/querying/basics/
- Metric types: https://prometheus.io/docs/concepts/metric_types/
- Unit-testing rules: https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/
- SRE workbook, Alerting on SLOs: https://sre.google/workbook/alerting-on-slos/

---

## 4. Rego / OPA / conftest (policy as code)

### Mental model
- **OPA** = a general policy engine. **Rego** = its language. **conftest** = a CLI that runs Rego
  against config files (YAML, JSON, Dockerfile…). Same Rego is used by OPA Gatekeeper in-cluster.
- Rego is **declarative**: you describe *what counts as a violation*; the engine finds all matches.
- Each input document (one K8s object) is `input`. Rules named `deny` / `violation` / `warn` produce results.
```
helm template ... | conftest test -p policy -     # each rendered object → evaluated → deny/warn messages
```

### Read our policy line by line (`policy/kubernetes.rego`)
| Construct | Example from our file | Meaning |
|---|---|---|
| package | `package main` | conftest looks in `main` by default |
| Rule with condition | `pod_spec := input.spec if input.kind == "Pod"` | Defined only when the condition holds |
| Partial set | `issue contains "..." if { ... }` | Each match adds one element to the set |
| Iteration | `some c in pod_spec.containers` | "for some container c…" |
| Negation | `not c.securityContext.readOnlyRootFilesystem == true` | Fires when missing *or* false |
| Helper function | `drops_all(c) if "ALL" in c.securityContext.capabilities.drop` | Reusable boolean |
| Multiple definitions = OR | two `digest_pinned(c)` rules | Pinned by digest **or** pull policy Never |
| deny vs warn | `deny contains ... if { not is_hook; ... }` | Fail CI vs just report |

Gotcha we hit: conftest treats rules named `violation` like `deny` — that's why the helper set is `issue`.

### Testing policies (`policy/kubernetes_test.rego`)
- `test_*` rules + `with input as {...}` replace the input with a fake object.
- `json.patch` builds a "bad" variant of a good object → assert a specific message appears.
- Run: `conftest verify -p policy`.

### Exercises
1. Add a rule: deny containers without a CPU **request**. Write a passing and a failing test first.
2. Add a `warn` (not deny) when a Deployment has `replicas: 1`. Run against the AKS render.
3. Write a rule that denies images from registries other than `docker.io` and `ghcr.io`.
4. Use `conftest test --output table` and `--namespace` options; read the docs for `--combine`
   (evaluate all docs together — e.g. "every Deployment must have a matching NetworkPolicy").
5. Try the same rule in the OPA playground: https://play.openpolicyagent.org

### Self-check
- Why does `not x == true` behave differently from `x == false` when `x` is missing?
- What's the difference between unit tests for the chart and policy tests?
- conftest (in CI) vs Gatekeeper/Kyverno (admission control in-cluster) — when would you use each?

### Resources
- Rego policy language: https://www.openpolicyagent.org/docs/latest/policy-language/
- Rego style guide: https://docs.styra.com/opa/rego-style-guide
- conftest docs: https://www.conftest.dev/
- OPA playground: https://play.openpolicyagent.org

---

## Tracking
| Topic | Read | Exercises done | Can explain in interview |
|---|---|---|---|
| Helm | ☐ | ☐ | ☐ |
| GitHub Actions | ☐ | ☐ | ☐ |
| Prometheus / PromQL | ☐ | ☐ | ☐ |
| Rego / conftest | ☐ | ☐ | ☐ |

Later additions to this list as we go: **Argo CD** (step 8 — start with docs/learning/step8-argocd.md), **Terraform for AKS** (step 9 — start with docs/learning/step9-terraform.md),
**Prometheus/PromQL** (now section 3 above).
