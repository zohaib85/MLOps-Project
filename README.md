# Production-Grade LLM Inference Platform on Kubernetes

**Outcome:** an OpenAI-compatible endpoint serving an open-weight instruct model with vLLM on Azure Kubernetes Service — released through GitOps, GPU-aware, observable, evaluated, secured by default, and recoverable via tested rollback — with reproducible evidence for every claim.

> **Status:** 🚧 In progress (build window 24 Sep – 21 Oct 2026). See [docs/PLAN.md](docs/PLAN.md).

## Architecture at a glance

| Plane | Components | Purpose |
|---|---|---|
| Delivery | GitHub Actions → GHCR → Git (desired state) → Argo CD | Tested, scanned, immutable releases; CI never holds cluster credentials |
| Runtime | AKS (system pool + T4 GPU pool) → ingress → vLLM | Scheduling, probes, security context, network policy |
| Evidence | pytest eval set, k6/Locust, Prometheus, Grafana, DCGM | Prove behavior, performance, and recovery |

_Architecture diagram: coming in Week 4._

## Repository layout

```
app/                 # evaluation, smoke, and load clients
charts/vllm/         # Helm chart and values
config/              # model identity + serving parameters
deploy/argocd/       # Argo CD Application and AppProject
infra/terraform/     # AKS environment
observability/       # dashboards, alert rules, collector config
tests/               # API, manifest, policy, smoke tests
docs/                # plan, ADRs, runbook, benchmark report
.github/workflows/   # CI
Makefile             # one-command workflows (`make help`)
```

## Quick start (local GPU)

**Prerequisites:** Linux or WSL2, Docker with NVIDIA GPU support (`docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi` works), ≥ 6 GB GPU memory, Python 3.10+, `make`, ~15 GB free disk.
Windows users: follow [docs/learning/local-gpu-setup.md](docs/learning/local-gpu-setup.md) first.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

make test     # unit tests — config pinning + arg rendering, no GPU needed
make serve    # start vLLM (pinned image + model revision from config/model.yaml)
make logs     # wait for "Application startup complete", then Ctrl+C
make smoke    # health, model identity, API contract, determinism, prompt-set pass rate
```

Send a request yourself:

```bash
curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "qwen2.5-0.5b-instruct",
  "messages": [{"role": "user", "content": "In one sentence, what is Kubernetes?"}],
  "temperature": 0, "max_tokens": 64}' | jq -r '.choices[0].message.content'
```

### Teardown

| Command | Removes | Keeps |
|---|---|---|
| `make stop` | the vLLM container (frees GPU) | image + model cache — next start is fast |
| `make clean-local` | container **and** `hf-cache` volume (~1 GB model) | vLLM image |
| `docker rmi $(python3 scripts/vllm_args.py --image)` | vLLM image (~9 GB) | — |

### Where things live

| What | Where | Why |
|---|---|---|
| Model identity + serving params | `config/model.yaml` | Single source of truth for local, Helm, tests, benchmarks |
| Model weights | Docker volume `hf-cache` → `/root/.cache/huggingface` in the container | Downloaded once at the pinned revision; never in Git |
| Smoke-run records | `results/raw/smoke-*.json` (git-ignored) | Each run tagged with model revision, image digest, prompt-set version |
| Regression prompts | `app/prompts/smoke-v*.yaml` | Versioned; never edited in place |
| Helm chart | `charts/vllm` (+ generated `values-model.yaml`) | One chart; env overlays in `deploy/envs/{kind,aks}` |

## Documentation

- [Build plan](docs/PLAN.md)
- [Architecture decision records](docs/adr/)
- [AKS learning notes](docs/learning/aks-notes.md)
- [Local GPU dev setup (Windows + WSL2)](docs/learning/local-gpu-setup.md)
- [AKS Lab 01 — GPU cluster by hand](docs/learning/aks-lab-01-cluster.md)
- [Step 6 — Helm chart on kind](docs/learning/step6-helm-chart.md)
- [Step 7 — CI pipeline](docs/learning/step7-ci.md)
- [Step 8 — GitOps with Argo CD](docs/learning/step8-argocd.md)
- [Step 9 — Terraform for AKS](docs/learning/step9-terraform.md)
- [Steps 11–13 — Observability, SLOs, alerts](docs/learning/step11-observability.md)
- [SLOs](docs/slo.md) · [Runbook](docs/runbook.md)
- [Skill gaps — Helm, GitHub Actions, Rego study plan](docs/learning/skill-gaps.md)

## Scope & limitations

- **Scope:** single model, single GPU node profile, one Azure region. Deliberately excludes training/fine-tuning, multi-node inference, and RAG. Prompts are synthetic; no user data is processed.
- **Model quality:** Qwen2.5-0.5B-Instruct is chosen for cost and fast iteration, not answer quality. Known miss: answers "Docker" to the Kubernetes prompt (tracked in `smoke-v2`).
- **Local ≠ target:** laptop runs (RTX A2000 via WSL2) are for development only and need a WSL-specific setting (`VLLM_WSL2_ENABLE_PIN_MEMORY=1`). Published numbers come only from the AKS T4 environment.
- **No auth locally:** the local endpoint binds to `127.0.0.1` only. Authentication and rate limiting arrive with the Kubernetes gateway (Week 2).
- **Pinned runtime:** vLLM `v0.29.0-cu129`. `v0.30.0-cu129` was rejected (broken torch/torchvision build — see `config/model.yaml`).
- **Evidence:** [Week 1 local baseline](docs/evidence/week1-local-baseline.md)
