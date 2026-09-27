#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose stop
echo '停止しました。作業コピーと記録は削除していません。'
