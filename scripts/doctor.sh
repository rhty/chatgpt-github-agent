#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker info >/dev/null 2>&1 || { echo 'Docker/OrbStackに接続できません。OrbStackを起動してください。'; exit 1; }
echo '--- Container state (no secrets) ---'
docker compose ps
echo '--- GitHub / worker checks ---'
if docker compose exec -T control /opt/venv/bin/python /opt/control/doctor.py; then :
else
  docker compose run --rm --no-deps --entrypoint /opt/venv/bin/python control /opt/control/doctor.py || true
fi
echo '--- Tunnel readiness ---'
docker compose exec -T control python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/readyz',timeout=4).read().decode()[:4000])" || true
echo '--- Tunnel diagnostic ---'
docker compose exec -T control /usr/bin/tunnel-client doctor \
  --control-plane.api-key=file:/run/secrets/tunnel_api_key --explain || true
