# Build Plan — Production-Grade LLM Inference Platform on Kubernetes

Build window: 24 Sep – 21 Oct 2026 · ~8–10 h/week · personal learning project.

## Decisions (kickoff)

| Area | Choice | Notes |
|---|---|---|
| Cloud / GPU | Azure AKS, minimal, region `eastus` | Free-tier control plane; 1× small system node; 1× T4 GPU user pool scaled to 0 when idle |
| GPU SKU | `Standard_NC4as_T4_v3` (T4 16 GB) | Needs "Standard NCASv3_T4 Family" vCPU quota ≥ 4 — **request now** |
| Model | Small Apache-2.0 instruct model (e.g. Qwen2.5-1.5B-Instruct) | T4 has no bf16 → `--dtype float16`; pin HF revision hash |
| Inference | Official `vllm/vllm-openai` image, pinned by digest | We don't rebuild vLLM |
| CI | GitHub Actions | Public runs are reviewer-visible evidence |
| Registry | GHCR | Free, OCI, no extra Azure resource |
| Our image | Eval/load/smoke harness (`app/`) | Built, scanned, published by digest in CI |
| GitOps | Argo CD, same repo, `deploy/` path | CI commits digest bump; CI never holds cluster creds |
| Gateway | vLLM `--api-key` + ingress-nginx rate limits | Minimal; Envoy Gateway deferred |
| Local dev | Docker + kind, CPU / tiny model or mock | GPU only for integration + evidence runs |

## Steps

### Step 0 — Kickoff
- [ ] Upgrade subscription to Pay-As-You-Go (free trial has 0 GPU quota) + budget alert
- [ ] Register resource providers
- [ ] Request Azure GPU quota (NCASv3_T4, 4 vCPU) in `eastus`
- [ ] Repo skeleton, `.gitignore`, `Makefile`, README outcome statement
- [ ] ADR stubs in `docs/adr/`
- [ ] GitHub milestones for Weeks 1–4

### Week 1 — Inference baseline (exit: API + smoke test)
- [ ] 1. `config/model.yaml`: model, revision, licence, context, serving params
- [ ] 2. `make serve` locally; verify `/v1/models`, `/health`, one chat call
- [ ] 3. pytest smoke tests + versioned fixed prompt set; assert model/revision
- [ ] 4. Pinned image + docs (setup, teardown, cache, limitations)
- [ ] 5. Exit gate: clean environment reproduces a valid response

### Week 2 — Kubernetes + GitOps (exit: reproducible release)
- [ ] 6. Helm chart `charts/vllm`: GPU request, probes, securityContext, NetworkPolicy, SA, model-cache PVC
- [ ] 7. CI: pytest, helm lint/template, kubeconform, policy check, Trivy, gitleaks, publish by digest, digest bump
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
