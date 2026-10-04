# Build Plan — Production-Grade LLM Inference Platform on Kubernetes

Build window: 24 Sep – 21 Oct 2026 · ~8–10 h/week · personal learning project.

## Decisions (kickoff)

| Area | Choice | Notes |
|---|---|---|
| Cloud / GPU | Azure AKS, minimal, region `eastus` | Free-tier control plane; 1× small system node; 1× T4 GPU user pool scaled to 0 when idle |
| GPU SKU | `Standard_NC4as_T4_v3` (T4 16 GB) | "Standard NCASv3_T4 Family" quota 4 vCPU — approved |
| Model | Small Apache-2.0 instruct model — `Qwen/Qwen2.5-0.5B-Instruct` (smallest, cheapest) | T4 has no bf16 → `--dtype float16`; pin HF revision hash |
| Inference | Official `vllm/vllm-openai` image, pinned by digest | We don't rebuild vLLM |
| CI | GitHub Actions | Public runs are reviewer-visible evidence |
| Registry | GHCR | Free, OCI, no extra Azure resource |
| Our image | Eval/load/smoke harness (`app/`) | Built, scanned, published by digest in CI |
| GitOps | Argo CD, same repo, `deploy/` path | CI commits digest bump; CI never holds cluster creds |
| Gateway | vLLM `--api-key` + ingress-nginx rate limits | Minimal; Envoy Gateway deferred |
| Local dev | WSL2 + Docker on RTX A2000 8GB; kind for cluster work | Laptop GPU for dev; T4 on AKS for evidence runs |

## Steps

### Step 0 — Kickoff
- [x] Upgrade subscription to Pay-As-You-Go (free trial has 0 GPU quota) + budget alert
- [x] Register resource providers
- [x] Request Azure GPU quota (NCASv3_T4, 4 vCPU) in `eastus`
- [x] Repo skeleton, `.gitignore`, `Makefile`, README outcome statement
- [x] ADR stubs in `docs/adr/`
- [ ] GitHub milestones for Weeks 1–4

### Week 1 — Inference baseline (exit: API + smoke test)
- [x] 1. `config/model.yaml`: model, revision, licence, context, serving params
- [x] 2. `make serve` locally; verify `/v1/models`, `/health`, one chat call
- [x] 3. pytest smoke tests + versioned fixed prompt set; assert model/revision
- [x] 4. Pinned image + docs (setup, teardown, cache, limitations)
- [ ] 5. Exit gate: clean environment reproduces a valid response (laptop fresh clone + T4 on AKS)
- [x] AKS Lab 01: hand-built cluster + GPU pool + device plugin ([guide](learning/aks-lab-01-cluster.md))

### Week 2 — Kubernetes + GitOps (exit: reproducible release)
- [x] 6. Helm chart `charts/vllm`: GPU request, probes, securityContext, NetworkPolicy, SA, model-cache PVC ([guide](learning/step6-helm-chart.md))
- [ ] 7. CI: pytest, helm lint/template, kubeconform, policy check, Trivy, gitleaks, publish by digest, digest bump ([guide](learning/step7-ci.md)) — workflow written; first green run pending
- [ ] 8. Argo CD Application + AppProject (kind first, then AKS)
- [ ] 9. Terraform: AKS + GPU pool + budget alert; `make down` teardown
- [ ] 10. Exit gate: Git change → traceable release; previous version restorable

### Week 3 — Observe + harden (exit: dashboard + drill)
- [ ] 11. kube-prometheus-stack, vLLM ServiceMonitor, DCGM exporter
- [ ] 12. One Grafana dashboard (service → inference → resources)
- [ ] 13. SLOs + alert rules + runbook
- [ ] 14. Drills: pod deletion; failing release → health gate → rollback

### Week 4 — Measure + publish (exit: demo + career package)
- [ ] 15. k6/Locust at several concurrency levels → benchmark report
- [ ] 16. Four ADRs (vLLM vs KServe, model storage, GitOps boundary, scaling)
- [ ] 17. README polish + architecture diagram
- [ ] 18. Demo recording; confidentiality + git-history secret scan; make public

## If the schedule slips
Cut KServe, MLflow, canary, autoscaling first. Keep vLLM, K8s, GitOps, observability, tests, rollback, benchmark.
