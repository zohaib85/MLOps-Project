terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.8"
    }
  }

  # Local state: single operator, short-lived lab environment. To share state, add an
  # `azurerm` backend (storage account + container) — see docs/learning/step9-terraform.md.
}

provider "azurerm" {
  features {}
  # v5 default is "none". Providers were registered by hand in Step 0; keep it explicit.
  resource_provider_registrations = "none"
  # subscription_id comes from ARM_SUBSCRIPTION_ID (the Makefile exports it from `az account show`).
}
