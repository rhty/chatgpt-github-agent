# ChatGPT GitHub Dev Agent — 導入手順

作成・資料確認日: 2026-09-27。Mac + OrbStackでの個人開発用スターターです。

**ChatGPTから実装・テスト・PR作成・コメント取得と返信を行います。通常の作業確認はChatGPTとGitHubで行い、手動のパッチ受け渡しは不要です。**

このZIPは、前の `chatgpt-dev-sandbox` とは別の構成です。前のディレクトリへ上書きしないでください。GitHub Appを登録するだけで機能が増えるわけではなく、このZIP内の制御用プログラムが連携を実装しています。

## 検証済みの範囲

ローカルの自動テスト41件が成功しています。GitHub応答を模擬したPR作成・追加コミット・コメントの重複防止、作業ファイルの取り扱い、実コマンド実行、および**実際のループバックHTTPを通したworker操作**を含みます。

**Dockerイメージのビルド、MCP SDKを使った実通信、GitHub/OpenAIの実アカウントへの接続は未検証です。** これらをこのMacで順に確認する `scripts/start.sh` を付けています。最初は秘密情報も自動デプロイもないテスト用リポジトリに限定してください。詳細は `VALIDATION.md`。

## 最初に確認すること

Web版ChatGPTで設定 → Security and login → Developer modeを確認し、Pluginsの「＋」でConnectionにTunnelがあるか確認してください。設定項目がなければ、この準備を進める前にその画面を確認します。

開発者向け資料はPlus/Pro等の読み書きを案内していますが、Help Centerにはより限定的な記載があります。**現在のアカウントの画面と実際のツール利用で確認**します。Freeで使える、無制限になる、どのモデルでも同じとは保証していません。このためだけに先にプランを変更する必要はありません。

今回のコードには、モデル推論API、Codex、Workを呼ぶ処理はありません。推論するのは操作中のChatGPTです。GitHubコメントを投稿するだけで通常のChatが自動起動する機能も入っていません。

## 構成

```text
ChatGPTのChat
    ↕
OpenAI Secure MCP Tunnel
    ↕ PC側から外向き接続
Mac / OrbStack
    ├─ control（認証情報を持つ、固定された制御プログラム）
    │    tunnel-client → 制御用MCP（標準入出力）
    │    GitHub AppとしてIssue/PR/コメント/CIを操作
    │    task_id・PR・ジョブの状態を保存
    │    リポジトリのコードは実行しない
    │
    └─ worker（コードを実行する隔離環境）
         Go / Node / Python / Git
         作業コピーの編集・コマンド実行・ログ保存
         GitHub/OpenAIのキー、Dockerソケット、Macのホームなし
```

controlのMCPはHTTPサーバーとして公開せず、tunnel-clientの子プロセスとして動かします。worker側のコードから、認証情報を持つMCPをHTTPで呼び出せる構成にはしていません。ホストのポート開放はありません。

ファイルはGitHubのコミットから取り込みます。Macの既存リポジトリをマウントする必要はありません。公開時は、controlがGitHub Git Database APIでコミットとPRを作り、workerにはpush用トークンを渡しません。

## 1. テスト用リポジトリを作る

ブラウザでGitHubへログインし、右上「＋」→New repositoryを開きます。

```bash
open 'https://github.com/new'
```

例として次の設定にします。組織名が違う場合は以後も読み替えてください。

| 項目 | 値 |
|---|---|
| Owner | mamama-dev |
| Repository name | ai-sandbox-check |
| Visibility | Private |
| Add README | 有効 |
| その他 | 最初は追加しない |

Create repositoryを押し、READMEがある状態を確認します。**空のリポジトリでは初期コミットを取り込めません。** このリポジトリにはActions/外部デプロイ連携やSecretsを設定しないでください。

## 2. 組織所有のGitHub Appを登録する

新しいGitHubユーザー、Bot用のメールアドレス、チームへの招待は不要です。普段のGitHubアカウントで操作します。組織のOwnerまたはApp作成権限が必要です。

