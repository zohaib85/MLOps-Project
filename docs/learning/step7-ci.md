# Step 7 — CI with GitHub Actions

**Goal:** every change is tested, validated, scanned and (on `main`) published as an immutable
image — and CI never touches the cluster.

## In plain English
**Every time code changes, a robot borrows a fresh computer, runs a checklist of inspections, and only lets
the change become a release if every inspection passes.**

Think of a factory: the PR is a product arriving for inspection; CI is a team of inspectors with pass/reject
stamps; `main` is the warehouse that only accepts fully-stamped products; on merge, shipping labels the box with
an unchangeable serial number (the image digest) and writes it in the logbook (Git); Argo CD is the delivery truck
that reads the logbook and delivers exactly that box to the cluster.

| Inspector | Question it answers |
|---|---|
| **test** | Is the code tidy, and does it do what we say it does? |
| **manifests** | Would our Kubernetes files be valid, and do they follow our safety rules? |
| **secrets** | Did anyone ever commit a password or key — even one deleted later? |
| **image** | Does the container build, actually work, and contain no known *fixable* security holes? |

On a **PR**: inspect only, never publish. On **merge to `main`**: inspect again, then **publish** the image by
digest and **record** the digest in Git (`deploy/envs/aks/harness-image.yaml`) — the release receipt.

Rules behind the design: same checks locally and in CI (`make lint test`) · only reviewed code becomes a
release · labels that can't be swapped (digests) · helpers pinned exactly (SHA-pinned actions) · each job gets
only the keys it needs · the robot never holds the keys to the cluster.

**Worked example (Oct 2026):** the `image` inspector rejected the build on CVE-2026-103111 in `libpcre2`
(OS package from the base image; fix available in Debian). The base image hadn't been rebuilt yet, so the
Dockerfile now applies Debian security updates; ignoring the CVE was rejected because a fix existed.

## Pipeline (`.github/workflows/ci.yml`)
```
PR / push ──► test ─────────┐
          ├─► manifests ────┼──► image ──(main only)──► push to GHCR by digest ──► bump (commit digest to Git)
          └─► secrets       │
```
| Job | What blocks a bad change | Run locally |
|---|---|---|
| **test** | ruff lint + format, `helm lint --strict` (kind + aks), generated-values drift, 23 unit tests | `make lint test` |
| **manifests** | Rego policy unit tests; each env rendered → **kubeconform** (K8s schema) + **conftest** (our policy); **Trivy** misconfiguration scan of rendered manifests + Dockerfile | `make policy-test validate` |
| **secrets** | **gitleaks** over the *whole* Git history (not just the diff) | `gitleaks git .` |
| **image** | Build harness image → run the mock + smoke suite *inside the built image* → **Trivy** CVE scan (fail on fixable HIGH/CRITICAL). On `main`: push `ghcr.io/<owner>/llm-platform-harness:sha-<commit>` with SBOM + provenance | `make harness-image` |
| **bump** | On `main`: writes the pushed digest to `deploy/envs/aks/harness-image.yaml` and commits it | — |

## Policy as code (`policy/kubernetes.rego`)
Denies any workload that: runs as root · allows privilege escalation · has a writable root FS ·
keeps Linux capabilities · uses an image not pinned by digest · uses `:latest` · has no memory limit ·
(Deployments) lacks readiness/liveness probes · mounts a SA token · is exposed via a public
LoadBalancer/NodePort. Helm test hooks only **warn**. The policy has its own tests (`conftest verify`).

**Why both chart unit tests *and* policy?** Unit tests check *our chart* does what we intend.
Policy checks *any manifest* meets the platform's rules — it would catch a future chart or a copy-pasted
manifest too. That's the platform-team view.

## Design choices to explain in an interview
| Choice | Why |
|---|---|
| Actions pinned to **commit SHAs** (`@3d3c42e…  # v7.0.1`) | A tag can be moved to malicious code; a SHA can't (cf. the tj-actions incident) |
| `permissions: contents: read` by default; `packages: write` / `contents: write` only on the jobs that need them | Least privilege for the CI token |
| Image tested **after** build, inside the image | Catches "works on my machine" packaging bugs (missing files, wrong user, unwritable paths) |
| Push only from `main`, by **digest**, with SBOM + provenance | Immutable, traceable artifact; PRs build + scan but publish nothing |
| CI-owned file (`harness-image.yaml`) separate from human-edited values | No merge conflicts or comment-mangling; Git history = audit log of every release |
| **No cluster credentials in CI** | Argo CD (step 8) pulls desired state from Git — a compromised runner can't deploy |

## Known follow-ups
- GHCR packages start **private**: make `llm-platform-harness` public (GitHub → Packages → settings) or add an
  imagePullSecret before AKS pulls it for `helm test`.
- vLLM's image is third-party and pinned manually in `config/model.yaml`; bumping it is a reviewed PR, not CI.
