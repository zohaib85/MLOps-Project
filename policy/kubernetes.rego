# Deployment policy for rendered manifests (conftest, Rego v1).
# Run: helm template ... | conftest test -p policy -
# Workload issues are `deny`; Helm test hooks only `warn` (short-lived, in-namespace).
# (Helper set is named `issue`: conftest treats rules named deny/violation/warn as results.)
package main

workload_kinds := {"Deployment", "StatefulSet", "DaemonSet", "Job"}

pod_spec := input.spec.template.spec if input.kind in workload_kinds

pod_spec := input.spec if input.kind == "Pod"

is_hook if input.metadata.annotations["helm.sh/hook"]

name := sprintf("%s/%s", [input.kind, input.metadata.name])

run_as_non_root if pod_spec.securityContext.runAsNonRoot == true

drops_all(c) if "ALL" in c.securityContext.capabilities.drop

# Locally loaded images (kind) can't be pulled by digest; everything else must be.
digest_pinned(c) if contains(c.image, "@sha256:")

digest_pinned(c) if c.imagePullPolicy == "Never"

issue contains "pod securityContext.runAsNonRoot must be true" if {
	pod_spec
	not run_as_non_root
}

issue contains "automountServiceAccountToken must be false" if {
	pod_spec
	not pod_spec.automountServiceAccountToken == false
}

issue contains sprintf("container %q: allowPrivilegeEscalation must be false", [c.name]) if {
	some c in pod_spec.containers
	not c.securityContext.allowPrivilegeEscalation == false
}

issue contains sprintf("container %q: readOnlyRootFilesystem must be true", [c.name]) if {
	some c in pod_spec.containers
	not c.securityContext.readOnlyRootFilesystem == true
}

issue contains sprintf("container %q: must drop ALL capabilities", [c.name]) if {
	some c in pod_spec.containers
	not drops_all(c)
}

issue contains sprintf("container %q: image %q must be pinned by digest", [c.name, c.image]) if {
	some c in pod_spec.containers
	not digest_pinned(c)
}

issue contains sprintf("container %q: ':latest' tag is not allowed", [c.name]) if {
	some c in pod_spec.containers
	regex.match(`:latest(@|$)`, c.image)
}

issue contains sprintf("container %q: memory limit is required", [c.name]) if {
	some c in pod_spec.containers
	not c.resources.limits.memory
}

issue contains sprintf("container %q: %s is required", [c.name, probe]) if {
	input.kind == "Deployment"
	some c in pod_spec.containers
	some probe in ["readinessProbe", "livenessProbe"]
	not c[probe]
}

deny contains sprintf("%s: %s", [name, msg]) if {
	not is_hook
	some msg in issue
}

warn contains sprintf("%s (helm test hook): %s", [name, msg]) if {
	is_hook
	some msg in issue
}

# The inference endpoint must never be exposed publicly without an explicit internal LB.
deny contains sprintf("%s: type %s exposes the endpoint outside the cluster", [name, input.spec.type]) if {
	input.kind == "Service"
	input.spec.type in {"LoadBalancer", "NodePort"}
	not input.metadata.annotations["service.beta.kubernetes.io/azure-load-balancer-internal"] == "true"
}
