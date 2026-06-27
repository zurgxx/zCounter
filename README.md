# zCounter

[`loongphy/codex-auth`](https://github.com/loongphy/codex-auth) で管理している Codex アカウント、手動 Cookie header を設定した Cursor アカウント、Claude Code / Claude Pro の OAuth 認証情報を使った Claude アカウントのクォータ残量を、CLI または常時表示 UI で確認するツールです。

## 使い方

```bash
python3 -m zcounter.cli
python3 -m zcounter.cli --json
python3 -m zcounter.ui
```

### デスクトップ UI（v0.3）

デスクトップ UI は `pywebview` を使います。Ubuntu / WSLg では初回のみ追加依存を
インストールしてください。

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[desktop]'
.venv/bin/python -m zcounter.ui
```

- 各アカウントをカードで表示（アカウント名、プラン、主枠・副枠の残量 %、リセット時刻）
- 残量に応じて `Safe` / `Warning` / `Critical` を表示
- `Refresh` ボタンと 5 分ごとの自動更新（Claude OAuth API のレート制限を避けるため CodexBar と同じ間隔）
- 取得に失敗した行は、直前の成功値を残して `Stale` または `Error` として表示

UI のデザイン検討用静的モックは `docs/mockups/` に置く（運用ルールはローカル `AGENTS.md`）。

Windows 11 の WSLg 上でも起動できます。Ubuntu 以外では、ディストリビューションに
応じた GTK / WebKitGTK パッケージを追加してください。

## データの読み方（v0.2）

Codex は `codex-auth` の管理データを参照します。

- `~/.codex/accounts/registry.json` を読む
- ChatGPT アカウント ID で `~/.codex/accounts/*.auth.json` と突き合わせる
- `https://chatgpt.com/backend-api/wham/usage` を呼び出す
- UI 向けに `https://chatgpt.com/backend-api/wham/rate-limit-reset-credits` も呼び出し、蓄積リセット残数を取得する（失敗時は usage 表示のみ継続）

環境変数 `CODEX_HOME` が設定されている場合は、`~/.codex/...` の代わりに `${CODEX_HOME}/accounts/...` を参照します。

Cursor は v0.2 では手動 Cookie header 設定のみ対応します。ブラウザ Cookie の自動探索、Keychain / secret store、複数 Cursor アカウントは未対応です。

Cursor config の読み込み順は次のとおりです。

1. `ZCOUNTER_CURSOR_CONFIG`
2. `$XDG_CONFIG_HOME/zcounter/cursor.toml`
3. `~/.config/zcounter/cursor.toml`

config 形式:

```toml
[cursor]
enabled = true
cookie_header = ""
```

`cookie_header` は secret として扱ってください。設定ファイルは `chmod 600` などで、自分以外が読めない権限にすることを推奨します。config が存在しない、`enabled = false`、または `cookie_header` が空の場合、Cursor 行は表示されません。

`cookie_header` は `cursor.toml` を手動で編集しても設定できます。DevTools の **Copy as cURL** から Cookie だけを抜き出す場合は、`scripts/update_cursor_cookie.py` を使えます。

1. ブラウザで Cursor にログインする
2. DevTools → Network で `/api/auth/me` または `/api/usage-summary` のリクエストを選ぶ
3. **Copy as cURL**
4. WSL で次を実行する:

```bash
python3 scripts/update_cursor_cookie.py
```

5. Copy as cURL の出力をそのまま貼り付ける
6. `Ctrl+D` で入力を終了する
7. `~/.config/zcounter/cursor.toml` が作成または更新される
8. `python3 -m zcounter.cli` で Cursor 行が表示されることを確認する

スクリプトは Cookie の値そのものは表示しません。書き込み先パス、Cookie 文字列の長さ、`contains_workos` などの検査結果のみを標準出力します。

**注意（secret）**

- **`WorkosCursorSessionToken` などの Cookie / トークンは secret です。** チャット、Issue、スクショに貼らないでください。
- Cursor からログアウトすると Cookie が無効になることがあります。期限切れや無効な Cookie のときは、zCounter が `cursor session is invalid or expired` のようなエラーを表示することがあります。その場合は上記の手順で Cookie を取り直してください。

暗黙パスの config が壊れている場合、または `ZCOUNTER_CURSOR_CONFIG` で明示した path が存在しない・壊れている場合は、secret を含まない Cursor error 行を表示します。

Claude は Claude Code が保存する OAuth 認証情報を参照します。

- `~/.claude/.credentials.json` を読む
- `https://api.anthropic.com/api/oauth/usage` で 5 時間枠 / 7 日枠の使用率を取得する
- `https://api.anthropic.com/api/oauth/profile` でメールアドレスとプラン名を補完する

環境変数 `CLAUDE_CONFIG_DIR` が設定されている場合は、`~/.claude/.credentials.json` の代わりに `${CLAUDE_CONFIG_DIR}/.credentials.json` を参照します。

**取得できる情報（Claude Code / Claude Pro OAuth）**

- 5 時間枠の使用率とリセット時刻
- 7 日枠の使用率とリセット時刻
- Pro / Max などのプラン名
- メールアドレス

**現状取得できない / 未対応**

- Claude Web UI 専用の Cookie 認証（手動設定なし）
- Web UI のみで利用しているアカウントで Claude Code 未ログインの場合
- トークンの自動更新（期限切れ時は Claude Code 側で再ログインが必要）

認証ファイルや API トークンは表示・ログ出力しません。認証情報が無い、期限切れ、API 応答形式の変化などは Claude 行の `error` に載せ、他 provider には影響しません。Cursor と違い、Claude は config の有無に関わらず常に 1 行表示します（未ログイン時は `claude credentials were not found` などのエラー行）。

トークン期限切れや 401 / 403 の場合は `Claude Code login required or token expired` を表示します。

## JSON 出力

`--json` を付けると、アカウントごとに正規化した JSON を 1 件ずつ出力します。主なフィールドは次のとおりです。

| フィールド | 内容 |
|-----------|------|
| `provider` | `codex`、`cursor`、または `claude` |
| `email` | レジストリまたはトークン情報から得たメールアドレス |
| `plan` | レジストリまたは usage 応答のプラン名 |
| `chatgpt_account_id` | 突き合わせ・API 呼び出しに使うアカウント ID |
| `provider_account_id` | provider 側のアカウント ID。Cursor では `auth/me` の `sub` |
| `five_hour` | 5 時間枠のクォータ（正規化済み）。無い場合は `null` |
| `weekly` | 週枠のクォータ（正規化済み）。無い場合は `null` |
| `primary` | provider 汎用の主クォータ枠 |
| `secondary` | provider 汎用の副クォータ枠 |
| `primary_label` | 主クォータ枠の表示ラベル |
| `secondary_label` | 副クォータ枠の表示ラベル |
| `source` | `wham-usage`、`codex-auth-registry`、`cursor-usage-summary`、`claude-usage` など |
| `updated_at` | スナップショット取得時刻（UTC） |
| `error` | アカウント単位のエラー文字列。正常時は `null` |
| `warnings` | secret を含まない警告文字列 |
| `details` | provider 固有の補助情報。Cookie や request header、raw response は含めない |

各クォータ枠（`five_hour` / `weekly`）には、次の値が入ります。

- `used_percent` … 使用率（%）
- `remaining_percent` … 残量（%）
- `reset_at` … リセット予定時刻
- `window_minutes` … 枠の長さ（分）

Web UI の日付表示は **年なし**（例: `6/28(日) 9:36`）。同日の 5 時間枠は `13:59` のみ。Codex の蓄積リセット（`Reset Credits` / `Expires`）は残数 > 0 のときだけ表示し、Expires は曜日＋時刻（JST）を「、」で並べる（例: `7/12(日) 13:03、7/27(月) 9:39`）。

## エラーの扱い

CLI は、通常の診断用途では **終了コード 0** のまま動く想定です。  
レジストリや auth ファイルの欠落、401 / 403、ネットワーク障害、usage 応答形式の変化などは、コマンド全体を落とさず、各アカウントの `error` フィールドに載せます。

UI でも同様に、取得失敗時は可能な限り直前の表示を残します。

## 制限と注意

- **v0.2 は期限切れトークンや Cookie を自動更新しません。** usage API が 401 / 403 を返した場合は、Codex / codex-auth 側でアカウントを更新するか、Cursor config の Cookie header を更新してから、再度 zCounter を実行してください。
- **`wham/usage` は安定した公開 API ではありません。** エンドポイントやレスポンス形式が予告なく変わる可能性があります。
- **`wham/rate-limit-reset-credits` も同様に非公開 API です。**
- **Cursor の usage-summary / auth/me も安定した公開 API ではありません。** エンドポイントやレスポンス形式が予告なく変わる可能性があります。
- **Claude の oauth/usage / oauth/profile も安定した公開 API ではありません。** エンドポイントやレスポンス形式が予告なく変わる可能性があります。
- **トークンや Cookie はリクエストヘッダにのみ使い、画面やログには出しません。**
- ターミナルのスクショや JSON の共有時には、メールアドレス・アカウント ID・残量・エラーメッセージなどが写る点に注意してください。
