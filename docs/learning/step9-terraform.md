# Step 9 — Terraform for AKS (Lab 01, as code)

**Goal:** one command creates the exact cluster you built by hand in Lab 01 — plus a budget —
and one command removes every billable resource.

## What Terraform manages (`infra/terraform/`)
| Resource | Lab 01 equivalent | Notes |
|---|---|---|
| `azurerm_resource_group.this` | `az group create` | `rg-llm-lab`, tagged `project=llm-platform` |
| `azurerm_kubernetes_cluster.this` | `az aks create` | Free tier · system pool `Standard_D2s_v4` ×1 · CNI Overlay + Cilium · OIDC + Workload Identity · **API server limited to your IP** · auto-upgrade `patch` + weekly node images |
| `azurerm_kubernetes_cluster_node_pool.gpu` | `az aks nodepool add` | `Standard_NC4as_T4_v3`, **0 nodes by default**, taint `sku=gpu:NoSchedule`, label `workload=gpu`, AKS installs the driver |
| `azurerm_consumption_budget_subscription.project` | (portal budget) | 50/80% actual + 100% forecast alerts for everything tagged `project=llm-platform` |

Files: `versions.tf` (pins Terraform ≥1.9, azurerm `~> 5.8`) · `variables.tf` (with validation) ·
`main.tf` · `outputs.tf` · `terraform.tfvars.example`.

## Decisions worth explaining in an interview
| Decision | Why |
|---|---|
| GPU pool starts at **0 nodes**; `make gpu-on/off` scales it; Terraform `ignore_changes = [node_count]` | The expensive node only exists during GPU sessions. Terraform owns the *shape*, day-to-day *scale* is operational — and doesn't create drift |
| GPU `upgrade_settings { max_unavailable = "1" }` (no surge) | Quota is exactly one T4 node — a surge node would fail. Upgrade in place instead. (azurerm v5 rejects setting `max_surge` together with it — caught by `terraform validate`) |
| `api_server_access_profile.authorized_ip_ranges` (validation forbids `0.0.0.0/0`) | The control plane isn't reachable from the whole internet |
| Budget at **subscription scope filtered by tag**, not on the resource group | VMs, disks and LBs live in the AKS-managed `MC_` group; a budget on `rg-llm-lab` would miss most of the spend. AKS propagates tags to node resources |
| `node_provisioning_profile { mode = "Manual" }` | **Required in azurerm v5** — v4 tutorials omit it and fail. `Auto` = Node Auto Provisioning (Karpenter) |
| `resource_provider_registrations = "none"` | v5 default; providers were registered once in Step 0 — Terraform shouldn't need subscription-wide rights |
| Local state | One operator, disposable environment. For a team: `azurerm` backend (storage account, state locking via blob lease) |
| `make preflight` before `apply` | Catches Lab 01's failures (not logged in, SKU restricted, quota short) *before* a 10-minute apply fails |

## Prerequisites
```bash
# Terraform CLI (WSL)
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install -y terraform jq
terraform version

az login --tenant <tenant-id>          # browser flow (device code is blocked by Security Defaults)
az account show -o table
```

## Run it
```bash
cd ~/MLOps-Project && git pull
make tf-check                                     # fmt + validate, no Azure needed

cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
curl -s https://ifconfig.me; echo                # your public IP → api_server_authorized_ip_ranges ["x.x.x.x/32"]
nano infra/terraform/terraform.tfvars            # set IP + budget email

make preflight                                   # ✔ login, SKUs allowed, quota
make infra-plan                                  # READ the plan: 4 resources to add, 0 to destroy
make infra-up                                    # ~8-10 min; ends with kubectl context = aks-llm-lab
kubectl get nodes -o wide                        # 1 system node; GPU pool exists with 0 nodes
```
Cost while idle (GPU at 0): roughly the system node only. **Tear down when you stop for the day.**

**Commit the lock file once:** your first `terraform init` creates `infra/terraform/.terraform.lock.hcl`
(provider checksums from the official registry). Commit it — every later `init` (yours and CI's) then
verifies it downloads exactly the same provider build. It wasn't committed earlier because the version
used for validation in the build session was compiled from source, so its checksums differ from the registry.

## Teardown
```bash
make infra-down          # destroys cluster, GPU pool, budget, resource group (+ AKS deletes the MC_ group)
az group list -o table   # verify rg-llm-lab and MC_rg-llm-lab_* are gone
```

## Things to try (learning)
1. `make infra-plan` twice in a row → second plan shows **no changes** (idempotence).
2. Change `budget_amount` in `terraform.tfvars` → plan shows an **in-place update** (`~`).
3. Change `name_prefix` → plan shows **destroy and recreate** (`-/+`). Read why (names force replacement).
4. `make gpu-on` → `make infra-plan` → still no changes (`ignore_changes` at work). `make gpu-off`.
5. Set `api_server_authorized_ip_ranges = ["0.0.0.0/0"]` → plan fails on the validation rule.
6. `terraform -chdir=infra/terraform state list` / `state show azurerm_kubernetes_cluster.this`.

## Self-check
- Why does the budget filter on a tag instead of a resource group?
- What happens if you scale the GPU pool with `az` and *don't* have `ignore_changes`?
- What's in `terraform.tfstate`, and why is it git-ignored (hint: it contains the kubeconfig)?
- Plan vs apply: why save the plan to a file (`-out=tfplan`) and apply that file?
