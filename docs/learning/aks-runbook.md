# AKS runbook — from empty subscription to observed, drilled vLLM on a T4

Everything from here runs on AKS (decision 10 Oct: no more kind work). This one document takes you
from `make infra-up` to the Week 1–3 exit gates. Run it top to bottom; every **⏸ stop point** is a
safe place to pause (scale the GPU to 0 or tear everything down) and come back later.

| Part | Covers | Time | Meter running |
|---|---|---|---|
| 0. Prepare | login, IP, preflight | 10 min | nothing |
| A. Platform | cluster, Argo CD, monitoring stack | 20 min | system node |
| B. GPU + vLLM | GPU node, device plugin, GitOps deploy, smoke | 25 min | + T4 |
| C. Release gate (step 10) | Git change → traceable release → restore | 30 min | + T4 |
| D. Observe (steps 11–12) | targets, dashboard, load | 20 min | + T4 |
| E. Drills (step 14) | pod deletion, failing release → rollback | 30 min | + T4 |
| F. Teardown | everything off | 10 min | — |

**Cost (rough, eastus list prices — check the Azure pricing page):** system node `Standard_D2s_v4`
≈ $0.10/h, T4 node `Standard_NC4as_T4_v3` ≈ $0.53/h, plus disks/load balancer cents per hour.
All parts in one sitting (~2.5 h) ≈ **$2–3**. The budget alert is your safety net, not your plan:
**`make gpu-off` whenever you stop for more than ~30 minutes.**

Golden rules (Lab 01 lessons):
- Never `sudo` with `kubectl`/`az`/`helm`/`make`.
- `make aks-check` before anything that changes the cluster — targets that need it run it themselves.
- Paste me any error as-is; don't improvise fixes on a running meter.

---

## 0. Prepare (laptop, free)
```bash
cd ~/MLOps-Project && git checkout main && git pull
az login --tenant <tenant-id>            # browser flow
az account show -o table                 # right subscription?
curl -s https://ifconfig.me; echo        # has your public IP changed since step 9?
nano infra/terraform/terraform.tfvars    # update api_server_authorized_ip_ranges if it has
make preflight                           # ✔ login, SKUs, quota
```
> Home IPs change. If `kubectl` later hangs or times out, this is the first thing to check
> (the API server only accepts your IP). Fix the tfvars and `make infra-plan && make infra-up` — an in-place update.

## A. Platform (system node only)
```bash
make infra-up                 # skip if the cluster from step 9 still exists — then: make aks-credentials
make aks-check                # context: aks-llm-lab ✔
kubectl get nodes -o wide     # 1 system node Ready (GPU pool exists with 0 nodes)

make argocd-install           # pinned v3.5.3, ~2 min
make monitoring-install       # kube-prometheus-stack 92.2.0, ~3-5 min
kubectl get pods -A | grep -v Running     # everything Running/Completed?
kubectl top nodes             # the 2-vCPU system node now carries Argo CD + monitoring
```
Why monitoring **before** the app: the chart only renders ServiceMonitor/PrometheusRule when the
cluster serves `monitoring.coreos.com/v1`. Installed first, the very first Argo CD sync includes them.

If pods stay `Pending` with *Insufficient cpu/memory* → send me `kubectl describe pod <name> -n <ns>`;
the fix is a bigger system node (one Terraform variable), not removing requests.

⏸ **Stop point A:** idle cost ≈ system node only. Or `make infra-down` (repeat A next time).

## B. GPU + vLLM via GitOps — Week 1 exit gate on the T4
```bash
make gpu-on                                    # T4 billing starts; ~4-6 min for node + driver
kubectl get nodes -l workload=gpu -w           # wait for Ready, then Ctrl+C
make gpu-plugin                                # NVIDIA device plugin (nodeSelector workload=gpu)
kubectl get nodes -l workload=gpu -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'; echo   # → 1
make dcgm-install                              # GPU metrics exporter (lands on the GPU node)

make argocd-apps-aks                           # AppProject + llm-aks Application → Argo CD syncs from main
kubectl -n argocd get applications -w          # llm-aks: Synced, then Healthy (Ctrl+C)
kubectl -n llm get pods -w                     # ContainerCreating (≈9 GB image pull) → Running → 1/1 Ready
kubectl -n llm logs deploy/llm-vllm -f         # "Application startup complete" (Ctrl+C)
```
First start is slow: image pull (~5-8 min) happens before the startup probe's 10-minute window;
model download (~1 GB) + load happen inside it.

**Week 1 exit gate (T4 half):**
```bash
make aks-smoke        # health, model identity + revision, API contract, determinism, prompt-set pass rate
```
Expect all green (the known "Docker" miss stays under the 0.8 pass-rate gate). Results land in
`results/raw/smoke-*.json` tagged with model revision + image digest — keep that file for evidence.

Also capture for evidence:
```bash
kubectl -n llm exec deploy/llm-vllm -- nvidia-smi
kubectl -n argocd get application llm-aks -o jsonpath='{.status.sync.revision}'; echo   # Git SHA deployed
```

⏸ **Stop point B:** `make gpu-off` (vLLM pod goes Pending — that's expected; `LLMPodPending` will
fire after 10 min, which is correct behaviour). `make gpu-on` resumes; the model is cached on the PVC.