GitHubの組織ページを開き、Settings → Developer settings → GitHub Apps → New GitHub Appへ進みます。

例:

```bash
open 'https://github.com/organizations/mamama-dev/settings/apps'
```

| 項目 | 設定 |
|---|---|
| GitHub App name | mamama-local-dev-agent（既存なら短い接尾辞を追加） |
| Description | Local development agent controlled from ChatGPT. |
| Homepage URL | 組織またはテスト用リポジトリのURL |
| Callback URL | 空欄 |
| Expire user authorization tokens | 既定値のまま。今回はユーザー認証を使わない |
| Request user authorization during installation | オフ |
| Enable Device Flow | オフ |
| Setup URL | 空欄 |
| WebhookのActive | **オフ** |
| Webhook URL / secret | 空欄 |

GitHub App名は全GitHubで一意である必要があります。ここで入力するHomepage URLのために新しいサイトをホストする必要はありません。Webhookを使わないので公開Webhookサーバーも不要です。

## 3. GitHub Appの権限を設定する

同じ画面のRepository permissionsを開き、**この版のプログラムに合わせて**次を設定します。

| 権限 | 設定 | 用途 |
|---|---|---|
| Contents | Read and write | ソース読み取り、作業ブランチとコミット |
| Pull requests | Read and write | PR作成・更新、レビュー取得と返信 |
| Issues | Read and write | Issue読み取り、PRの通常コメント |
| Actions | Read-only | CI実行とジョブログの取得 |
| Checks | Read-only | チェック結果 |
| Commit statuses | Read-only | コミットのステータス |
| Metadata | Read-only | リポジトリ情報。自動設定される場合あり |

それ以外はNo accessです。特にAdministration、Secrets、Workflows、Organization permissions、Account permissionsは付与しません。

下部のWhere can this GitHub App be installed?は **Only on this account** を選び、Create GitHub Appを押します。

**注意:** Contents: writeをGitHub側で「ai/ブランチだけ」の権限にできているわけではありません。ブランチ限定・マージ禁止は本プログラムでも検証しています。本番用リポジトリには利用できるブランチ保護を併用してください。Appを迂回許可対象にしないでください。

## 4. App IDと秘密鍵を用意し、インストールする

作成後のGeneral画面で **App ID（数字）** を控えます。`Iv...`などのClient IDではありません。

同じ画面のPrivate keysまで下がり、Generate a private keyを押します。`.pem`ファイルがMacに保存されます。**内容をChatGPTやGitHubに貼り付けないでください。** 後でファイルを選ぶだけで使えます。Client secretや個人用PATは不要です。

次に左側Install App → 対象組織のInstallを選びます。Only select repositoriesを選択し、`ai-sandbox-check`だけを選んでInstallしてください。

このスターターはInstallation IDをリポジトリから自動取得し、トークンを自動更新します。手動でInstallation IDを探したり、期限ごとにトークンを貼り直したりする操作は不要です。

## 5. OpenAIのトンネルと実行用キーを用意する

すでに前の手順で作成したものがあれば再利用できます。ただし同じTunnel IDで動く古いクライアントは後で停止します。

```bash
open 'https://platform.openai.com/settings/organization/tunnels'
```

対象organizationでトンネルを作成します。名前は例として `mac-github-agent`。利用する**ChatGPT workspaceを関連付け**ます。Platformのorganizationだけに紐付けて終わらせないでください。作成した `tunnel_...` を控えます。

次にRuntime API keyを作成します。

```bash
open 'https://platform.openai.com/settings/organization/api-keys'
```

Restrictedにして **Tunnels: Read + Use** を付けます。その他の権限はこの用途では付けません。作成・管理用のRead + Manage権限と、常駐実行用のRead + Use権限は別です。Admin API keyやAll権限のキーを代用しないでください。

