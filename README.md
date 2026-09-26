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

## Quick start

_Filled in at the end of Week 1._ Run `make help` to see available targets.

## Documentation

- [Build plan](docs/PLAN.md)
- [Architecture decision records](docs/adr/)
- [AKS learning notes](docs/learning/aks-notes.md)

## Scope & limitations

Single model, single GPU node profile, one Azure region. Deliberately excludes training/fine-tuning, multi-node inference, and RAG. Prompts are synthetic; no user data is processed.