## C. Release gate (step 10): Git change → traceable release → previous version restorable
The change: shrink the context window 4096 → 2048 tokens. Harmless, and visible from the API.

**1. Baseline**
```bash
kubectl -n llm port-forward svc/llm-vllm 8000:8000 &      # keep running for this part
curl -s localhost:8000/v1/models | jq '.data[0] | {id, max_model_len}'   # 4096
```
**2. Change through a PR** (never `kubectl edit` — Argo CD would revert it):
```bash
git checkout -b release/context-2048
sed -i 's/max_model_len: 4096/max_model_len: 2048/' config/model.yaml
make values                                # regenerates charts/vllm/values-model.yaml
git commit -am "serving: max_model_len 4096 -> 2048 (step 10 release gate)"
git push -u origin release/context-2048    # open PR → CI green → merge
```
**3. Watch Argo CD roll it out** (it polls Git every ~3 min; Recreate = old pod stops, new pod starts):
```bash
kubectl -n argocd get application llm-aks -w     # OutOfSync → Synced; Healthy after model load
kubectl -n llm get pods -w
curl -s localhost:8000/v1/models | jq '.data[0].max_model_len'    # 2048 (restart the port-forward if it dropped)
```
**4. Trace it** — every link from running pod back to the commit:
```bash
kubectl -n argocd get application llm-aks -o jsonpath='{range .status.history[*]}{.id}{"  "}{.revision}{"  "}{.deployedAt}{"\n"}{end}'
git log --oneline -3 origin/main
```
**5. Restore the previous version — the GitOps way is `git revert`:**
```bash
git checkout main && git pull
git revert --no-edit HEAD        # if HEAD is the merge commit: git revert -m 1 --no-edit HEAD
git push -u origin HEAD:release/revert-context    # PR → merge
curl -s localhost:8000/v1/models | jq '.data[0].max_model_len'    # 4096 again
```
Evidence: the history output (three revisions), both `/v1/models` outputs, the PR links.
**Step 10 done.**

## D. Observe (steps 11–12)
```bash
make prom-ui        # http://localhost:9090
```
- Status ▸ Targets: `serviceMonitor/llm/llm-vllm` and `dcgm-exporter` **UP** (if `llm-vllm` is DOWN with
  *context deadline exceeded* → NetworkPolicy; send me `kubectl -n llm get networkpolicy -o yaml`).
- Alerts: 7 `LLM*` rules, inactive (`LLMPodPending` may be firing if you used stop point B — it clears).
```bash
make grafana-ui     # http://localhost:3000 — admin / $(make grafana-password)
```
Dashboards ▸ *LLM inference — service, engine, resources*: pick namespace `llm`, service `llm-vllm`.
```bash
make load LOAD_ARGS="--concurrency 1 --duration 120"
make load LOAD_ARGS="--concurrency 8 --duration 180"
```
Watch: request rate, p95, TTFT, tokens/s, running/waiting, KV cache, GPU util/memory/power.
**Screenshot** the full dashboard during the concurrency-8 run (evidence for step 12).
Note the loadgen's printed p50/p95 at both levels — first data points for Week 4.

## E. Drills (step 14)
**Drill 1 — pod deletion (self-healing)**
```bash
date -u +%T; kubectl -n llm delete pod -l app.kubernetes.io/name=vllm
kubectl -n llm get pods -w        # new pod → Ready; note the time
make aks-smoke
```
Record: time to Ready (model cached on the PVC → much faster than first start). Did `LLMEndpointDown`
fire? It shouldn't if recovery < 5 min — that's what `for: 5m` is for.

**Drill 2 — failing release → health gate → rollback**
A release that passes CI but fails at runtime: context length above the model's native 32k.
```bash
git checkout main && git pull && git checkout -b drill/bad-release
sed -i 's/max_model_len: 4096/max_model_len: 65536/' config/model.yaml && make values
git commit -am "drill: max_model_len 65536 (exceeds model limit — expected to fail)"
git push -u origin drill/bad-release      # PR → CI green (CI can't know the model's runtime limit) → merge
```
Watch it fail: `kubectl -n llm get pods -w` (CrashLoopBackOff), `kubectl -n llm logs deploy/llm-vllm --previous`
(the validation error), Argo CD `llm-aks`: **Degraded** — the health gate. Alerts: `LLMPodRestarting`,
then `LLMEndpointDown`. Follow the runbook link from the alert, then roll back:
```bash
git checkout main && git pull && git revert -m 1 --no-edit HEAD
git push -u origin HEAD:drill/rollback    # PR → merge → Argo CD → Healthy
make aks-smoke
```
Record: time from merge → Degraded → revert merged → Healthy (your MTTR), alert timeline screenshot.
Talking point: `bfloat16` on a T4 is the same class of mistake — that one **is** caught in CI
(`test_t4_compatible_dtype`). Move checks left when you can; keep the runtime gate for what you can't.

## F. Teardown
```bash
make gpu-off                       # if continuing another day with the cluster up
make infra-down                    # done for now: removes cluster, MC_ group, budget
az group list -o table             # rg-llm-lab and MC_rg-llm-lab_* gone
```

## Send me after each part
Paste outputs (or "done") and I'll write the evidence docs (`docs/evidence/week1-t4-baseline.md`,
`week2-release-gate.md`, `week3-observability-drills.md`) and tick `docs/PLAN.md`.
