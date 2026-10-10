#!/usr/bin/env bash
# Pre-flight checks before `terraform apply` — the Lab 01 failures, caught up front:
#   logged in? right subscription? VM sizes offered to this subscription (SKU restrictions)?
#   enough vCPU quota per family and in the region?
# Usage: scripts/azure_preflight.sh [location] [system_vm_size] [gpu_vm_size]
set -euo pipefail

LOC=${1:-eastus}
SYS=${2:-Standard_D2s_v4}
GPU=${3:-Standard_NC4as_T4_v3}
fail=0
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$*"; fail=1; }

echo "Azure pre-flight ($LOC)"

if ! az account show -o none 2>/dev/null; then
  bad "not logged in — run: az login --tenant <tenant-id>"; exit 1
fi
ok "subscription: $(az account show --query '[name, id]' -o tsv | paste -sd ' ')"

for size in "$SYS" "$GPU"; do
  sku=$(az vm list-skus -l "$LOC" --size "$size" --all -o json \
        --query "[?name=='$size'] | [0].{family:family, restrictions:restrictions[].reasonCode, vcpus:capabilities[?name=='vCPUs'].value | [0]}")
  if [ "$sku" = "null" ] || [ -z "$sku" ]; then bad "$size: not offered in $LOC"; continue; fi
  family=$(jq -r .family <<<"$sku"); vcpus=$(jq -r .vcpus <<<"$sku")
  if [ "$(jq '.restrictions | length' <<<"$sku")" != "0" ]; then
    bad "$size: restricted ($(jq -r '.restrictions | join(",")' <<<"$sku")) — pick another size or region"
    continue
  fi
  usage=$(az vm list-usage -l "$LOC" -o json --query "[?name.value=='$family'] | [0]")
  free=$(jq -r '(.limit|tonumber) - (.currentValue|tonumber)' <<<"$usage")
  if [ "$free" -ge "$vcpus" ]; then ok "$size: allowed; family $family has $free vCPU free (needs $vcpus)"
  else bad "$size: family $family has $free vCPU free, needs $vcpus — request quota"; fi
done

total=$(az vm list-usage -l "$LOC" -o json --query "[?name.value=='cores'] | [0]")
tfree=$(jq -r '(.limit|tonumber) - (.currentValue|tonumber)' <<<"$total")
if [ "$tfree" -ge 8 ]; then ok "regional vCPUs free: $tfree (system 2 + surge 2 + GPU 4 = 8)"
else bad "regional vCPUs free: $tfree, need 8 (system + upgrade surge + GPU)"; fi

[ "$fail" -eq 0 ] && echo "pre-flight passed" || { echo "pre-flight FAILED — fix the ✘ items before terraform apply"; exit 1; }
