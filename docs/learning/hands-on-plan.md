# Hands-on learning plan — Helm, Prometheus, GitHub Actions

**You do the work; Claude reviews.** Every lab below is something *you* type, run, break and fix.
Most labs end in a real PR to this project, so the learning *is* the project progress.
Concepts and reading lists live in [skill-gaps.md](skill-gaps.md); this file is the practice.

## Working agreement
| You | Claude |
|---|---|
| Type every command and every edit yourself | Explains concepts when you ask |
| Try for 15 minutes before asking | Gives **hints in levels**: say "hint 1" (direction), "hint 2" (where to look), "hint 3" (near-answer). Never the full solution unless you say "show me" |
| Open the PR yourself, read CI yourself first | Reviews your PR as comments only — never pushes to it unless you say "take over" |
| Paste errors as-is | Asks you what you think it means before explaining |
| Answer the "explain back" question in your own words | Tells you what's missing from your answer |

Each lab: **Goal · Do · Done when · Explain back.** Hints are folded — open only when stuck.
No kind. Labs marked 🖥 need only your laptop (free); ☁ labs are AKS checkpoints done during the
[AKS runbook](aks-runbook.md) sessions, so no extra cloud time.

## Schedule (≈ 1–1.5 h per session)
| Session | Labs | You produce |
|---|---|---|
| 1 | Helm H1–H2 🖥 | answers to H1/H2 questions |
| 2 | Helm H3–H5 🖥 | **PR #1 (yours):** configurable termination grace period + test |
| 3 | GitHub Actions G1–G3 🖥 | playground workflow on a learning branch; a deliberately broken draft PR, fixed |
| 4 | Prometheus P1–P3 🖥 | local Prometheus scraping the mock; PromQL answers |
| 5 | Prometheus P4 🖥 | **PR #2:** slow-burn alert + promtool test + runbook section |
| 6 | ☁ AKS runbook A–D + P6 | live targets/dashboard; P6 answers |
| 7 | Prometheus P5 🖥 → ☁ | **PR #3:** new dashboard panel, seen live in Grafana via GitOps |
| 8 | GitHub Actions G4–G5 🖥 | **PR #4:** Python matrix · **PR #5:** Dependabot |
| 9 | ☁ AKS runbook E (drills) | drill timings |
| 10 | Stretch H6 + explain-back round | PDB decision write-up |

