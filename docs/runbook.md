# Runbook — LLM inference platform

Every alert in `charts/vllm/templates/prometheusrule.yaml` links to a section here
(`runbook_url: …/runbook.md#<alertname in lowercase>`; `tests/unit/test_observability.py` enforces it).
Each section is: **what it means → first look → likely causes → fix → verify.**

**Before anything else:**
```bash
kubectl config current-context           # right cluster? (aks-llm-lab / kind-llm-platform)
kubectl -n llm get pods -o wide          # Running? Ready? which node? restarts?
kubectl -n argocd get applications       # Synced/Healthy? (a bad Git change shows here first)
helm -n llm history llm                  # helm installs only; Argo CD history: argocd app history
```
Dashboard: Grafana → *LLM inference — service, engine, resources* (`make grafana-ui`).
Alerts: `make prom-ui` → http://localhost:9090/alerts.

---

## LLMEndpointDown
**Meaning:** Prometheus has had no healthy `/metrics` target for the inference Service for 5 minutes.
To clients this usually means the API is down too.

**First look:** `kubectl -n llm get pods`, `kubectl -n llm describe pod -l app.kubernetes.io/name=vllm`,
`kubectl -n llm logs deploy/llm-vllm --tail=100`.

| Symptom | Likely cause | Fix |
|---|---|---|
| Pod `Pending` | GPU pool at 0 nodes | see [LLMPodPending](#llmpodpending) |
| Pod `Running`, not Ready, logs show model loading | Still starting (cold cache: download + load ≈ minutes) | Wait for the startup probe; check the model-cache PVC is bound |
| `CrashLoopBackOff` | Bad args/image in the last release, CUDA OOM | Roll back (below) |
| Pod Ready but target down | NetworkPolicy blocks the monitoring namespace, or the ServiceMonitor doesn't select the Service | `kubectl -n llm get networkpolicy -o yaml`; Prometheus UI → Status → Targets |

**Roll back (GitOps):** `git revert <bad commit> && git push` → Argo CD syncs the previous state.
Emergency only: `argocd app rollback llm-aks <id>` (auto-sync must be paused first, otherwise Git wins again).

**Verify:** target `UP` in Prometheus; `make smoke BASE_URL=…` passes.

## LLMErrorBudgetFastBurn
**Meaning:** the 5xx ratio on `/v1/chat/completions` is above 14.4× the error budget over both the
last 1 h and 5 m. With a 99% SLO that's a 14.4% error ratio: at this rate, 2% of the monthly budget
is gone in one hour. Pages straight away.

**First look:** dashboard row *Service* → "Requests by status class"; server logs for tracebacks;
did a release just happen? (`kubectl -n argocd get applications`, Git log of `deploy/` and `charts/`).

| Likely cause | Fix |
|---|---|
| Bad release (new args, image, model revision) | `git revert` → Argo CD sync (see LLMEndpointDown) |
| Engine errors under load (CUDA OOM, request too long for `max_model_len`) | Check logs; reduce `gpu_memory_utilization` / `max_num_seqs`, or limit `max_tokens` at the gateway |
| Drill: `MOCK_ERROR_RATE` set on kind | Remove it from the env values |

**Verify:** 5m error ratio back near 0; the alert resolves after the 1h window recovers.

## LLMLatencyP95High
**Meaning:** p95 end-to-end latency has been above the objective (5 s) for 10 minutes.

**First look:** *Inference* row: is "Requests in the engine → waiting" above 0 (queueing)?
Is TTFT high (prefill/queue) or is generation slow (long outputs)? *Resources* row: GPU at 100%?

| Likely cause | Fix |
|---|---|
| More concurrency than one T4 can serve | Expected beyond the benchmark knee (Week 4 report: `docs/benchmark.md`); rate-limit at the gateway |
| Long `max_tokens` requests | Cap `max_tokens`; latency scales with tokens generated |
| KV cache full → preemptions | See [LLMKVCacheSaturated](#llmkvcachesaturated) |
| Drill: `MOCK_LATENCY_S` set on kind | Remove it |

**Verify:** p95 stat tile green; no requests waiting.

## LLMQueueBacklog
**Meaning:** more than 5 requests have waited for an engine slot for 5 minutes — demand exceeds what
the batch can hold (`max_num_seqs`, KV-cache size).

**First look:** "Requests in the engine" and "KV cache usage" panels; request rate vs the benchmark.

**Fix:** reduce load (rate limits) or add capacity (a second GPU node — out of scope for this lab:
quota is one T4). Short spikes are fine; a sustained queue means the SLO will be missed.

**Verify:** waiting drops to 0.

## LLMKVCacheSaturated
**Meaning:** over 90% of the GPU KV-cache blocks have been in use for 10 minutes. vLLM starts
preempting (pausing and recomputing) requests, so latency climbs.

**First look:** KV cache panel, waiting requests, and `vllm:num_preemptions_total` in Prometheus.

**Fix:** fewer concurrent long requests (lower `max_num_seqs`, cap `max_tokens`), a shorter
`max_model_len`, or more GPU memory for the cache (raise `gpu_memory_utilization` carefully — the T4
has 16 GiB and the 0.5B model needs ~1 GiB of weights).

**Verify:** usage below 90%; preemption counter flat.

## LLMPodRestarting
**Meaning:** the server container restarted more than twice in 15 minutes.

**First look:**
```bash
kubectl -n llm get pod -l app.kubernetes.io/name=vllm -o jsonpath='{.items[*].status.containerStatuses[*].lastState}'
kubectl -n llm logs deploy/llm-vllm --previous --tail=100
```

| `lastState.terminated.reason` | Cause | Fix |
|---|---|---|
| `OOMKilled` | Container memory limit too low (host RAM, not GPU) | Raise `resources.limits.memory` in `deploy/envs/aks/values.yaml` |
| `Error` + CUDA OOM in logs | GPU memory: `gpu_memory_utilization` too high, or another process holds the GPU | Lower it in `config/model.yaml` → `make values` → PR |
| Liveness probe failures in events | Engine stuck or overloaded | Check load; probe timings in `charts/vllm/values.yaml` |

**Verify:** restart count stops rising (dashboard "Container restarts").

## LLMPodPending
**Meaning:** the inference pod has been `Pending` for 10 minutes — it can't be scheduled.

**First look:** `kubectl -n llm describe pod -l app.kubernetes.io/name=vllm` → *Events*.

| Event message | Cause | Fix |
|---|---|---|
| `0/1 nodes are available: … untolerated taint` / `didn't match node selector` | GPU pool scaled to 0 | `make gpu-on` (≈ 5 min for the node + driver) |
| `Insufficient nvidia.com/gpu` | Node exists but GPU not advertised (device plugin / driver not ready) or old pod still holds it | `kubectl describe node -l workload=gpu` → Allocatable; wait for the driver; Recreate strategy should free it |
| `pod has unbound immediate PersistentVolumeClaims` | Model-cache PVC not provisioned | `kubectl -n llm get pvc`; check `storageClassName` |
| Quota error in cluster-autoscaler / node pool scale fails | Regional vCPU quota | `make preflight` |

**Verify:** pod `Running` and Ready; LLMEndpointDown clears.
