#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
cd "$(dirname "$0")/.."
usage() {
  printf 'Usage: bash scripts/configure.sh [--project-name NAME]\n'
  printf 'NAME: lowercase letters/digits, hyphens, underscores; start with a letter or digit.\n'
  printf 'Omit --project-name to enter a name interactively. Existing settings are never overwritten.\n'
}
project_name=''
project_name_given=0
while (( $# > 0 )); do
  case "$1" in
    --project-name)
      [[ "$project_name_given" == 0 && $# -ge 2 ]] || { usage >&2; exit 1; }
      project_name=$2
      project_name_given=1
      shift 2
      ;;
    --project-name=*)
      [[ "$project_name_given" == 0 ]] || { usage >&2; exit 1; }
      project_name=${1#*=}
      project_name_given=1
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
  esac
done
if [[ -e .env || -L .env ]]; then
  echo '設定済みです。.env を上書きしません。対象リポジトリの追加は scripts/add-repo.sh を使ってください。'
  exit 1
fi
if [[ -e secrets || -L secrets ]]; then
  echo 'secrets が既にあります。認証情報を上書きしません。別環境は新しいclone先で設定してください。'
  exit 1
fi
printf '\nGitHub と OpenAI で取得した情報を、Mac 内だけに保存します。\n\n'
printf '別環境には、別のclone先・Docker環境名・GitHub App・Tunnelを使ってください。\n'
if [[ "$project_name_given" == 0 ]]; then
  IFS= read -r -p 'Docker環境名（例: team-github-agent。省略不可）: ' project_name
fi
[[ "$project_name" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || {
  echo 'Docker環境名は小文字英数字で始め、小文字英数字・ハイフン・アンダースコアだけを使用してください。'
  exit 1
}
if [[ -n "${COMPOSE_PROJECT_NAME:-}" && "$COMPOSE_PROJECT_NAME" != "$project_name" ]]; then
  echo 'シェルの COMPOSE_PROJECT_NAME と指定した環境名が異なります。unset COMPOSE_PROJECT_NAME 後に再実行してください。'
  exit 1
fi
read -r -p 'GitHub App ID（数字。Client IDではありません）: ' app_id
[[ "$app_id" =~ ^[0-9]+$ ]] || { echo 'App IDは数字を入力してください。'; exit 1; }
read -r -p '許可するリポジトリ（owner/repository。複数は空白なしのカンマ区切り）: ' repo
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(,[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)*$ ]] || { echo 'owner/repository、または空白なしのカンマ区切りで入力してください。'; exit 1; }
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
COMPOSE_PROJECT_NAME=$project_name
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
printf '\nCONFIG_SAVED\nCOMPOSE_PROJECT_NAME=%s\n' "$project_name"
printf '設定を保存しました。同名の別環境がないことを確認してから bash scripts/start.sh を実行してください。\n'
printf '秘密鍵・APIキーはチャットやGitHubに貼り付けないでください。\n'
