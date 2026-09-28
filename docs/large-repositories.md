# 大きなリポジトリの取り込み

`start_task`はGitHubのコミットに対応するソースアーカイブを取得します。
圧縮48 MiB・展開160 MiB・1ファイル8 MiBに固定されていた旧版では、
データや画像を含むリポジトリの準備が`Response exceeds configured size limit`などで失敗します。
この上限はエージェントの取り込み制限であり、ChatGPTのメッセージ枠ではありません。

## 更新する

実行中の作業を終え、エージェントのリポジトリで次を実行します。
修正がmainへマージされた後に行ってください。

```bash
git switch main &&
git pull --ff-only &&
bash scripts/start.sh
```

設定スクリプトの再実行、鍵の再発行、MCP接続の作り直しは不要です。
既存の`.env`に下記の設定がなくても、Composeの既定値が適用されます。
`docker compose down -v`やタスク状態の削除は行わないでください。

`AGENT_READY`の後、ChatGPTから`list_tasks`で失敗した作業を探し、
**同じrepo・task_idで`start_task`を再実行**します。
`preparing`のタスクは、保存済みのbase SHAを使って準備を再試行します。
準備済みのタスクは既存の作業コピーを返し、編集を上書きしません。
PR作成に成功したと報告する前に、実際の`publish_pr`の結果を確認してください。

## 制限を変更する

これはソース取り込み専用の制限です。既定値は次のとおりです。
単位はMiB（1 MiB = 1,048,576 bytes）です。

| 環境変数 | 既定値 | 対象 |
|---|---:|---|
| `SOURCE_MAX_ARCHIVE_MIB` | 512 | 圧縮アーカイブ。controlとworkerの両方に適用 |
| `SOURCE_MAX_TOTAL_MIB` | 2048 | 展開する通常ファイルの合計 |
| `SOURCE_MAX_FILE_MIB` | 128 | 展開する個々の通常ファイル |

変更が必要な場合だけ`.env`へ正の整数を設定し、`scripts/start.sh`で反映します。
上限は無効化せず、必要量とホストの空きディスク容量に合わせてください。

アーカイブの取得は固定サイズのチャンクでcontrolの状態ボリューム上の一時ファイルへ書き込みます。
workerにはBase64/JSONではなく、Content-Length付きのバイナリHTTPで転送します。
workerも状態ボリューム上の一時ファイルを使い、各ソースファイルを分割して展開します。
そのため、圧縮アーカイブ全体を複数のbytes／Base64文字列として同時に保持しません。
一時アーカイブは成功・失敗の両方で閉じて削除します。メモリ上の`/tmp`は使用しません。

取り込み中はcontrol・workerそれぞれの圧縮コピー、展開後の作業コピー、Gitオブジェクトの
ディスク領域が必要です。タスクの作業コピーは完了後も保持されます。
これは無制限の容量や定常メモリ使用量を保証するものではありません。
Gitのスナップショット作成など、転送以外の処理でも資源を使用します。

## 変更していない境界

- GitHub Appの鍵・トークンはworkerに渡しません。
- symlink、submodule、Git LFS、パストラバーサルの拒否を維持します。
- 取り込みは25,000エントリまでです。
- **PRの公開差分は引き続き1ファイル8 MiB・合計12 MiB・200ファイルまでです。**
  大きな既存ファイルを読み込めることと、大きな変更を公開できることは別です。
  変更していない大きなファイルは公開差分に含めません。
- 通常のJSON RPCの72 MiB上限を拡大して回避する方式ではありません。
  旧Base64取り込みRPCは小さな互換経路として残り、本番の`start_task`は使用しません。
- ワーカーは共有で、タスク同士のセキュリティ隔離を追加したものではありません。

## 失敗を確認する

`list_tasks`と`get_task_status`は、準備に失敗したタスクでも次を返します。

- `preparation_stage`: `download`／`worker_import`／`complete`
- `preparation_error`: 最後の準備エラー
- `source_archive_bytes`: ダウンロード完了時の圧縮サイズ。未完了ならnull

容量エラーには対象段階、上限の設定名、バイト数を含めます。
大きなコミットのpatchを取り込まないよう、ベースコミット情報はGit refs／Git commit APIで取得します。
旧版の保存済みタスクは追加フィールドを持たないため、最初はnullでも異常ではありません。

準備は同期処理です。低速回線などでMCP側の待機が終わった場合も、
新しいtask_idを増やしたり成功と仮定したりせず、状態を確認して同じtask_idで再試行してください。

## 検証

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_source_import.py`は、容量制限、認証ヘッダーを転送しないリダイレクト、
途中切断、準備失敗の記録と再試行、大きな未変更ファイルの保持を検証します。
実際に48 MiBを超える圧縮アーカイブをループバックHTTP経由でworkerへ送り、
展開した内容と公開差分を確認するテストも含みます。
GitHub APIは模擬応答であり、Dockerビルド・実際のGitHub/Tunnel・対象リポジトリでの確認とは別です。

参考: [Python urllibのファイル転送](https://docs.python.org/3/library/urllib.request.html)、
[GitHubのアーカイブ取得API](https://docs.github.com/en/rest/repos/contents#download-a-repository-archive-tar)。
