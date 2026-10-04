# llm-platform harness: smoke/eval tests + OpenAI-compatible mock server.
#   docker run IMAGE                         -> mock server on :8000
#   docker run -e BASE_URL=... IMAGE pytest tests/smoke -v   -> smoke tests against an endpoint
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    RESULTS_DIR=/tmp/results
WORKDIR /opt/llm-platform

# Apply Debian security updates on top of the pinned base. The base digest only moves when
# Docker rebuilds python:3.12-slim; fixes (e.g. CVE-2026-103111 in libpcre2, fixed in
# 10.46-1~deb13u3) often land in Debian first. Reproducibility comes from publishing the
# *result* by digest — the image CI tests and scans is exactly the one that ships.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

COPY pyproject.toml ./
COPY config/ config/
COPY scripts/ scripts/
COPY app/ app/
COPY tests/ tests/

# Non-root; the chart also enforces runAsNonRoot and a read-only root filesystem.
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["python", "-m"]
CMD ["app.mock_openai"]
