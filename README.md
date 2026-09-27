# ChatGPT GitHub Agent

ChatGPTからローカルの開発環境を操作し、GitHubのPR作成・レビュー対応まで行うMCPサーバーです。
OpenAI Secure MCP Tunnelで接続し、コードの実行環境とGitHubの認証情報を分離します。

**開発中のプロジェクトです。** 自動テストと実接続の検証範囲は[検証ガイド](VALIDATION.md)を参照してください。

## できること

- GitHubのソースを作業コピーとして取得し、ファイルを検索・編集する。
- コンテナ内でコマンドやテストを実行し、終了コードとログを取得する。
- GitHub App名義で作業ブランチ・コミット・PRを作成し、同じPRを更新する。
- Issue、PRコメント、レビュー、CI結果を取得し、修正内容を返信する。

作業はChatGPTから指示します。GitHubへのコメントをきっかけにAIを自動起動するWebhookや、常駐する推論ループは含みません。

## 構成

```text
ChatGPT
  │
OpenAI Secure MCP Tunnel
  │ ホスト側から外向き接続
  ▼
control コンテナ
  ├─ tunnel-client → MCPサーバー（stdio）
  ├─ GitHub App認証・GitHub API操作
  └─ タスク・PRの状態管理
       │ 内部HTTP
       ▼
worker コンテナ
  ├─ Go / Node.js / Python / Git
  └─ 作業コピー・コマンド実行・ジョブログ
```

`control`はリポジトリのコードを実行せず、`worker`にはGitHub App秘密鍵やTunnelのAPIキーを渡しません。
ホストのホームディレクトリ、既存のリポジトリ、Dockerソケットはマウントせず、ホスト向けのポートも公開しません。

変更の公開は`control`がGitHub Git Database APIで行います。`worker`にpush用のトークンを持たせる方式ではありません。

## 導入

必要なものは、Docker環境、対象リポジトリにインストールしたGitHub App、OpenAI Secure MCP Tunnel、カスタムMCPを利用できるChatGPTアカウントです。
Mac + OrbStackを想定しています。Docker Composeは2.33.1以降が必要です。

**最初に、利用するChatGPTアカウントでカスタムMCPとTunnel接続の作成画面に進めることを確認してください。**
画面や提供条件には差異があるため、特定のプランや「Add」ボタンだけで利用可否を判断しません。
確認方法とGitHub Appの権限設定は[セットアップガイド](docs/setup.md)にまとめています。

設定に必要なIDと鍵を準備した後、次を実行します。

```bash
git clone https://github.com/rhty/chatgpt-github-agent.git
cd chatgpt-github-agent
bash scripts/configure.sh
bash scripts/start.sh
```

`AGENT_READY`が表示されたら、ChatGPTのカスタムMCP接続で対象のTunnelを選択します。
その後、テスト用リポジトリでPR作成とコメント対応を確認します。

## 使い方

接続名を`GitHub Dev Agent`とした場合の依頼例です。`OWNER/REPOSITORY`は許可したリポジトリ名へ置き換えてください。

```text
GitHub Dev Agentを使って、OWNER/REPOSITORYのIssue 12を実装してください。
作業IDはissue-12とします。関連コードを確認し、テストを実行して、
結果を確認したうえでDraft PRを作成してください。マージはしないでください。
```

レビュー後は、同じPRと作業IDを指定して続けます。

```text
issue-12のPRに付いた新しいレビューコメントとCI結果を確認してください。
必要な修正とテストを行い、同じPRを更新して対応内容を返信してください。
```

初回確認と実装依頼のテンプレートは[prompts/](prompts/)にあります。
タスクの状態とジョブログはMCP経由で取得できます。ホストやTunnel自体が停止した場合は、ローカルの診断が必要です。

## 運用コマンド

```bash
bash scripts/start.sh      # 起動・再開と接続チェック
bash scripts/stop.sh       # 停止（保存済みデータは維持）
bash scripts/doctor.sh     # 接続できない場合の診断
bash scripts/add-repo.sh   # 許可リポジトリを追加
```

リポジトリ追加時は、GitHub Appのインストール設定でも対象を許可し、実行中の作業を止めてから再起動します。
同じTunnel IDで複数のクライアントを同時に動かさないでください。

## 制約とセキュリティ

workerは1つで、同時コマンド実行も1つです。タスク間はディレクトリを分けていますが、セキュリティ上の隔離ではありません。
外向き通信は依存取得のため許可しています。信頼できないコードや複数利用者を受け入れる実行基盤には適していません。

元リポジトリはソースのスナップショットとして取得します。完全なGit履歴、submodule、Git LFS、symlink、自動rebaseには対応していません。
マージ、force push、デフォルトブランチへの直接反映、workflow変更を公開するツールは提供しません。
ただし、Appの`Contents: write`自体が作業ブランチ限定になるわけではありません。既存CIやデプロイ設定も確認してください。

このサーバーはモデル推論APIを呼びませんが、ChatGPTやTunnelなど外部サービスの利用条件・上限・料金を変更するものではありません。
コードやログはツール結果としてChatGPTへ送信されます。認証情報と実行環境の境界は[SECURITY.md](SECURITY.md)を参照してください。

## 開発・検証

```bash
python3 -m unittest discover -s tests -v
```

GitHub APIはテスト内で模擬します。実際のGitHub App、MCP、Tunnelを通した導入確認は[VALIDATION.md](VALIDATION.md)の手順で別途行います。

## ドキュメント

| 文書 | 内容 |
|---|---|
| [セットアップ](docs/setup.md) | ChatGPTの事前確認、GitHub App、Tunnel、起動、接続テスト |
| [セキュリティ](SECURITY.md) | 認証情報、実行環境、公開操作、ネットワークの境界 |
| [検証](VALIDATION.md) | 自動テストと実接続チェック |
| [プロンプト](prompts/) | 接続テスト、レビュー対応、実装依頼のテンプレート |

## ライセンス

[MIT](LICENSE)
