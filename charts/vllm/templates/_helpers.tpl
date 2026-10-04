{{- define "vllm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "vllm.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "vllm.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "vllm.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vllm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "vllm.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{ include "vllm.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: inference
llm-platform/engine: {{ .Values.engine }}
{{- with .Values.model.revision }}
llm-platform/model-revision: {{ . | trunc 12 | quote }}
{{- end }}
{{- end }}

{{- define "vllm.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "vllm.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* repository[:tag][@digest] */}}
{{- define "vllm.imageRef" -}}
{{- $ref := .repository -}}
{{- if .tag }}{{ $ref = printf "%s:%s" $ref .tag }}{{ end -}}
{{- if .digest }}{{ $ref = printf "%s@%s" $ref .digest }}{{ end -}}
{{- $ref -}}
{{- end }}

{{- define "vllm.image" -}}
{{- if eq .Values.engine "vllm" -}}
{{- if not .Values.vllm.image.digest }}{{ fail "vllm.image.digest is required (pin images by digest) — run `make values`" }}{{ end -}}
{{- include "vllm.imageRef" .Values.vllm.image -}}
{{- else if eq .Values.engine "mock" -}}
{{- include "vllm.imageRef" .Values.mock.image -}}
{{- else -}}
{{- fail (printf "engine must be 'vllm' or 'mock', got %q" .Values.engine) -}}
{{- end -}}
{{- end }}

{{- define "vllm.cacheClaimName" -}}
{{- default (printf "%s-model-cache" (include "vllm.fullname" .)) .Values.modelCache.existingClaim }}
{{- end }}
