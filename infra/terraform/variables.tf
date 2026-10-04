variable "location" {
  description = "Azure region. GPU quota (NCASv3_T4) was approved here."
  type        = string
  default     = "eastus"
}

variable "name_prefix" {
  description = "Prefix for resource names: rg-<prefix>, aks-<prefix>."
  type        = string
  default     = "llm-lab"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.name_prefix))
    error_message = "Use 3-21 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "kubernetes_version" {
  description = "AKS Kubernetes version. null = AKS default for the region."
  type        = string
  default     = null
}

variable "system_vm_size" {
  description = "System pool VM size. Newer v5/v6 sizes were NotAvailableForSubscription in eastus (Lab 01)."
  type        = string
  default     = "Standard_D2s_v4"
}

variable "gpu_vm_size" {
  description = "GPU pool VM size (1x NVIDIA T4 16GB, 4 vCPU)."
  type        = string
  default     = "Standard_NC4as_T4_v3"
}

variable "gpu_node_count" {
  description = "Initial GPU node count. Later scaling is done with `make gpu-on` / `make gpu-off` (ignored by Terraform)."
  type        = number
  default     = 0

  validation {
    condition     = var.gpu_node_count >= 0 && var.gpu_node_count <= 1
    error_message = "Quota allows one NC4as_T4_v3 node (4 vCPU): use 0 or 1."
  }
}

variable "api_server_authorized_ip_ranges" {
  description = "CIDRs allowed to reach the Kubernetes API server, e.g. [\"203.0.113.7/32\"] (your public IP)."
  type        = list(string)

  validation {
    condition     = length(var.api_server_authorized_ip_ranges) > 0 && !contains(var.api_server_authorized_ip_ranges, "0.0.0.0/0")
    error_message = "Provide at least one CIDR, and never 0.0.0.0/0 — the API server must not be open to the internet."
  }
}

variable "budget_amount" {
  description = "Monthly budget (in the subscription's billing currency) for resources tagged project=llm-platform."
  type        = number
  default     = 50
}

variable "budget_contact_email" {
  description = "Email that receives budget alerts."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_contact_email))
    error_message = "Must be a valid email address."
  }
}

variable "tags" {
  description = "Extra tags merged onto every resource."
  type        = map(string)
  default     = {}
}
