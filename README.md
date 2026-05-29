# zCounter

[`loongphy/codex-auth`](https://github.com/loongphy/codex-auth) で管理している Codex アカウントのクォータ残量を、CLI または常時表示 UI で確認するツールです。

## 使い方

```bash
python3 -m zcounter.cli
python3 -m zcounter.cli --json
python3 -m zcounter.ui
```

### デスクトップ UI（v0.1）

`python3 -m zcounter.ui` で、小さな常時最前面ウィンドウを開きます。

- 各 Codex アカウントを 1 行で表示（メールアドレス、5 時間枠・週枠の残量 %、リセット時刻［ローカル］）
- 60 秒ごとに自動更新
- 取得に失敗した行は、直前の成功値を残して `stale` または短いエラー表示にする

Linux では X11 / Wayland などのグラフィカル環境が必要です。macOS / Windows では通常の GUI 環境で動作します。  
Tkinter を使うため、Linux では `python3-tk` などのパッケージが別途必要な場合があります。

## データの読み方（v0.1）

v0.1 は `codex-auth` の管理データを参照します。

- `~/.codex/accounts/registry.json` を読む
- ChatGPT アカウント ID で `~/.codex/accounts/*.auth.json` と突き合わせる
- `https://chatgpt.com/backend-api/wham/usage` を呼び出す

環境変数 `CODEX_HOME` が設定されている場合は、`~/.codex/...` の代わりに `${CODEX_HOME}/accounts/...` を参照します。

## JSON 出力

`--json` を付けると、アカウントごとに正規化した JSON を 1 件ずつ出力します。主なフィールドは次のとおりです。

| フィールド | 内容 |
|-----------|------|
| `provider` | 現在は常に `codex` |
| `email` | レジストリまたはトークン情報から得たメールアドレス |
| `plan` | レジストリまたは usage 応答のプラン名 |
| `chatgpt_account_id` | 突き合わせ・API 呼び出しに使うアカウント ID |
| `five_hour` | 5 時間枠のクォータ（正規化済み）。無い場合は `null` |
| `weekly` | 週枠のクォータ（正規化済み）。無い場合は `null` |
| `source` | 現在は `wham-usage` または `codex-auth-registry` |
| `updated_at` | スナップショット取得時刻（UTC） |
| `error` | アカウント単位のエラー文字列。正常時は `null` |

各クォータ枠（`five_hour` / `weekly`）には、次の値が入ります。

- `used_percent` … 使用率（%）
- `remaining_percent` … 残量（%）
- `reset_at` … リセット予定時刻
- `window_minutes` … 枠の長さ（分）

## エラーの扱い

CLI は、通常の診断用途では **終了コード 0** のまま動く想定です。  
レジストリや auth ファイルの欠落、401 / 403、ネットワーク障害、usage 応答形式の変化などは、コマンド全体を落とさず、各アカウントの `error` フィールドに載せます。

UI でも同様に、取得失敗時は可能な限り直前の表示を残します。

## 制限と注意

- **v0.1 は期限切れトークンを自動更新しません。** usage API が 401 / 403 を返した場合は、Codex / codex-auth 側でアカウントを更新してから、再度 zCounter を実行してください。
- **`wham/usage` は安定した公開 API ではありません。** エンドポイントやレスポンス形式が予告なく変わる可能性があります。
- **トークンはリクエストヘッダにのみ使い、画面やログには出しません。**
- ターミナルのスクショや JSON の共有時には、メールアドレス・アカウント ID・残量・エラーメッセージなどが写る点に注意してください。
