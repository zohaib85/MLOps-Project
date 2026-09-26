# AKS for Kubernetes Engineers — Learning Notes

What AKS changes relative to "plain" Kubernetes, scoped to what this project uses.
Each topic lists where in the build it becomes hands-on.

## 1. Mental model: what Azure manages vs what you manage

| Concern | AKS | You |
|---|---|---|
| API server, etcd, scheduler, controller-manager | Managed, invisible (no control-plane nodes) | Pick tier: **Free** (no SLA — ours) / Standard / Premium |
| Worker nodes | VM Scale Sets, one per **node pool** | Size, count, taints, labels, upgrades |
| Node infra (VMSS, NICs, disks, LB, public IPs) | Lives in auto-created **`MC_<rg>_<cluster>_<region>`** resource group | Don't edit it by hand — AKS will fight you |
| K8s version + node OS image | Offers versions; optional auto-upgrade channels | Choose version + upgrade policy |

## 2. Node pools (hands-on: Week 2, Terraform)
- **System pool**: runs CoreDNS, metrics-server, konnectivity etc. Must always have ≥1 node. Ours: 1× small VM.
- **User pool**: your workloads. Ours: GPU pool `Standard_NC4as_T4_v3`, **can scale to 0** (system pools cannot).
- Taint the GPU pool (`sku=gpu:NoSchedule`) so only the vLLM pod (with a toleration) lands there — you don't want CoreDNS on a $0.5/h node.
- Terraform: `azurerm_kubernetes_cluster` (includes system pool) + `azurerm_kubernetes_cluster_node_pool` (GPU pool).

## 3. GPUs on AKS (hands-on: Week 2–3)
- GPU node images ship with the **NVIDIA driver** preinstalled by default.
- You still need the **NVIDIA device plugin** DaemonSet so pods can request `nvidia.com/gpu: 1`.
- Alternative: NVIDIA GPU Operator (skip AKS driver install) — more moving parts; we note it in an ADR.
- GPU metrics: DCGM exporter (Week 3).

## 4. Networking (hands-on: Week 2)
- CNI options: kubenet (being retired), Azure CNI (pod IPs from VNet), **Azure CNI Overlay** (pods on private overlay — ours).
- NetworkPolicy enforcement must be chosen at cluster create: Azure NPM, Calico, or **Cilium** (ours: Azure CNI powered by Cilium).
- `Service type=LoadBalancer` → Azure Standard Load Balancer + public IP (costs money, remember teardown).
- Ingress: self-installed ingress-nginx (ours, portable) vs the **application routing add-on** (managed nginx).

## 5. Identity & access (hands-on: Week 2)
- `az aks get-credentials` writes kubeconfig. With **Entra ID integration**, auth goes through `kubelogin`.
- **Azure RBAC for Kubernetes** lets Entra users/groups get K8s roles via Azure role assignments.
- Cluster uses **managed identities** (control plane identity + kubelet identity for pulling images/disks).
- **Workload Identity**: pods get Azure tokens via federated OIDC — no secrets in the cluster. Replaces old pod-identity.
- GitOps boundary: GitHub Actions never gets kubeconfig; Argo CD inside the cluster pulls from Git.

## 6. Storage (hands-on: Week 2, model cache)
- CSI drivers are built in. Default StorageClasses: `managed-csi` (Azure Disk, RWO), `azurefile-csi` (RWX).
- Model cache PVC on Azure Disk: faster restarts (no re-download from Hugging Face). ADR: disk vs Azure Files vs baked image.

## 7. Operations & cost (hands-on: Week 3–4)
- `az aks stop` / `az aks start`: deallocates all nodes, keeps config. Cheapest idle state short of destroy.
- `az aks nodepool scale --node-count 0` on the GPU pool between sessions.
- Cluster autoscaler per pool (`min_count` / `max_count`).
- Upgrades: `az aks upgrade` (control plane + nodes), node-image upgrades, auto-upgrade channels, maintenance windows.
- Azure-native observability (Container Insights, Managed Prometheus/Grafana) vs self-hosted kube-prometheus-stack (ours) — compare in an ADR.

## Handy commands
```bash
az aks list -o table
az aks get-credentials -g <rg> -n <cluster>
az aks nodepool list -g <rg> --cluster-name <cluster> -o table
az aks nodepool scale -g <rg> --cluster-name <cluster> -n gpu --node-count 0
az aks get-upgrades -g <rg> -n <cluster> -o table
az aks stop|start -g <rg> -n <cluster>
```
