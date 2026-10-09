locals {
  # AKS propagates these to the node resources in the MC_ group, so the project budget sees VM spend too.
  tags = merge({
    project    = "llm-platform"
    env        = "lab"
    managed_by = "terraform"
  }, var.tags)
}

data "azurerm_subscription" "current" {}

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = "aks-${var.name_prefix}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  dns_prefix          = var.name_prefix
  kubernetes_version  = var.kubernetes_version
  tags                = local.tags

  sku_tier = "Free" # no control-plane SLA; Standard adds the uptime SLA for production

  # Kubernetes RBAC (the provider default, stated explicitly; Trivy AZU-0042 checks for it).
  role_based_access_control_enabled = true

  # Pods get Entra ID tokens via federated OIDC — no secrets in the cluster.
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  automatic_upgrade_channel = "patch"     # stay on supported patch releases
  node_os_upgrade_channel   = "NodeImage" # weekly node image (OS security) updates

  # Required in azurerm v5. Manual = classic node pools (Auto = Node Auto Provisioning / Karpenter).
  node_provisioning_profile {
    mode = "Manual"
  }

  # System pool: CoreDNS, konnectivity, metrics-server — and Argo CD / monitoring for this lab.
  default_node_pool {
    name                        = "system"
    vm_size                     = var.system_vm_size
    node_count                  = 1
    temporary_name_for_rotation = "systemtmp"
    tags                        = local.tags

    upgrade_settings {
      max_surge = "10%" # rounds up to 1 extra D2s_v4 during upgrades
    }
  }

  identity {
    type = "SystemAssigned"
  }

  # Azure CNI Overlay + Cilium: pods don't consume VNet IPs; Cilium enforces NetworkPolicy.
  # Create-time decisions (see Lab 01, question 5).
  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    load_balancer_sku   = "standard"
  }

  # Only these CIDRs can reach the API server (kubectl, helm, Argo CD UI port-forward).
  api_server_access_profile {
    authorized_ip_ranges = var.api_server_authorized_ip_ranges
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  name                  = "gpu"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = var.gpu_vm_size
  mode                  = "User" # only user pools can scale to zero
  node_count            = var.gpu_node_count
  gpu_driver            = "Install" # AKS installs the NVIDIA driver; device plugin is ours (deploy/lab)
  tags                  = local.tags

  node_taints = ["sku=gpu:NoSchedule"] # repel everything that doesn't tolerate it
  node_labels = { workload = "gpu" }   # let GPU workloads select this pool

  # Quota is exactly one GPU node: upgrade in place (take the node down) instead of adding a
  # surge node. In azurerm v5 max_unavailable conflicts with max_surge — setting it implies no surge.
  upgrade_settings {
    max_unavailable = "1"
  }

  lifecycle {
    # Day-to-day scaling (0 <-> 1) happens with `make gpu-on/gpu-off`, not Terraform.
    ignore_changes = [node_count]
  }
}

# Budget on everything tagged project=llm-platform — including VMs in the AKS-managed MC_ group,
# which a resource-group budget on rg-llm-lab would miss.
resource "azurerm_consumption_budget_subscription" "project" {
  name            = "budget-${var.name_prefix}"
  subscription_id = data.azurerm_subscription.current.id
  amount          = var.budget_amount
  time_grain      = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  filter {
    tag {
      name   = "project"
      values = [local.tags.project]
    }
  }

  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.budget_contact_email]
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.budget_contact_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.budget_contact_email]
  }

  lifecycle {
    ignore_changes = [time_period] # start date is set once at creation
  }
}
