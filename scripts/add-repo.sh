#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo '先にconfigure.shを実行してください。'; exit 1; }
read -r -p '追加するリポジトリ（owner/repository）: ' repo
[[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { echo '形式を確認してください。'; exit 1; }
current=$(sed -n 's/^ALLOWED_REPOS=//p' .env)
case ",$current," in *",$repo,"*) echo '登録済みです。'; exit 0;; esac
read -r -p 'GitHub Appの対象追加と、このリポジトリのCI/デプロイ設定を確認しましたか？ [yes/no]: ' answer
[[ "$answer" == yes ]] || { echo '変更しませんでした。'; exit 1; }
tmp=$(mktemp './.env.XXXXXX')
trap 'rm -f "$tmp"' EXIT
awk -v value="$current,$repo" '/^ALLOWED_REPOS=/{print "ALLOWED_REPOS=" value;next}{print}' .env > "$tmp"
chmod 600 "$tmp"
mv "$tmp" .env
printf '追加しました。実行中の作業を止めた状態で bash scripts/start.sh を実行してください。\n'
