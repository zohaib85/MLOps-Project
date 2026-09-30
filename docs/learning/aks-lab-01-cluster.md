# AKS Lab 01 — Build a GPU cluster by hand (then we codify it in Terraform)

**Goal:** understand every AKS choice by making it yourself with `az`, verify a pod can use the T4,
then tear down. Week 2 recreates the same cluster with Terraform.
**Time:** ~45 min (mostly waiting). **Cost:** roughly $0.60–0.70/hour while the GPU node runs —
check current prices on the Azure pricing page. Always finish with the teardown section.

Run everything in **WSL Ubuntu**.

---

## 0. Tools (one time)
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash   # Azure CLI
sudo az aks install-cli                                   # kubectl + kubelogin
az version -o table && kubectl version --client

az login --use-device-code          # opens a code you enter in your Windows browser
az account show -o table            # confirm the Pay-As-You-Go subscription is selected
```

## 1. Names in one place
```bash
export RG=rg-llm-lab LOC=eastus AKS=aks-llm-lab
export TAGS="project=llm-platform env=lab owner=zohaib"
```
Tags let you filter cost by project in Cost Management — do it from the first resource.

## 2. Resource group
```bash
az group create -n $RG -l $LOC --tags $TAGS -o table
```

## 2b. Pre-flight: are the VM sizes allowed, and is there quota?
New subscriptions often can't use every size in busy regions (`NotAvailableForSubscription`) —
that's a **SKU restriction**, separate from quota. Check both before waiting on a create:
```bash
for s in Standard_D2s_v4 Standard_NC4as_T4_v3; do
  az vm list-skus -l $LOC --size $s --all -o tsv \
    --query "[?name=='$s'].[name, join(',', restrictions[].reasonCode)]"
done                                   # second column must be empty
az vm list-usage -l $LOC -o table | grep -iE "DSv4 Family|NCASv3_T4|Total Regional vCPUs"
```
Seen on this project (eastus, new PAYG subscription, Sep 2026): most v5/v6 D- and B-series were
restricted; v4, v7 and ARM (`p`) sizes were allowed.

## 3. Create the cluster (system pool only) — ~5–8 min
```bash
az aks create -g $RG -n $AKS -l $LOC --tags $TAGS \
  --tier free \
  --nodepool-name system --node-count 1 --node-vm-size Standard_D2s_v4 \
  --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium \
  --enable-oidc-issuer --enable-workload-identity \
  --generate-ssh-keys -o table
```
| Flag | What it decides | Why this choice |
|---|---|---|
| `--tier free` | Control-plane SLA | Free = no SLA, $0. Fine for a lab; Standard adds the uptime SLA for production |
| `--nodepool-name system --node-count 1` | The **system pool** (CoreDNS, metrics-server, konnectivity) | Must always exist; 1 small node for a lab |
| `--node-vm-size Standard_D2s_v4` | 2 vCPU / 8 GB Intel VM | Enough RAM for Prometheus later. Chosen because newer v5/v6 sizes are **restricted for new subscriptions in eastus** (see 2b); fallback `Standard_D2as_v7` |
| `--network-plugin azure --network-plugin-mode overlay` | **Azure CNI Overlay**: pods get IPs from a private overlay, not your VNet | Doesn't burn VNet IPs; Microsoft's recommended default |
| `--network-dataplane cilium` | eBPF dataplane **and** the NetworkPolicy engine | We need NetworkPolicy in Week 2. Chosen at create time — hard to change later |
| `--enable-oidc-issuer --enable-workload-identity` | Pods can get Entra ID tokens without secrets | Needed later for secrets/Key Vault; free to enable now |

## 4. Connect and explore — this is the "AKS vs vanilla K8s" lesson
```bash
az aks get-credentials -g $RG -n $AKS --overwrite-existing
kubectl get nodes -o wide
kubectl get pods -n kube-system
kubectl get node -o jsonpath='{.items[0].metadata.labels}' | tr ',' '\n' | grep -E 'agentpool|mode|kubernetes.azure.com'
```
Now find where your VM actually lives:
```bash
NODE_RG=$(az aks show -g $RG -n $AKS --query nodeResourceGroup -o tsv); echo $NODE_RG
az resource list -g $NODE_RG -o table
```
You should see a **VM Scale Set**, a **load balancer**, a **public IP**, a **VNet**, NSG, managed identity.
👉 That `MC_...` group is owned by AKS. Look, don't touch — AKS reconciles it.

Things to notice:
- No control-plane nodes in `kubectl get nodes` — Azure runs them.
- `kube-system` has Azure-specific pods: `cilium-*`, `azure-cns`, `konnectivity-agent`, CSI drivers (`csi-azuredisk-node`, `csi-azurefile-node`).
- Node label `kubernetes.azure.com/mode=system`.

## 5. Add the GPU pool — ~5–10 min
```bash
az aks nodepool add -g $RG --cluster-name $AKS -n gpu --tags $TAGS \
  --mode User --node-count 1 \
  --node-vm-size Standard_NC4as_T4_v3 \
  --node-taints sku=gpu:NoSchedule \
  --labels workload=gpu -o table