Order matters: Helm first (everything is a chart), Prometheus before session 6 (you'll *use* it live),
and every PR you open exercises GitHub Actions anyway.

---

## Helm

### H1 — Render and read 🖥 (30 min)
**Goal:** know where every value ends up — Kubernetes never sees templates, only rendered YAML.
**Do:**
```bash
cd ~/MLOps-Project
helm template llm charts/vllm -n llm \
  -f charts/vllm/values-model.yaml -f deploy/envs/aks/values.yaml -f deploy/envs/aks/harness-image.yaml \
  > /tmp/aks.yaml
grep '^kind:' /tmp/aks.yaml
```
Answer from `/tmp/aks.yaml` + the templates:
1. Which file and line produce `--max-model-len 4096`? Trace it back to `config/model.yaml`.
2. Where does `nvidia.com/gpu: 1` come from? What would you change to request 0 GPUs?
3. Why does the output contain no `ServiceMonitor`, although `metrics.serviceMonitor.enabled: true`?
4. What is the full image reference of the vLLM container, and which helper builds it?

<details><summary>Hint 1</summary>Q1 is a chain of four files: <code>grep -rn -- max-model-len charts/vllm scripts</code>, then read <code>scripts/render_chart_values.py</code> and look for <code>.Values.vllm.args</code> in the deployment template.</details>
<details><summary>Hint 2</summary>Q3: look at the first line of <code>templates/servicemonitor.yaml</code>. What does Helm assume about the cluster when there is no cluster?</details>

**Done when:** you can answer all four without guessing. **Explain back:** "What does `helm template` do that `kubectl apply` can't?"

### H2 — Values precedence 🖥 (20 min)
**Goal:** predict, then verify, which value wins.
**Do:** for each command, *write down your prediction first*, then run it and grep the result:
```bash
R="helm template llm charts/vllm -f charts/vllm/values-model.yaml -f deploy/envs/aks/values.yaml -f deploy/envs/aks/harness-image.yaml"
$R | grep -A2 'requests:'                                   # which file set cpu "2"?
$R --set resources.requests.cpu=1 | grep -A2 'requests:'
$R -f deploy/envs/kind/values.yaml | grep -m1 'image:'      # what happens when kind values come last?
```
**Done when:** 3/3 predictions right (or you can explain why you were wrong).
**Explain back:** precedence order of chart defaults, `-f` files (in order) and `--set`.

### H3 — Your first chart feature: configurable grace period 🖥 → PR (60 min)
**Goal:** change a template, add a value, test it, ship it through CI and Argo CD.
`terminationGracePeriodSeconds: 30` is hard-coded in `charts/vllm/templates/deployment.yaml`.
vLLM needs time to finish in-flight requests when the pod stops, and long generations can exceed 30 s.
**Do:**
1. Branch: `git checkout main && git pull && git checkout -b feat/grace-period`
2. Add a value `terminationGracePeriodSeconds` to `charts/vllm/values.yaml` (default 30, with a comment saying why it exists).
3. Use it in `deployment.yaml` instead of the hard-coded number.
4. Set `60` in `deploy/envs/aks/values.yaml`.
5. Add a test in `tests/unit/test_chart.py` asserting kind renders 30 and aks renders 60 (copy the style of the existing tests — `render()` and `deployment()` helpers).
6. Run `make lint test` until green. Commit, push, open the PR, read CI.

<details><summary>Hint 1</summary>Template syntax for a value: <code>{{ .Values.someKey }}</code>. Look at how <code>.Values.probes</code> is used in the same file.</details>
<details><summary>Hint 2</summary>In the test, <code>dep, spec, container = deployment(render(repo_root, "aks"))</code> — the field lives on <code>spec</code>.</details>

**Done when:** CI green, PR reviewed, merged. ☁ Checkpoint (next AKS session):
`kubectl -n llm get pod -l app.kubernetes.io/name=vllm -o jsonpath='{.items[0].spec.terminationGracePeriodSeconds}'` → 60, without you running Helm — Argo CD did it.
**Explain back:** what happens to an in-flight request when the grace period is too short?

### H4 — Read a guardrail 🖥 (15 min)
**Do:** render with `--set vllm.image.digest=` and read the error. Find the exact line that produced it.
**Explain back:** why is "fail the render" better than "warn in the README"?

### H5 — Conditionals and cluster capabilities 🖥 (20 min)
**Do:** render the aks values twice — without and with `--api-versions monitoring.coreos.com/v1` — and diff the `kind:` lists.
Then find where the Makefile and CI pass that flag, and why.
**Explain back:** how does Argo CD know which APIs your AKS cluster has? What would break if the chart always rendered the ServiceMonitor?

### H6 — Stretch: a PodDisruptionBudget, and deciding *not* to ship it 🖥 (45 min)
**Do:** add `templates/poddisruptionbudget.yaml` gated by `pdb.enabled` (default false). Enable it in aks values locally and run `make test`.
1. Which test fails, and why? (Read its docstring.)
2. With `replicas: 1` and `maxUnavailable: 0`, what happens when AKS upgrades the GPU node?
3. Decide: ship it disabled, ship it enabled, or don't ship it. Write 5 lines justifying it in the PR description.
**Explain back:** what a PDB protects against, and when it hurts.

---

## Prometheus

### P1 — Run Prometheus yourself 🖥 (45 min)
**Goal:** write a scrape config by hand and see a target go UP. Everything in Docker on your laptop.
**Do:**
```bash
make harness-image                                    # the mock server image
docker network create promlab
docker run -d --name mock --network promlab -p 8000:8000 \
  -e MOCK_SERVED_NAME=qwen2.5-0.5b-instruct llm-platform-harness:dev
curl -s localhost:8000/metrics | head                  # what metric types do you see?
mkdir -p ~/prom-lab && nano ~/prom-lab/prometheus.yml  # you write this (outside the repo)
docker run -d --name prom --network promlab -p 9090:9090 \
  -v ~/prom-lab:/etc/prometheus prom/prometheus:v3.15.0
```
Your `prometheus.yml` needs: a global scrape interval of 15s and one scrape job named `mock` whose target is the mock container on port 8000.
<details><summary>Hint 1</summary>Top-level keys: <code>global:</code> and <code>scrape_configs:</code>. Docs: prometheus.io → Configuration → scrape_config.</details>
<details><summary>Hint 2</summary>Inside the <code>promlab</code> network, containers reach each other by name: the target is <code>mock:8000</code>, not localhost. The target goes in <code>static_configs: - targets: [...]</code>.</details>

**Done when:** http://localhost:9090 → Status ▸ Target health shows `mock` **UP**.
**Explain back:** pull vs push — why does Prometheus scrape instead of apps sending metrics?
(Changed the config? `docker restart prom`.)

### P2 — PromQL basics 🖥 (30 min)
Generate traffic: `python3 scripts/loadgen.py --concurrency 4 --duration 300` (keep it running). In the Prometheus UI:
1. Graph `http_requests_total`. Now graph `rate(http_requests_total[1m])`. Why is the first one useless?
2. Requests per second **by status class** — one query.
3. Requests per second for `/v1/chat/completions` only.
4. `vllm:num_requests_running` — counter or gauge? How do you know without docs?
5. Tokens generated per second.

**Done when:** five working queries saved in a note. **Explain back:** when do you use `rate()` and when not?

### P3 — Histograms and fault injection 🖥 (30 min)
Restart the mock with latency and errors injected:
```bash
docker rm -f mock && docker run -d --name mock --network promlab -p 8000:8000 \
  -e MOCK_SERVED_NAME=qwen2.5-0.5b-instruct -e MOCK_LATENCY_S=0.3 -e MOCK_ERROR_RATE=0.1 llm-platform-harness:dev
```
1. Write the p95 latency query from `vllm:e2e_request_latency_seconds_bucket`. Does it match the loadgen's printed p95?
2. Remove `sum by (le)` from your query — what changes and why?
3. Write the 5xx **error ratio** (errors ÷ all) for chat requests. Does it come out near 0.1?

**Explain back:** why a histogram percentile is an *estimate* (hint: buckets).

### P4 — Write an alert, test it, document it 🖥 → PR (75 min)
**Goal:** the full alerting workflow: rule → unit test → runbook → CI.
`docs/slo.md` says a slow-burn alert was deliberately omitted. Add it:
`LLMErrorBudgetSlowBurn` — error ratio above **6×** the budget over **6h** and **30m**, `for: 15m`, severity `warning`.
**Do:**
1. Branch `feat/slow-burn-alert`.
2. Add a `llm:errors:ratio_rate6h` and `llm:errors:ratio_rate30m` recording rule and the alert in `charts/vllm/templates/prometheusrule.yaml` (copy the fast-burn pattern — note the backtick escaping for `{{ $value }}`).
3. Add two promtool tests in `observability/tests/alerts-test.yaml`: 7% errors → fires; 3% → quiet.
4. Run `make test` — one test will fail and tell you what else is missing. Fix it.
5. Add the alert to the table in `docs/slo.md`; remove the "deliberately omitted" sentence.
6. `make lint test rules-test` green → PR.

<details><summary>Hint 1</summary>6 × 1% = 0.06 — use <code>mulf 6 $budget</code> like the fast-burn rule uses 14.4.</details>
<details><summary>Hint 2</summary>The failing test is <code>test_every_alert_has_severity_and_runbook_anchor</code>: <code>docs/runbook.md</code> needs a <code>## LLMErrorBudgetSlowBurn</code> section.</details>
<details><summary>Hint 3</summary>promtool series for 7% errors: 2xx <code>'0+93x800'</code>, 5xx <code>'0+7x800'</code> with <code>interval: 30s</code> gives 400 minutes of data — enough for the 6h window.</details>

**Explain back:** why does the slow-burn alert use `severity: warning` while fast-burn is `critical`?

### P5 — Add a dashboard panel 🖥 → ☁ PR (45 min)
**Goal:** dashboards as code, shipped by GitOps.
Add a timeseries panel **"Preemptions"** to the *Inference* row of `charts/vllm/dashboards/llm-inference.json`,
using `vllm:num_preemptions_total` (counter → you know what to do).
**Do:** copy an existing single-series timeseries panel, give it a unique `id`, place it with `gridPos`,
change title/description/expr. `make test` checks metric names, unique ids and legend rules.
**Done when:** PR merged; ☁ in the next AKS session the panel appears in Grafana without you touching Grafana.
**Explain back:** why is a ConfigMap + sidecar better than importing the JSON in the Grafana UI?

### P6 — Prometheus on AKS ☁ (during runbook part D, 20 min)
In the AKS Prometheus UI (`make prom-ui`):
1. Status ▸ Service discovery: find the `llm-vllm` target. Which `__meta_kubernetes_*` label became `model_revision`?
2. Status ▸ Rule health: when did `llm:errors:ratio_rate5m` last evaluate, and how long did it take?
3. Alerts: which alert is closest to firing during `make load --concurrency 8`? Why?
4. Query `DCGM_FI_DEV_FB_USED`. Why is GPU memory ~85% used with zero traffic?
**Explain back:** what the Prometheus Operator did with your ServiceMonitor.

---

## GitHub Actions

### G1 — Read a real run 🖥 (30 min)
Open the latest run on `main` (Actions tab) next to `.github/workflows/ci.yml`.
1. Draw the job graph (which jobs run in parallel, which wait — find every `needs:`).
2. Why did `bump` run on `main` but get *skipped* on every PR? Find the `if:`.
3. Which job has `contents: write` permission, and why only that one?
4. Find where the image digest travels from `image` to `bump`.
**Explain back:** what is shared between two jobs, and what isn't?

### G2 — Playground workflow 🖥 (45 min)
**Goal:** learn the syntax without risking real CI. On a branch you never merge:
```bash
git checkout -b learn/actions-playground
nano .github/workflows/playground.yml
```
Write a workflow that triggers on `push` to branches `learn/**` and has:
1. a job `hello` that prints the commit SHA, branch and actor (use contexts);
2. a job `matrix` running on three values (`[a, b, c]`) printing its value;
3. a job `summary` that `needs` both, reads an **output** set by `hello`, and writes a line to `$GITHUB_STEP_SUMMARY`.
Push and watch it run.
<details><summary>Hint 1</summary>Contexts: <code>${{ github.sha }}</code>, <code>${{ github.ref_name }}</code>, <code>${{ github.actor }}</code>.</details>
<details><summary>Hint 2</summary>Outputs: in a step <code>echo "x=hi" &gt;&gt; "$GITHUB_OUTPUT"</code> (step needs an <code>id</code>), then job-level <code>outputs: { x: ${{ steps.&lt;id&gt;.outputs.x }} }</code>, read with <code>needs.hello.outputs.x</code>.</details>

**Done when:** all three jobs green, summary visible on the run page. Delete the branch afterwards.

### G3 — Break CI on purpose 🖥 (30 min)
Open a **draft** PR with: one ruff violation (an unused import in `scripts/loadgen.py`) and one failing assertion in a unit test.
Read both failures in the logs *before* fixing. Which job failed first? Did `image` run? Why not?
Fix, push, watch it go green. Close the PR without merging.
**Explain back:** why CI runs the same `make` targets you run locally.

### G4 — Real change: test on two Python versions 🖥 → PR (45 min)
Make the `test` job run on Python **3.11 and 3.12** using a `matrix`.
Things you'll discover: what the job is called in the PR checks now; whether anything breaks on 3.11
(the codebase uses `str.removesuffix`, `zip(strict=)` — check when they were added); whether
`pyproject.toml` declares a minimum version.
**Explain back:** what happens to required status checks in branch protection when a job name changes?

### G5 — Real change: keep pinned actions up to date 🖥 → PR (30 min)
All actions are pinned to commit SHAs (safe, but they go stale). Add `.github/dependabot.yml` with
weekly updates for the `github-actions` and `pip` ecosystems. After merge, look at the first Dependabot PR:
how does it update a SHA pin *and* the `# vX.Y.Z` comment?
**Explain back:** tag pinning vs SHA pinning — which attack does SHA pinning stop, and what does it cost?

---

## Progress tracker
| Lab | Done | Explain-back OK | PR |
|---|---|---|---|
| H1 · H2 · H3 · H4 · H5 · H6 | ☐ ☐ ☐ ☐ ☐ ☐ | ☐ ☐ ☐ ☐ ☐ ☐ | H3: · H6: |
| P1 · P2 · P3 · P4 · P5 · P6 | ☐ ☐ ☐ ☐ ☐ ☐ | ☐ ☐ ☐ ☐ ☐ ☐ | P4: · P5: |
| G1 · G2 · G3 · G4 · G5 | ☐ ☐ ☐ ☐ ☐ | ☐ ☐ ☐ ☐ ☐ | G4: · G5: |
