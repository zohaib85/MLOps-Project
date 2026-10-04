# Step 6 — Helm chart `charts/vllm` (run it on kind)

**Goal:** package the inference server as a production-shaped Kubernetes workload, prove it on a
free local cluster (kind), then reuse the exact chart on AKS with a different values file.

## How the pieces fit
```
config/model.yaml ──make values──► charts/vllm/values-model.yaml   (generated, committed, drift-checked)
                                         │
deploy/envs/kind/values.yaml ──┐         ▼
deploy/envs/aks/values.yaml  ──┴──► helm template/upgrade charts/vllm ──► Deployment, Service, SA, PVC, NetworkPolicy
```
| Engine | Where | Image | GPU |
|---|---|---|---|
| `mock` | kind / CI | `llm-platform-harness` (our image: smoke tests + OpenAI-compatible stub) | no |
| `vllm` | AKS | pinned `vllm/vllm-openai@sha256:…` | `nvidia.com/gpu: 1` |

The mock is **not a model** — it exists so the chart's packaging, probes, security settings,
storage and network policy can be tested without a GPU. Quality/performance only come from vLLM.

## Design decisions worth explaining in an interview
| Decision | Why |
|---|---|
| `strategy: Recreate` | One GPU: a RollingUpdate starts the new pod first, which can't get the GPU → stuck Pending |
| **startupProbe** (10 min budget) + strict liveness | Model download + load is slow; without a startup probe, liveness kills the pod mid-load → crash loop |
| Non-root, read-only root FS, drop ALL caps, seccomp RuntimeDefault | Secure-by-default; writable paths are explicit emptyDirs (`/tmp`, `$HOME`) |
| `/dev/shm` as memory-backed emptyDir | vLLM needs shared memory (`--ipc=host` locally); container default is 64 MB |
| `HF_HOME` on a PVC + `fsGroup` | Weights survive restarts; `fsGroup` makes the volume writable for the non-root user |
| `automountServiceAccountToken: false` | The server never calls the K8s API — no token to steal |
| NetworkPolicy: default-deny, allow same-namespace ingress, DNS, HTTPS egress **except 169.254.169.254** | Blocks the cloud metadata endpoint (classic credential-theft path) |
| Image `fail`s without a digest | "Pinned by digest" is enforced by the chart, not just convention |
| Values generated from `model.yaml` + drift test | One source of truth for laptop, chart, tests, benchmarks |

## Install tools (WSL, one time)
```bash
# helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
# kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64 && chmod +x kind && sudo mv kind /usr/bin/kind
helm version && kind version
```

## Run it
```bash
cd ~/MLOps-Project && source .venv/bin/activate && git pull
make test            # 21 unit tests incl. chart rendering (needs helm)
make lint            # helm lint --strict for kind + aks, values drift check

make kind-up         # creates cluster "llm-platform"; context becomes kind-llm-platform
make kind-deploy     # builds harness image, loads it into kind, helm install --wait
kubectl -n llm get pods -w     # watch: 0/1 Running for ~20s (simulated model load) → 1/1, then Ctrl+C
make kind-test       # helm test: in-cluster pod calls /health and /v1/models
make kind-smoke      # port-forward + smoke tests (quality gate skipped for the mock)
```

## Things to look at (the learning part)
```bash
kubectl -n llm describe pod -l app.kubernetes.io/instance=llm | sed -n '/Events/,$p'
#   → "Startup probe failed: connection refused" during the simulated load, then healthy
kubectl -n llm get pod -l app.kubernetes.io/instance=llm -o jsonpath='{.items[0].spec.securityContext}'; echo
kubectl -n llm get pvc                       # model-cache Bound
kubectl -n llm exec deploy/llm-vllm -- id    # uid=1000 — not root
kubectl -n llm exec deploy/llm-vllm -- touch /should-fail   # read-only filesystem
```

**Experiment — see why the startup probe matters:** make loading slower than the probe budget and watch the
pod get restarted.
```bash
helm upgrade llm charts/vllm -n llm -f charts/vllm/values-model.yaml -f deploy/envs/kind/values.yaml \
  --set mock.startupDelaySeconds=90 --set probes.startup.failureThreshold=3
kubectl -n llm get pods -w     # RESTARTS climbs → CrashLoopBackOff
make kind-deploy               # restore
```

**Experiment — NetworkPolicy:** a pod in *another* namespace should be blocked.
```bash
kubectl create ns other
kubectl -n other run probe --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- -T 5 http://llm-vllm.llm:8000/health || echo "blocked ✅"
kubectl -n llm run probe --rm -it --restart=Never --image=busybox:1.36 -- \
  wget -qO- -T 5 http://llm-vllm:8000/health && echo " allowed ✅"
```
If the first call succeeds, your kind CNI isn't enforcing NetworkPolicy — note it; AKS (Cilium) does.

## Bug found on the first kind run (and what it taught)
`make kind-test` timed out. The helm-test pod reused the chart's labels, so it matched **both** the
Service selector (traffic could be routed to the test pod itself) and the NetworkPolicy podSelector
(its egress was limited to DNS + 443, so the call to :8000 was dropped). Fix: the test pod gets its own
labels; `test_only_server_pods_match_selectors` guards against regressions.
Side finding: kind's default CNI **did enforce** the NetworkPolicy.

## Clean up
```bash
make kind-down
```
