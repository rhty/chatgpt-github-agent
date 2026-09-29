# 組織ごとに開発環境を分ける

[セットアップに戻る](setup.md)

同じソースコードを、**別のclone先・Compose環境名・認証情報・Tunnel ID**で利用します。
この手順は新しい環境を追加するためのもので、既存環境の改名やデータ移行は行いません。

## 分けるもの

- GitHub Appと秘密鍵は各組織で別に作成します。Private Appのまま使えます。
- Tunnel IDと実行用APIキーを環境ごとに用意し、適切なChatGPTワークスペースに関連付けます。
- `.env`と`secrets/`を既存環境からコピーしません。新しいclone先で設定します。
- Docker環境名を重複させません。`COMPOSE_PROJECT_NAME`はコンテナだけでなく、Compose管理のネットワーク・ボリュームの識別にも使われます。

## 新しい環境を設定する

以下は`team-b`という仮の環境名の例です。既存の環境と異なる名前に置き換えてください。

```bash
mkdir -p ~/ai-lab &&
git clone https://github.com/rhty/chatgpt-github-agent.git ~/ai-lab/team-b-github-agent &&
cd ~/ai-lab/team-b-github-agent &&
bash scripts/configure.sh --project-name team-b-github-agent
```

同名のディレクトリが既にある場合は削除せず、その用途と設定を確認してから進めます。
`--project-name`を省略すると名前を対話入力します。空欄は受け付けません。
Dockerのルールに合わせ、小文字英数字で始め、小文字英数字・ハイフン・アンダースコアだけを使います。

入力するのは、新しいGitHub App ID、許可リポジトリ、Tunnel ID、そのAppの秘密鍵、Tunnel実行用APIキーです。
許可リポジトリは、例えば次のようにまとめて入力できます。

```text
example-team/core,example-team/console,example-team/kiban
```

GitHub Appのインストール設定でも対象リポジトリを許可しておく必要があります。
`configure.sh`はGitHubへのインストールや権限変更を実行しません。
設定済みの`.env`や`secrets/`があると処理を止め、既存の設定・鍵を上書きしません。

## 設定を確認して起動する

```bash
grep '^COMPOSE_PROJECT_NAME=' .env
bash scripts/start.sh
```

この例では`COMPOSE_PROJECT_NAME=team-b-github-agent`であることを確認します。
`MCP_HTTP_CHECK_OK`と`AGENT_READY`の後、ChatGPTに別のMCP接続を作り、新しいTunnelを選びます。
接続名も`Team B GitHub Dev Agent`など区別できる名前にします。
最初は`system_status`でAppと許可リポジトリを確認し、書き込みは後で確認します。

**既存環境の`.env`を編集したり、`COMPOSE_PROJECT_NAME`を改名したりする必要はありません。**
異なる名前で、現在のCompose定義を別々のclone先から起動すると、作業データ・タスク状態・鍵の保存先を分けられます。
`start.sh`/`stop.sh`/`doctor.sh`は操作したい環境のclone先で実行します。

シェルで`COMPOSE_PROJECT_NAME`を常時exportしないでください。Composeではシェルの値が`.env`より優先されます。
設定時に異なるexport値があればスクリプトは停止します。意図しない値なら`unset COMPOSE_PROJECT_NAME`して再実行します。
起動時も同じ注意が必要です。`-p`、`COMPOSE_FILE`、`COMPOSE_ENV_FILES`等で別環境を上書き指定しないでください。
同名プロジェクトの自動検出は行いません。起動前に既存環境と異なる名前であることを確認してください。

## 分離の範囲

現在のCompose定義は固定の外部ボリューム名やホスト公開ポートを使いません。
コンテナ・ボリュームを分けても、同じMacとDockerエンジンを使う以上、ホスト障害やホスト管理者からの分離ではありません。
別環境へのネットワーク攻撃を防ぐ包括的な送信先制御もありません。[安全性と運用上の境界](../SECURITY.md)を参照してください。
CPU・メモリ上限は環境ごとに適用されるため、同時実行時はMac全体の使用量に合わせて各`.env`の`DEV_CPUS`/`DEV_MEMORY`を調整します。
GitHub AppをPrivateにしても、コードやログがツール結果としてChatGPTへ送信される点は変わりません。

## 参照

- [Docker Compose project name](https://docs.docker.com/compose/how-tos/project-name/)
- [Docker Compose environment variables](https://docs.docker.com/compose/how-tos/environment-variables/envvars/)