```
| Flag | Why |
|---|---|
| `--mode User` | Only user pools can scale to 0 — the core of our cost control |
| `--node-taints sku=gpu:NoSchedule` | Nothing lands on the $0.5/h node unless it explicitly tolerates it |
| `--labels workload=gpu` | Lets GPU workloads *select* this pool (taint repels, label attracts — you need both) |

AKS installs the **NVIDIA driver** on GPU node images automatically.

## 6. Install the NVIDIA device plugin
The driver makes the GPU usable by the OS. The **device plugin** tells Kubernetes it exists
(`nvidia.com/gpu`) so the scheduler can hand it to pods.
```bash
kubectl apply -f deploy/lab/nvidia-device-plugin.yaml
kubectl -n gpu-resources get pods -o wide          # 1 pod, on the GPU node
kubectl get nodes -l workload=gpu -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.'nvidia\.com/gpu'
```
✅ `GPU` column shows `1`.

## 7. Prove a pod can use the GPU
```bash
kubectl apply -f deploy/lab/gpu-smoke-pod.yaml
kubectl get pod gpu-smoke -w        # Pending → ContainerCreating → Completed, then Ctrl+C
kubectl logs gpu-smoke              # nvidia-smi table showing "Tesla T4"
kubectl delete pod gpu-smoke
```
Note the **driver version** in the output — it decides which CUDA images work (remember why we chose `cu129`).

## 8. Pause or tear down (don't skip)
```bash
# Pause GPU only (keeps cluster; ~$0.09/h for the system node):
az aks nodepool scale -g $RG --cluster-name $AKS -n gpu --node-count 0

# Pause everything (deallocates all nodes; config kept):
az aks stop -g $RG -n $AKS         # resume: az aks start -g $RG -n $AKS

# Delete everything (the lab is disposable — Terraform rebuilds it in Week 2):
az group delete -n $RG --yes --no-wait
```
Deleting `$RG` also deletes the `MC_...` group automatically.

---

## Check your understanding (interview prep)
1. Why can the system pool never scale to 0, but the GPU pool can?
2. What's the difference between the GPU **driver** and the **device plugin**? Who installs each here?
3. Why do we need **both** a taint and a label on the GPU pool?
4. What would break if you edited the load balancer in the `MC_` group by hand?
5. Why is the network dataplane a create-time decision?

### Answers (try first, then expand)

<details><summary>1. System pool vs GPU pool scaling to 0</summary>

The system pool hosts cluster-critical pods — CoreDNS, konnectivity-agent (control-plane → node tunnel for
`logs`/`exec`), metrics-server, CNI/Cilium and CSI controllers. AKS requires ≥1 system pool with ≥1 node.
User pools run only your workloads, so 0 nodes just means "no capacity"; with autoscaler `min-count 0`
a pending GPU pod scales it 0 → 1. To stop *everything*, use `az aks stop`.
</details>

<details><summary>2. GPU driver vs device plugin</summary>

| | Driver | Device plugin |
|---|---|---|
| What | Kernel module + `libcuda` on the node OS | DaemonSet speaking the kubelet device-plugin API |
| Job | Makes the GPU usable (`nvidia-smi`, CUDA) | Advertises `nvidia.com/gpu`; hands a GPU to a container on allocation |
| Missing → | Nothing can use the GPU | GPU works, but K8s doesn't know — GPU pods stay Pending |
| Installed by | AKS GPU node image (+ NVIDIA container toolkit) | Us (`kubectl apply`) |

Node driver version caps the CUDA version containers can use → why we pinned `cu129`.
Alternatives: NVIDIA GPU Operator; AKS managed GPU (preview).
</details>

<details><summary>3. Taint and label</summary>

Taint **repels** everything without a toleration (cost + contention). A toleration only *permits*; the
label + `nodeSelector` **attracts**. GPU-requesting pods are steered by the resource anyway, but helpers
that don't request a GPU (device plugin, DCGM exporter) need the selector. AKS doesn't enable
`ExtendedResourceToleration`, so tolerations are explicit.
</details>

<details><summary>4. Editing the MC_ load balancer by hand</summary>

cloud-controller-manager reconciles the LB from `Service type=LoadBalancer` objects — manual edits get
overwritten or drift. The same LB usually provides **outbound SNAT** for nodes, so breaking it kills image
pulls / model downloads. Upgrades can recreate resources; manual edits are unsupported. Change it via
Service annotations or `az aks update` instead.
</details>

<details><summary>5. Dataplane is a create-time decision</summary>

It defines pod IP allocation (overlay vs VNet), routing, Service load-balancing (eBPF replaces kube-proxy)
and NetworkPolicy enforcement on every node. Without a policy engine, NetworkPolicies are accepted but
silently not enforced. Some one-way, disruptive migrations exist (e.g. enabling Cilium on Overlay);
pod CIDR stays fixed. In practice: choose once or rebuild.
</details>