Tunnelsが表示されない場合は、選択したorganization、キーの種類、本人の権限を確認します。これはモデル推論APIを呼ぶためのキーではなく、トンネル接続の認証に使用します。ただしトンネル自体の独立した課金条件をこのスターターで保証するものではありません。

## 6. 新しいZIPをMacに展開する

OrbStackを起動してください。ZIPがDownloadsにある場合:

```bash
mkdir -p ~/ai-lab
unzip ~/Downloads/chatgpt-github-agent.zip -d ~/ai-lab
cd ~/ai-lab/chatgpt-github-agent

docker version
docker compose version
```

このComposeは外向き通信の経路を明示する `gw_priority` を使うため、Docker Compose 2.33.1以降が必要です。古い場合はOrbStack/Docker Composeを更新してから進めます。

前の `chatgpt-dev-sandbox` の上書きではありません。古いファイル・作業コピーはこの版に自動移行しません。

設定前に `compose.yaml` と `control/`、`worker/`、`scripts/` を確認できます。秘密情報を入力する場所は次の設定スクリプトだけです。モデルにそのファイルの読み取りを許可する必要はありません。

## 7. 対話式で設定を保存する

```bash
bash scripts/configure.sh
```

順番に入力します。

```text
GitHub App ID（数字）: 手順4で控えた数字
最初のリポジトリ [mamama-dev/ai-sandbox-check]: 同じならEnter
Tunnel ID（tunnel_...）: 手順5のID
```

次にMacのファイル選択画面が開くので、手順4でダウンロードした`.pem`を選びます。最後にOpenAI Tunnelの実行用APIキーを入力します。画面にキー文字列は表示されません。

最後に `CONFIG_SAVED` が出れば保存完了です。

```text
.env                         ID・対象リポジトリ・リソース設定
secrets/github-app.pem       GitHub App秘密鍵
secrets/tunnel-api-key       Tunnel認証キー
```

`.env`にキー本体は入れません。`secrets/`内はMac上の通常ファイルで、暗号化された保管庫ではありません。Git管理対象からは除外していますが、このフォルダごと共有しないでください。

CPU/メモリ・Go/Nodeの版を変える場合は`.env`を編集します。既定はworker4CPU/6GB、control1CPU/1GB、Go1.26、Node24です。これは本スターターの設定であり必須量ではありません。Mac/OrbStack全体に余裕がある範囲で設定します。

## 8. 古い接続を止め、新しい環境を起動する

**前のスターターを実際に起動していて、同じTunnel IDを再利用する場合だけ**、先に古い方で停止します。

```bash
cd ~/ai-lab/chatgpt-dev-sandbox
docker compose stop
cd ~/ai-lab/chatgpt-github-agent
```

同一Tunnel IDで複数のクライアントを同時に起動しないでください。この版はstdioを使うため、公式クライアントの単一インスタンス条件があります。

新しい方で:

```bash
bash scripts/start.sh
```

スクリプトがビルド、worker起動、GitHub App認証、対象リポジトリ、MCPツール列挙、Tunnel接続を順に確認します。

**すべて通った場合の目印**は以下です。

```text
SETUP_CHECK_OK
MCP_STDIO_CHECK_OK 16 tools
AGENT_READY
```

`SETUP_CHECK_OK`は読み取りと認証を確認した段階です。PRへの書き込み成功は次のChatGPTからのテストで確認します。

`AGENT_READY`が出たらターミナルを閉じて構いません。コンテナはバックグラウンドで動きます。ただしMacの電源、インターネット、OrbStackは必要です。Macがスリープすると接続できなくなることがあります。

## 9. ChatGPTに接続する

Web版ChatGPTでDeveloper modeを有効にし、Pluginsの「＋」を開きます。

```bash
open 'https://chatgpt.com/plugins'
```

| 項目 | 値 |
|---|---|
| Name | GitHub Dev Agent |
| Description | Read and edit isolated source copies, run tests, and create or update GitHub pull requests. |
| Connection | Tunnel |
| Tunnel | 手順5のトンネルを選択またはIDを入力 |
| MCP側Authentication | 項目があればNo Authentication |

