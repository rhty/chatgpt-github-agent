# 検証ガイド

## 自動テスト

リポジトリのルートで実行します。Python 3.10以降、Git、OpenSSL、Bashを使用します。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q control worker tests
for script in scripts/*.sh; do bash -n "$script"; done
```

テストでは一時ディレクトリ、テスト専用の鍵、ローカルのworker HTTPサーバーを使います。
GitHub APIは模擬し、実際のGitHubへのPR投稿やOpenAIへの接続は行いません。ユーザーの鍵は不要です。

主な検証対象は次のとおりです。

- ファイルの読み書き、UTF-8、ハッシュによる更新競合、パストラバーサル・symlinkの拒否。
- コマンド実行、終了コード、タイムアウト、停止、重複要求、再起動時の状態。
- ソース取り込み、サイズ制限、rename・バイナリ・実行属性・累積差分の公開。
- GitHub AppのJWT署名、リポジトリ限定のトークン要求、PR更新、他者の更新との競合、返信の重複防止。
- worker HTTPを通したソース取り込み、編集、コマンド実行、差分取得。
- 初期設定でのリポジトリ指定必須化、入力検証、既存設定の保護。

### ローカル検証記録

2026-09-27のドキュメント・初期設定更新時に、自動テスト45件の成功、Pythonのコンパイル、Bashスクリプトの構文チェックを確認しました。
この記録は実サービスとの統合テストやセキュリティ監査を意味しません。

## 実接続チェック

[セットアップ](docs/setup.md)の事前確認を完了し、テスト用リポジトリだけを許可してから実施します。

`scripts/start.sh`は次を順番に確認します。

| 段階 | 確認内容 |
|---|---|
| Docker | Compose設定、イメージビルド、workerのHTTPヘルスチェック |
| GitHub | App認証、許可リポジトリ、初期コミットの読み取り |
| worker | 認証ファイルとDockerソケットが見えないこと |
| MCP | SDKのstdioクライアントによる初期化と16ツールの登録 |
| Tunnel | クライアント起動とreadyz |

`AGENT_READY`まで成功しても、PRやコメントへの書き込みは未確認です。
次にChatGPTから以下を実行します。

1. [接続テスト](prompts/01-connection-test.txt)でファイル変更・コマンド検証・PR作成を行う。
2. GitHubでPRの差分、検証結果、投稿主体を確認する。
3. PRにコメントを書き、[レビュー対応](prompts/02-review-followup.txt)で追加コミットと返信を確認する。
4. CIを利用する対象では、チェック結果とジョブログの取得も別途確認する。

## 未検証の範囲

本プロジェクトの初期検証記録には、Docker/OrbStackでのビルド、実アカウントでのGitHub App認証・書き込み、
OpenAI TunnelとChatGPTを経由した実行、macOSのファイル選択ダイアログの動作確認は含まれていません。
自動テストの成功だけでこれらの成功を報告しないでください。

大規模リポジトリ、長時間連続運転、敵対的コード、マルチテナントの隔離についても検証していません。
安全性の前提は[SECURITY.md](SECURITY.md)を参照してください。
