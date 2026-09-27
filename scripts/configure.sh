#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then
  echo '設定済みです。.env を上書きしません。対象リポジトリの追加は scripts/add-repo.sh を使ってください。'
  exit 1
fi
printf '\nGitHub と OpenAI で取得した情報を、Mac 内だけに保存します。\n\n'
read -r -p 'GitHub App ID（数字。Client IDではありません）: ' app_id
[[ "$app_id" =~ ^[0-9]+$ ]] || { echo 'App IDは数字を入力してください。'; exit 1; }
read -r -p '最初のリポジトリ [mamama-dev/ai-sandbox-check]: ' repo
repo=${repo:-mamama-dev/ai-sandbox-check}
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo 'owner/repository の形式で入力してください。'; exit 1; }
read -r -p 'Tunnel ID（tunnel_...）: ' tunnel
[[ "$tunnel" =~ ^tunnel_[0-9a-f]{32}$ ]] || { echo 'Tunnel IDの形式を確認してください。'; exit 1; }
printf '\n次に、GitHub からダウンロードした秘密鍵 .pem を選びます。\n'
if [[ "$(uname -s)" == Darwin ]] && command -v osascript >/dev/null; then
  key_path=$(osascript -e 'POSIX path of (choose file with prompt "GitHub Appの秘密鍵（.pem）を選んでください")')
else
  read -r -p '.pem のファイルパス（引用符は不要）: ' key_path
fi
[[ -f "$key_path" ]] || { echo '秘密鍵ファイルが見つかりません。'; exit 1; }
openssl pkey -in "$key_path" -noout >/dev/null 2>&1 || { echo '秘密鍵を読み取れません。.pem を確認してください。'; exit 1; }
read -r -s -p 'OpenAI Tunnel の実行用APIキー（画面には表示しません）: ' api_key
printf '\n'
[[ -n "$api_key" ]] || { echo 'キーが空です。'; exit 1; }
mkdir -p secrets
chmod 700 secrets
cp "$key_path" secrets/github-app.pem
chmod 600 secrets/github-app.pem
printf '%s' "$api_key" > secrets/tunnel-api-key
chmod 600 secrets/tunnel-api-key
unset api_key
cat > .env <<EOF
COMPOSE_PROJECT_NAME=chatgpt-github-agent
HOST_UID=$(id -u)
HOST_GID=$(id -g)
GITHUB_APP_ID=$app_id
ALLOWED_REPOS=$repo
CONTROL_PLANE_TUNNEL_ID=$tunnel
DEV_CPUS=4
DEV_MEMORY=6g
GO_IMAGE=golang:1.26-bookworm
NODE_IMAGE=node:24-bookworm-slim
TUNNEL_IMAGE=ghcr.io/openai/tunnel-client:v0.0.15
EOF
chmod 600 .env
printf '\nCONFIG_SAVED\n設定を保存しました。次は bash scripts/start.sh を実行してください。\n'
printf '秘密鍵・APIキーはチャットやGitHubに貼り付けないでください。\n'