PCのIPやlocalhostを入力するのではありません。No AuthenticationはMCP側に追加OAuthを付けない意味で、Tunnelの認証をなくす意味ではありません。GitHubの秘密鍵をChatGPTの接続画面へ貼り付ける必要もありません。

登録後、新規チャットの入力欄「＋」からDeveloper modeを選び、GitHub Dev Agentを追加します。利用できるツールには `system_status`、`start_task`、`publish_pr`、`get_feedback`、`reply` などが含まれます。

書き込みやコマンド実行の確認が出た場合、テスト用リポジトリと操作範囲を確認して承認してください。確認の要否はChatGPT側の設定に従います。本スターターは書き込みを読み取りと偽装しません。

## 10. ChatGPTからテストPRを作る

`prompts/01-connection-test.txt` をチャットに貼り付けます。対象リポジトリを変更した場合は先にその行を書き換えます。

成功すると、作業用の `ai/connection-test` ブランチにコミットが作成され、PRのURLが返ります。GitHub上で、追加ファイル、PR本文の検証結果、投稿主体がAppであることを確認してください。

Draftがそのリポジトリで使えない場合は、導入テストに限って通常PRへ切り替える指示をプロンプトに含めています。どちらも自動マージしません。初期テストのPRはマージせず、次のコメント確認に使います。

## 11. GitHubコメント → 修正 → 返信を確認する

テストPRの会話欄に、次のようにコメントします。

```text
接続テストのファイルの末尾に「レビュー対応確認済み」を1行追加してください。
```

ChatGPTに `prompts/02-review-followup.txt` を貼り付けます。既存task_idを再利用し、通常コメント・行単位レビュー・提出済みレビューを取得し、修正と検証後、同じPRに追加コミットして返信します。

**GitHubにコメントするだけでは、このChatが自動的に起動・再開するわけではありません。** 現段階ではChatGPTで「このPRのコメントに対応して」と開始指示を出します。Dockerへの指示やログのコピペは通常不要です。

同じ作業を別チャットから再開する場合はPR URLを示し、`list_tasks`から該当するtask_idを探させます。別タスクとして同じPRを作り直させないでください。

## 12. 実際の開発用リポジトリを追加する

最初の一往復ができてから追加します。

GitHubの組織Settings → GitHub Apps → 対象AppのConfigure（Installed GitHub Apps側）で、Only select repositoriesの一覧へ対象を追加します。Appの登録設定と、インストール先の許可設定は別画面です。

**先に追加先の既存CI・自動デプロイ・Secretsを確認してください。** Workflows権限を付けなくても、コミット/PRで既存のワークフローや外部デプロイが起動する場合があります。特に同一リポジトリの作業ブランチを信頼してSecretsを渡す設定には注意します。初期状態のまま本番用の自動反映先を許可しないでください。

GitHub側で追加後、実行中のコマンドが終わっている状態でMacから:

```bash
cd ~/ai-lab/chatgpt-github-agent
bash scripts/add-repo.sh
bash scripts/start.sh
```

入力するのは `owner/repository` です。GitHub Appのインストール設定と、このスターターの `ALLOWED_REPOS` の両方で許可します。追加後に `system_status` をChatGPTから確認させます。

実装依頼のひな形は `prompts/03-coding-task.txt` にあります。新規タスクはその時点のデフォルトブランチのソースから始まります。マージ済みPRを再利用せず、次のタスクIDを指定してください。

## 日常の使い方

ChatGPTで依頼:

> mamama-dev/対象リポジトリのIssue 12を実装し、テストしてDraft PRを作ってください。

レビュー後:

> このPRの新しいコメントとCI結果を確認し、修正して同じPRへ追加してください。対応内容をGitHubにも返信してください。

途中の確認:

> このPRに対応する作業の状態と、最後のテストの終了コード・出力を確認してください。

