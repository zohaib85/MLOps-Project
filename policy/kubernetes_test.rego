# Unit tests for the policy itself: `conftest verify -p policy`
package main

good_deployment := {
	"kind": "Deployment",
	"metadata": {"name": "ok"},
	"spec": {"template": {"spec": {
		"automountServiceAccountToken": false,
		"securityContext": {"runAsNonRoot": true},
		"containers": [{
			"name": "server",
			"image": "repo/app:v1@sha256:0000000000000000000000000000000000000000000000000000000000000000",
			"securityContext": {
				"allowPrivilegeEscalation": false,
				"readOnlyRootFilesystem": true,
				"capabilities": {"drop": ["ALL"]},
			},
			"resources": {"limits": {"memory": "1Gi"}},
			"readinessProbe": {"httpGet": {"path": "/health"}},
			"livenessProbe": {"httpGet": {"path": "/health"}},
		}],
	}}},
}

test_good_deployment_passes if {
	count(deny) == 0 with input as good_deployment
}

test_unpinned_image_denied if {
	bad := json.patch(good_deployment, [{"op": "replace", "path": "/spec/template/spec/containers/0/image", "value": "repo/app:v1"}])
	some msg in deny with input as bad
	contains(msg, "pinned by digest")
}

test_root_denied if {
	bad := json.patch(good_deployment, [{"op": "replace", "path": "/spec/template/spec/securityContext/runAsNonRoot", "value": false}])
	some msg in deny with input as bad
	contains(msg, "runAsNonRoot")
}

test_missing_probe_denied if {
	bad := json.patch(good_deployment, [{"op": "remove", "path": "/spec/template/spec/containers/0/livenessProbe"}])
	some msg in deny with input as bad
	contains(msg, "livenessProbe")
}

test_hook_pod_only_warns if {
	pod := {
		"kind": "Pod",
		"metadata": {"name": "t", "annotations": {"helm.sh/hook": "test"}},
		"spec": {"containers": [{"name": "c", "image": "repo/x:dev"}]},
	}
	count(deny) == 0 with input as pod
	count(warn) > 0 with input as pod
}

test_public_loadbalancer_denied if {
	svc := {"kind": "Service", "metadata": {"name": "s"}, "spec": {"type": "LoadBalancer"}}
	count(deny) == 1 with input as svc
}

test_internal_loadbalancer_allowed if {
	svc := {
		"kind": "Service",
		"metadata": {"name": "s", "annotations": {"service.beta.kubernetes.io/azure-load-balancer-internal": "true"}},
		"spec": {"type": "LoadBalancer"},
	}
	count(deny) == 0 with input as svc
}
