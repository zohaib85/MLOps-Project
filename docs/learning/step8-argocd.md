# Step 8 — GitOps with Argo CD (on kind first)

**Goal:** the cluster deploys itself from Git. A merged commit becomes a release; reverting the
commit is the rollback; manual `kubectl` changes are undone automatically.

## Mental model: push vs pull
```
Push (classic CD):  CI ──kubectl/helm with cluster credentials──► cluster
Pull (GitOps):      CI ──commit──► Git ◄──watches── Argo CD (inside the cluster) ──applies──► cluster
```
With pull, **CI never holds cluster credentials** — a compromised CI runner can't deploy anything;
it can only open a commit that still goes through review. That's the security boundary for ADR-0003.

## What we added
| File | Role |
|---|---|
| `deploy/argocd/project.yaml` | **AppProject** — guardrails: only this repo, only namespace `llm`, only these resource kinds |
| `deploy/argocd/app-kind.yaml` | **Application** — render `charts/vllm` with kind values from branch `main`; auto-sync, prune, self-heal |
| `deploy/argocd/app-aks.yaml` | Same for AKS (step 10) — includes the CI-owned `harness-image.yaml` |
| `tests/unit/test_argocd.py` | Value files exist and stay in the repo; apps stay within project guardrails; every kind the chart renders is allowed by the project |

| Sync option | Meaning |
|---|---|
| `automated` | Apply changes as soon as Git changes (polls every ~3 min by default) |
| `prune: true` | Delete resources that were removed from Git |
| `selfHeal: true` | Undo manual changes in the cluster (drift) |
| `CreateNamespace=true` | Create `llm` if missing |

## Prerequisite
Argo CD reads branch **`main`**, so **PR #2 must be merged first** (otherwise the chart isn't on `main` yet).
Merging also triggers CI on `main`: the harness image is pushed to GHCR and `bump` commits its digest.

## Run it (kind)
```bash
cd ~/MLOps-Project && git checkout main && git pull
kubectl config use-context kind-llm-platform

helm uninstall llm -n llm        # hand the release over: Argo CD will own it from now on
make kind-load                   # Argo can't pull our local image; load it into kind
make argocd-install              # pinned Argo CD v3.5.3 (~2 min)
make argocd-apps                 # AppProject + Application
make argocd-status               # wait for SYNC=Synced, HEALTH=Healthy
```
UI: `make argocd-ui` → https://localhost:8080 (accept the self-signed cert), user `admin`,
password from `make argocd-password`. Click `llm-kind` to see the resource tree.

## Experiments (the learning part)
**1. Self-heal (drift correction)**
```bash
kubectl -n llm delete service llm-vllm          # "accidental" manual change
kubectl -n llm get svc -w                       # Argo CD recreates it within seconds
kubectl -n llm label deploy llm-vllm hacked=yes --overwrite
kubectl -n llm get deploy llm-vllm --show-labels   # label removed again by self-heal
```

**2. A release = a Git commit** (via PR, like production)
```bash
git checkout -b demo/faster-startup
sed -i 's/startupDelaySeconds: 20/startupDelaySeconds: 5/' deploy/envs/kind/values.yaml
git commit -am "kind: faster simulated model load" && git push -u origin demo/faster-startup
# open PR → CI green → merge → within ~3 min (or click "Refresh" in the UI) Argo CD syncs
kubectl -n llm get deploy llm-vllm -o jsonpath='{.spec.template.spec.containers[0].env}' | tr ',' '\n' | grep -A1 DELAY
```

**3. Rollback = revert the commit**
```bash
git checkout main && git pull && git revert --no-edit HEAD && git push   # or revert via a PR
# Argo CD syncs back to 20s. History: UI → llm-kind → History and Rollback
```

**4. Guardrails** — try to make the app deploy somewhere the project forbids:
```bash
kubectl -n argocd patch application llm-kind --type merge -p '{"spec":{"destination":{"namespace":"kube-system"}}}'
make argocd-status    # sync fails: destination not permitted by AppProject llm-platform
kubectl apply -f deploy/argocd/app-kind.yaml   # restore
```

## Interview angles
- **Why GitOps for model serving?** Every model/config change is a reviewed commit: who, what, when, and
  one-command rollback. The running state is always "what's in `main`".
- **Why `selfHeal`?** Hot-fixes with `kubectl` silently drift from Git; the next deploy would undo them anyway.
  Self-heal makes Git the only way to change prod.
- **What does the AppProject add?** Least privilege for deployments: even a bad Application can't deploy to
  other namespaces, pull from other repos, or create cluster-wide resources.
- **Push vs pull trade-off:** pull adds an in-cluster component to operate (Argo CD) but removes cluster
  credentials from CI and gives continuous drift detection.

## Clean up
`make kind-down` removes the whole cluster (Argo CD included).