ジョブの詳細ログはworker内で上限付き保存し、MCP経由で取得します。GitHubにも進捗コメントが欲しい場合は、その投稿をChatGPTへ依頼します。常駐して自動投稿する監視Botではありません。

## 止める・復旧する

通常停止:

```bash
cd ~/ai-lab/chatgpt-github-agent
bash scripts/stop.sh
```

再開:

```bash
bash scripts/start.sh
```

接続全体が停止し、ChatGPTから確認できないときの診断:

```bash
bash scripts/doctor.sh
```

診断出力にはキー本体を出さない設計です。それでも共有前に個人情報や非公開リポジトリ名を確認してください。`.env`・`.pem`・`secrets/`を丸ごと貼る必要はありません。

停止で作業コピーや記録は消えません。ただし実行中のプロセスを途中から続行するものではありません。再起動後はジョブ状態を確認して必要なコマンドを再実行します。**`docker compose down -v`はデータを消すので、通常運用では使いません。**

GitHubへの書き込みを至急止める必要がある場合は、AppのインストールをSuspendまたはUninstallし、必要に応じてApp秘密鍵も失効させます。ローカルの停止とは別にGitHub側のアクセスを止められます。

## 初期版の範囲と制限

これは自分が管理するリポジトリ向けのスターターで、敵対的コードや複数ユーザーを受け入れる完成した基盤ではありません。

- 開発用workerは1つです。複数task_idのファイルは分かれますが、相互にセキュリティ隔離されていません。同時コマンドは1つです。同じtask_idを複数チャットから同時編集しないでください。
- ソースはスナップショットです。GitHub上のコミット履歴は維持して追加しますが、workerには元の完全なGit履歴・リモート設定はありません。submodule、LFSポインタ、symlinkは取り込み時に停止します。
- ソースは圧縮48MiB・展開160MiB・1ファイル8MiB・25,000要素まで。公開差分は200ファイル・合計12MiBまで。巨大なタスクは分割してください。これらは本スターターの設定です。
- ローカルのソース、コメント、テスト出力はツール結果としてOpenAIへ送られます。業務コードの利用条件は別途確認してください。
- workerの外向き通信は許可しています。インターネットや到達可能なネットワーク先へ通信できます。ネットワーク完全隔離ではありません。
- `.github/workflows`の公開、mainへの直接push、force push、マージ、リポジトリ削除のツールはありません。GitHub Appの認証情報自体の能力がこれらすべてを禁止するわけではありません。
- PRを長期間維持してベースが進む場合の自動rebase・複雑な競合解決は未実装です。別主体がai/ブランチを更新した場合は上書きせず停止します。
- CI結果の概要は件数上限があり、詳細は現PRのheadに対応するActions実行を対象にします。独自のmerge-refのみのCIや外部CIの全文ログは別対応です。チェックが存在しないことを成功と扱わないでください。
- ログは1ジョブ2MiBまで、終了済みログは保存件数や経過日数で整理します。task_idの作業コピー・依存キャッシュは自動削除しません。大量運用時にはディスク管理の拡張が必要です。
- Mac/OrbStack/Tunnel自体が停止した場合、それを同じ接続のChatGPTから復旧することはできません。プロセス再起動ポリシーはありますが、完全な無保守を保証するものではありません。

詳細な境界は `SECURITY.md`。再現可能な検証と未実施事項は `VALIDATION.md` を参照してください。

## 参照した公式資料

- OpenAI Secure MCP Tunnel: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- OpenAI Developer mode: https://developers.openai.com/api/docs/guides/developer-mode
- OpenAI Help Centerの提供条件: https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt
- tunnel-client stdio/configuration: https://github.com/openai/tunnel-client/blob/master/docs/configuration.md
- GitHub App登録: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app
- GitHub App権限: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
- GitHub App秘密鍵: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps
- GitHub Appインストール: https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app
- GitHub installation認証: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation
- GitHubワークフローのトリガー: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
- Docker Compose gateway設定: https://docs.docker.com/reference/compose-file/services/#gw_priority
