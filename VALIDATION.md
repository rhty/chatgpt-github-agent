# 検証記録

実施日: 2026-09-27

## この作成環境で実施したもの

```bash
python -m unittest discover -s tests -v
```

結果: **41 tests / OK**。

- ファイルの読み書き、UTF-8、既存ファイルのハッシュ一致、パストラバーサル・symlinkの拒否。
- shellコマンドの開始、実行結果、終了コード、重複防止、タイムアウト、停止、再起動時の状態。
- ソースtarの取り込み、サイズ・形式制限、submodule/LFS/symlinkの拒否。
- renameのdelete/add出力、バイナリと実行属性、ローカルコミット後も差分が残ること。
- GitHubでtrackedだが.gitignoreに一致するファイルも初期スナップショットで維持すること。
- リポジトリと作業ブランチの許可検証、初回PR、同じ内容の再送、追加コミット、以前の変更を戻す処理。
- 他者のブランチ更新やclosed PRでの停止、ref更新後の通信結果不明からの復帰。
- 通常コメント・行単位コメントの投稿、再試行による二重投稿の抑止。
- task/PR/ジョブ状態の保存と再読み取り。
- opensslで生成したテスト用秘密鍵を使うJWT署名・検証と、1リポジトリ限定のトークン要求。
- **別プロセスで実際のworker HTTPサーバーを起動し、HTTP経由でソース取り込み・書き込み・コマンド実行・差分出力を確認。**

GitHub APIは模擬応答を使っています。実際のGitHubへPRやコメントを作成して確認したわけではありません。テストのキーも一時的なローカルテスト用で、ユーザーのキーではありません。

合わせてPythonソースの構文チェックと`bash -n scripts/*.sh`相当のスクリプト構文チェック、Compose YAMLの読み取りとマウント/secret設定の静的確認を行っています。**YAML確認はdocker compose configの実行と同じではありません。**

## 未実施

- Docker / OrbStack上でのイメージビルド、secretファイルの実マウント、ネットワーク分離。
- MCP SDK 1.30.0でのツール列挙・呼び出しの実通信。
- OpenAIの実Tunnelアカウントへの認証、ChatGPTからのMCP呼び出し。
- GitHub Appの実インストールを用いたAPI認証、PR作成、コメント返信、CIログ取得。
- macOSのファイル選択ダイアログと起動スクリプトの実行。
- 大規模リポジトリ・長時間連続運転・意図的な攻撃コードに対する負荷/セキュリティ検証。

## 導入先で行う確認

`scripts/start.sh`は、以下を順に行います。

1. Docker Compose設定を検査し、worker/controlをビルド。
2. worker HTTPの健康状態を確認。
3. `control/doctor.py`でGitHub App認証、許可リポジトリの初期コミット、workerに認証ファイルやDockerソケットが見えないことを確認。
4. `control/smoke_test.py`でMCP SDKのstdioクライアントを使ってMCP初期化と16ツールの登録を確認。
5. 実際のtunnel-clientを起動し、readyzを確認。

ここまで通ってもPR作成の実証ではありません。ChatGPTで`prompts/01-connection-test.txt`と`02-review-followup.txt`を実行し、GitHub上のPR、追加コミット、返信を確認します。

実接続で不一致が見つかった場合は、そのエラーをもとに修正が必要です。未検証の段階で「必ずそのまま動く」「セキュリティ監査済み」とは扱わないでください。
