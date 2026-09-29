# 接続の切断と復旧

## この変更で対処する故障経路

旧構成では、`tunnel-client`とMCPサーバーが1本のstdio接続を共有していました。実運用ログで、次の順序の記録を確認しています。

```text
command response deadline reached; dropping without posting a response
stdio MCP command failed; requesting tunnel-client shutdown
reason="stdio MCP command stdin write failed"
error="write |1: file already closed"
stop tunnel-client: context deadline exceeded
```

共有パイプへの書き込み失敗がトンネル全体の終了要求につながることは、使用バージョンの[stdio実装](https://github.com/openai/tunnel-client/blob/a390c168ff1b2d14e73a95991c186c6aba3ff5a0/pkg/mcpclient/stdio_command.go)でも確認できます。

ただし、パイプを最初に閉じた分岐や、個々のChatGPTの502エラーとの対応まで、このログだけで確定したわけではありません。ポーリング・TLS接続のタイムアウトも記録されていますが、通信経路、ホストの休止、リソース不足のどれが最初の原因かは未確定です。

上流の[Issue #34](https://github.com/openai/tunnel-client/issues/34)には似た過去の不具合がありますが、通常の要求に対する修正は既に取り込まれています。本件を「古い版なので最新版にすれば直る」と扱いません。

## 現在の構成

```text
controlコンテナ
  runtime.py
    ├─ MCPサーバー: http://127.0.0.1:8081/mcp
    └─ tunnel-client: MCP_SERVER_URLで上記へ接続
                       health/adminは127.0.0.1:8080
```

MCPは`mcp==1.30.0`のstateless Streamable HTTPとJSON応答を使います。別の要求が共有のstdin/stdoutを閉じる経路を使いません。HTTPセッションIDは発行せず、タスク・ジョブ・PRの状態は従来の永続ストレージで管理します。

これは要求単位の接続寿命を分ける対策で、インターネットの切断やOpenAI側の障害、ホストの停止まで解消するものではありません。タイムアウトした処理が取り消された保証もありません。

MCPは**同じcontrolコンテナのloopbackだけ**で待ち受けます。`0.0.0.0`への変更、ホストへのポート公開、workerとのnetwork namespace共有はしないでください。workerへの秘密鍵の配布やGitHub権限の追加は不要です。モデル推論APIの呼び出しも追加していません。

`runtime.py`はMCPの起動を確認してからトンネルを開始し、片方の終了時はもう片方も停止して終了コード1を返します。既存のCompose再起動ポリシーで両方を起動し直す設計です。書き込み要求を無条件で自動再実行する仕組みではありません。

## 既存環境への適用

処理中のジョブを終えてから、ホスト側のエージェントのリポジトリで実行します。

```bash
git pull --ff-only && bash scripts/start.sh
```

今回はDockerイメージ内の実装が変わるため、pullだけでは反映されません。`start.sh`がビルドと再起動を行います。鍵の再発行、`.env`の作り直し、TunnelやChatGPT接続の再登録、ボリュームの削除は不要です。

起動時は従来の別プロセスでのstdio互換テストに加えて、常駐中のHTTP MCPへ実際にinitializeとtools/listを送り、次を確認してから`AGENT_READY`を表示します。

```text
MCP_HTTP_CHECK_OK 16 tools
AGENT_READY
```

`AGENT_READY`だけではChatGPTからの経路全体の成功を保証しません。続けてChatGPTで`system_status`を実行してください。

## 切断後の作業再開

1. `system_status`で接続を確認する。
2. `list_tasks`や`get_task_status`で既存タスクを確認する。新しいタスクIDでやり直さない。
3. コマンドの返答を失った場合は、既存job_idの結果を取得する。同じ論理操作を再送するときは同じrequest_idを使う。
4. PR作成の返答を失った場合は、保存状態とGitHub側を確認してから続ける。接続エラーだけを理由に「何も実行されていない」と判断しない。

常駐プロセスが正常なのに特定の会話だけでSession terminatedが続く場合、新しいチャットで同じ接続の読み取りツールを一度確認します。これで成功しても、過去の障害原因を確定したことにはなりません。

## 検証範囲

`tests/test_http_mcp_recovery.py`は実際のSDKとループバックHTTPを使い、呼び出し元のタイムアウト後もMCPプロセスが残り、同じJSON-RPC IDを使う次の呼び出しが成功すること、並行する別クライアントの応答が混ざらないこと、Host検証、初期化とツール一覧を確認します。GitHub操作は模擬し、遅延ツールはテスト内だけに登録します。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r control/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

MCP SDKがない環境ではHTTPテストはskipされます。noexecのtmpfs上では実行ファイルやネイティブ拡張を使えないため、検証用venvとTMPDIRには実行可能なローカル領域を使ってください。

このテストは公式Tunnelサービス・Docker起動全体・ホスト休止を含むエンドツーエンド再現ではありません。実環境への適用後の確認とは分けて扱います。
