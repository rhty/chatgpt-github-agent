ARG TUNNEL_IMAGE=ghcr.io/openai/tunnel-client:v0.0.15
FROM ${TUNNEL_IMAGE} AS official-tunnel
FROM python:3.13-slim-bookworm
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=official-tunnel /usr/bin/tunnel-client /usr/bin/tunnel-client
COPY --from=official-tunnel /usr/bin/cloudflared /usr/bin/cloudflared
RUN if ! getent group "${HOST_GID}" >/dev/null; then groupadd -g "${HOST_GID}" agentgroup; fi \
    && useradd -m -u "${HOST_UID}" -g "${HOST_GID}" -s /usr/sbin/nologin agent \
    && mkdir -p /state/tasks /opt/control \
    && chown -R "${HOST_UID}:${HOST_GID}" /state
COPY requirements.txt /opt/control/requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /opt/control/requirements.txt
COPY *.py /opt/control/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp \
    MCP_COMMAND="/opt/venv/bin/python /opt/control/mcp_server.py" \
    HEALTH_LISTEN_ADDR=127.0.0.1:8080 LOG_LEVEL=info LOG_FORMAT=json
USER agent
WORKDIR /opt/control
ENTRYPOINT ["/usr/bin/tunnel-client", "run"]
CMD ["--control-plane.api-key=file:/run/secrets/tunnel_api_key", "--mcp.max-concurrent-requests=1", "--mcp.stdio-send-initialized-notification=true"]
