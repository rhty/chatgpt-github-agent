# These are project defaults, not requirements imposed by MCP.
ARG GO_IMAGE=golang:1.26-bookworm
ARG NODE_IMAGE=node:24-bookworm-slim
ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${GO_IMAGE} AS go-toolchain
FROM ${NODE_IMAGE} AS node-toolchain
FROM ${PYTHON_IMAGE}
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates git ripgrep curl jq make build-essential pkg-config libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=go-toolchain /usr/local/go /usr/local/go
COPY --from=node-toolchain /usr/local/bin/node /usr/local/bin/node
COPY --from=node-toolchain /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && corepack enable
RUN if ! getent group "${HOST_GID}" >/dev/null; then groupadd -g "${HOST_GID}" devgroup; fi \
    && useradd -m -u "${HOST_UID}" -g "${HOST_GID}" -s /bin/bash dev \
    && mkdir -p /workspace /state/jobs /home/dev/.cache /home/dev/go /opt/mcp \
    && chown -R "${HOST_UID}:${HOST_GID}" /workspace /state /home/dev
COPY engine.py repository.py server.py /opt/mcp/
ENV PATH="/usr/local/go/bin:/home/dev/go/bin:/usr/local/bin:/usr/bin:/bin" \
    HOME=/home/dev LANG=C.UTF-8 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    GOPATH=/home/dev/go GOCACHE=/home/dev/.cache/go-build \
    GOMODCACHE=/home/dev/go/pkg/mod NPM_CONFIG_CACHE=/home/dev/.cache/npm \
    COREPACK_HOME=/home/dev/.cache/corepack CI=1
USER dev
WORKDIR /workspace
CMD ["python", "/opt/mcp/server.py"]
