#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo '先に bash scripts/configure.sh を実行してください。'; exit 1; }
command -v docker >/dev/null || { echo 'Docker CLI が見つかりません。OrbStackを起動してください。'; exit 1; }
docker info >/dev/null 2>&1 || { echo 'OrbStackを起動してから、もう一度このコマンドを実行してください。'; exit 1; }
printf '\n開発環境と制御環境をビルドします。初回はイメージのダウンロードがあります。\n'
docker compose config --quiet
docker compose build
# Only one stdio tunnel instance may own the same Tunnel ID.
docker compose stop control >/dev/null 2>&1 || true
docker compose up -d worker
ready=0
for ((i=0;i<60;i++)); do
  if docker compose exec -T worker python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).read()" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 ]] || { echo '開発環境の起動を確認できませんでした。bash scripts/doctor.sh の出力を確認してください。'; exit 1; }
printf '\nGitHub App・対象リポジトリ・隔離設定を確認します。\n'
docker compose run --rm --no-deps --entrypoint /opt/venv/bin/python control /opt/control/doctor.py
printf '\nMCPツールの起動を確認します。\n'
docker compose run --rm --no-deps --entrypoint /opt/venv/bin/python control /opt/control/smoke_test.py
printf '\nOpenAIへのトンネルを起動します。\n'
docker compose up -d control
ready=0
for ((i=0;i<60;i++)); do
  if docker compose exec -T control python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz',timeout=2).read()" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
if [[ "$ready" != 1 ]]; then
  echo 'トンネルの接続を確認できませんでした。診断結果を表示します（キー本体は表示しません）。'
  # Doctor probes a new bind; avoid colliding with the running daemon on port 8080.
  docker compose exec -T control /usr/bin/tunnel-client doctor \
    --control-plane.api-key=file:/run/secrets/tunnel_api_key \
    --health.listen-addr=127.0.0.1:0 --explain || true
  exit 1
fi
printf '\nAGENT_READY\nChatGPTのPlugins画面で、このTunnelを接続してください。\n'
printf 'このターミナルは閉じて大丈夫です。MacとOrbStackは起動したままにしてください。\n'
