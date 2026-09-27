# セットアップ

[READMEに戻る](../README.md)

Mac + OrbStackを想定した手順です。`OWNER`は自分のGitHubユーザー名または組織名に置き換えてください。
最初はREADMEだけを持つテスト用リポジトリで、PR作成からコメント対応まで確認します。

## 0. ChatGPTでカスタムMCPの入口を確認する

GitHub Appの鍵発行やローカルの起動より先に、この確認を行います。
必要なのは一般的なプラグインの追加ではなく、**カスタムMCPサーバーの接続作成**です。

2026-09-27の公式資料には、次の差異があります。

| 公式資料 | 案内 |
|---|---|
| [Developer mode](https://developers.openai.com/api/docs/guides/developer-mode) | Settings → Security and loginでDeveloper modeを有効化 |
| [Developer modeのHelp Center](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) | プラン・ワークスペース権限別の手順。Apps → Advanced settingsという表記もある |
| [PluginsのHelp Center](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt-and-codex) | Add (+)はPlugin Creatorを開く入口。Create MCP appは別の操作 |

利用中の画面にDeveloper modeがなければ、次の順に確認します。

1. 設定の検索欄に文字が入っていれば消し、`developer`または`MCP`で検索する。
2. Plugins画面で、カスタムMCPの作成項目があるか確認する。Personalタブがあれば、そちらも確認する。
3. `Create MCP app`などの接続作成項目が見つかったら、`Connection: Tunnel`を選べるか確認する。まだ作成を完了させる必要はない。

これは画面上の入口を確認するための手順で、検索結果やPersonalタブに必ず項目があることを保証するものではありません。
**「Add」を押すだけでMCP接続フォームが開くとは限りません。** Plugin Creatorの会話が開いた場合は、接続の作成が完了したわけではありません。

入口が見つからない場合、スクリーンショットだけで機能未提供・権限不足・UI変更のどれかと断定せず、アカウントの提供状況を確認してください。
`Enforce CSP for custom apps`やMFAなど、別のセキュリティ設定を変更して代用しないでください。プラン変更も先に行う必要はありません。

読み取りだけでなく、コード実行と書き込みを使えることは接続後のテストで確認します。

## 1. テスト用リポジトリを作る

GitHubのNew repositoryで、所有者を`OWNER`、名前を`ai-sandbox-check`、公開範囲をPrivateに設定し、READMEを追加して作成します。
空のリポジトリでは初期コミットを取得できません。Secrets、自動デプロイ、実運用データは入れないでください。

## 2. GitHub Appを登録する

組織所有なら、組織のSettings → Developer settings → GitHub Appsから作成します。
個人所有なら、自分のSettings → Developer settings → GitHub Appsを使います。
登録権限については[GitHubの公式手順](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app)を参照してください。

新しいBot用ユーザーアカウントは不要です。

| 項目 | 設定 |
|---|---|
| GitHub App name | 他と重複しない名前。例: OWNER-local-dev-agent |
| Description | Local development agent controlled from ChatGPT. |
| Homepage URL | 自分のサイト、所有者のGitHubページ、またはリポジトリのURL |
| Redirect URI / Callback URL | 空欄。ユーザー認証は利用しない |
| Allow wildcard matching | オフ |
| Expire user authorization tokens | 既定のオンのまま。今回はユーザートークンを利用しない |
| Request user authorization (OAuth) during installation | オフ |
| Enable Device Flow | オフ |
| Setup URL | 空欄 |
| Redirect on update | オフ |
| Webhook: Active | オフ |
| Webhook URL / Secret | 空欄 |
| Where can this GitHub App be installed? | Only on this account |

### Repository permissions

以下は[control/github_api.py](../control/github_api.py)の`PERMISSIONS`が要求する権限です。
選択済み件数だけでなく、各項目の読み取り・書き込み区分を確認してください。

| 権限 | 設定 | 用途 |
|---|---|---|
| Contents | Read and write | ソース取得、作業ブランチとコミットの作成 |
| Pull requests | Read and write | PR作成・更新、レビュー取得・返信 |
| Issues | Read and write | Issue取得、PRの通常コメント |
| Actions | Read-only | CI実行情報とジョブログの取得。実行を起動する権限ではない |
| Checks | Read-only | チェック結果の取得 |
| Commit statuses | Read-only | コミットのステータス取得 |
| Metadata | Read-only | リポジトリ情報。必須項目として自動設定される場合がある |

それ以外のRepository permissionsと、Organization / Account / Enterprise permissionsはNo accessにします。
Administration、Secrets、Workflowsを追加する必要はありません。

確認後、Create GitHub Appを押します。[権限の公式説明](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)も参照してください。

## 3. App ID・秘密鍵・インストール

作成したAppのGeneral画面で、数字の**App ID**を控えます。Client IDではありません。
Private keys → Generate a private keyで`.pem`ファイルを保存します。Client secretや個人用PATは使いません。

Install Appから対象アカウントへ進み、**Only select repositories**で`ai-sandbox-check`だけを選択してインストールします。
Installation IDの取得と短期トークンの更新はプログラムが行います。

秘密鍵をChatGPTへ貼り付けたり、リポジトリへコミットしたりしないでください。
詳しくは[秘密鍵の管理](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps)と[Appのインストール](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app)を参照してください。

## 4. OpenAI Secure MCP Tunnelを作成する

[PlatformのTunnel設定](https://platform.openai.com/settings/organization/tunnels)でトンネルを作成し、`tunnel_...`のIDを控えます。
対象のPlatform organizationに加えて、利用するChatGPT workspaceを関連付けてください。

実行用APIキーはRestrictedにし、Tunnelsの**Read + Use**を付与します。
トンネルの管理用キーやAll権限のキーではなく、常駐クライアント用のキーを使います。

必要な権限項目が見えない場合は、対象organizationと本人の権限を確認します。
詳細は[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)と[tunnel-clientの権限設定](https://github.com/openai/tunnel-client/blob/master/docs/permissions.md)を参照してください。

## 5. ローカルに取得して設定する

OrbStackを起動し、ターミナルで実行します。

```bash
git clone https://github.com/rhty/chatgpt-github-agent.git
cd chatgpt-github-agent
docker version
docker compose version
bash scripts/configure.sh
```

Composeは`gw_priority`を使用するため[2.33.1以降](https://docs.docker.com/reference/compose-file/services/#gw_priority)が必要です。
`configure.sh`には次を入力します。

| 入力 | 内容 |
|---|---|
| GitHub App ID | 数字のApp ID |
| 最初のリポジトリ | `OWNER/ai-sandbox-check`。省略不可 |
| Tunnel ID | 作成した`tunnel_...` |
| 秘密鍵 | macOSではファイル選択画面から`.pem`を指定。他の環境ではパスを入力 |
| Tunnel実行用APIキー | 非表示で入力 |

`CONFIG_SAVED`で設定保存が完了します。既存の`.env`は上書きしません。

```text
.env                       ID・許可リポジトリ・リソース設定
secrets/github-app.pem     GitHub App秘密鍵
secrets/tunnel-api-key     Tunnel実行用APIキー
```

`secrets/`はGit管理対象外ですが、ホスト上の通常のファイルです。フォルダごとの共有にも注意してください。
CPU・メモリ・言語のバージョンを変更する場合は`.env`を編集します。

## 6. 起動する

同じTunnel IDで動く別のクライアントがあれば、先に停止してください。
この構成はstdioを使用します。[公式クライアントの構成要件](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)に従い、同じTunnelに複数のクライアントを接続しません。

```bash
bash scripts/start.sh
```

ビルド、workerの起動、GitHub認証、MCP初期化、Tunnel接続を順番に確認します。

```text
SETUP_CHECK_OK
MCP_STDIO_CHECK_OK 16 tools
AGENT_READY
```

`AGENT_READY`は起動確認の完了を示します。GitHubへの書き込み成功を確認したものではありません。
コンテナはバックグラウンドで動きますが、ホスト、Docker、ネットワークは稼働している必要があります。

## 7. ChatGPTに接続する

手順0で確認した**カスタムMCPの接続作成画面**を開きます。

| 項目 | 設定 |
|---|---|
| Name | GitHub Dev Agent |
| Description | Read and edit isolated source copies, run tests, and create or update GitHub pull requests. |
| Connection | Tunnel |
| Tunnel | 手順4のトンネルを選択、またはIDを入力 |
| MCP側Authentication | 項目があればNo Authentication |

No Authenticationは内部MCPに追加OAuthを設けない意味で、Tunnelの認証を無効化するものではありません。
PCのIPやlocalhostを入力したり、GitHubの秘密鍵をアップロードしたりする必要はありません。

検出されたツールに`system_status`、`start_task`、`publish_pr`、`get_feedback`、`reply`などがあることを確認します。
新しいチャットでこの接続を選び、操作内容を確認して必要な承認を行います。
ツール変更時の再読み込みなどは[公式の接続・テスト手順](https://developers.openai.com/plugins/deploy/connect-chatgpt)を参照してください。

## 8. PR作成とレビュー対応を確認する

[prompts/01-connection-test.txt](../prompts/01-connection-test.txt)の`OWNER/ai-sandbox-check`を自分のリポジトリへ置き換え、接続済みのChatGPTへ送信します。
返されたPRで、追加ファイル、検証結果、Appによる投稿を確認します。このPRはまだマージしません。

GitHubのPR会話欄に、次のコメントを書きます。

```text
接続テストのファイルの末尾に「レビュー対応確認済み」を1行追加してください。
```

続けて[prompts/02-review-followup.txt](../prompts/02-review-followup.txt)をChatGPTへ送信します。
同じPRに追加コミットと返信が付くことを確認してください。
GitHubコメントだけでは自動起動しません。開始・再開の指示はChatGPTから行います。

## 9. 開発対象を追加する

対象リポジトリの既存CI、自動デプロイ、利用するSecretsを確認します。
Workflowsの編集権限を付けなくても、コミットやPRを契機に既存ワークフローが起動する場合があります。
[GitHubのトリガー仕様](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)を参照してください。

GitHubのインストール済みAppのConfigureで対象リポジトリを追加し、実行中の作業がない状態で次を実行します。

```bash
bash scripts/add-repo.sh
bash scripts/start.sh
```

GitHub Appの許可と`ALLOWED_REPOS`の両方で制限します。
実装依頼には[prompts/03-coding-task.txt](../prompts/03-coding-task.txt)を使えます。

## 停止・診断

```bash
bash scripts/stop.sh
bash scripts/start.sh
bash scripts/doctor.sh
```

通常の停止で作業コピーや保存済みログは消えません。実行中のプロセスは途中から再開されないため、再起動後に状態を確認します。
`docker compose down -v`は永続ボリュームを削除します。通常の停止には使わないでください。

診断結果を共有する場合は、キー・秘密鍵・個人情報が含まれていないか確認してください。
GitHubへのアクセスを緊急に止める場合は、Appのインストールを停止・解除し、必要に応じて秘密鍵を失効させます。

詳細な境界は[SECURITY.md](../SECURITY.md)、検証範囲は[VALIDATION.md](../VALIDATION.md)を参照してください。
