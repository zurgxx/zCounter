# zCounter

Simple Codex quota CLI for accounts managed by `loongphy/codex-auth`.

## Usage

```bash
python3 -m zcounter.cli
python3 -m zcounter.cli --json
python3 -m zcounter.ui
```

### Desktop UI (v0.1)

`python3 -m zcounter.ui` opens a small always-on-top Tkinter window. It shows one
line per Codex account (email, 5-hour and weekly remaining %, reset estimate) and
refreshes every 60 seconds. Failed fetches keep the last successful values and
mark the row as `stale` or show a short error hint.

Requires a graphical display (X11/Wayland on Linux, or native GUI on macOS/Windows).

The v0.1 implementation uses `codex-auth` as the management data source:

- Reads `~/.codex/accounts/registry.json`.
- Matches `~/.codex/accounts/*.auth.json` by ChatGPT account ID.
- Calls `https://chatgpt.com/backend-api/wham/usage`.

If `CODEX_HOME` is set, zCounter reads `${CODEX_HOME}/accounts/registry.json`
and `${CODEX_HOME}/accounts/*.auth.json` instead of `~/.codex/...`.

## JSON Output

`--json` prints one normalized object per account. Main fields:

- `provider`: currently always `codex`.
- `email`: account email from the codex-auth registry or token identity.
- `plan`: plan label from the registry or usage response.
- `chatgpt_account_id`: account ID used for matching and API requests.
- `five_hour`: normalized 5-hour quota window, or `null`.
- `weekly`: normalized weekly quota window, or `null`.
- `source`: currently `wham-usage` or `codex-auth-registry`.
- `updated_at`: UTC timestamp for the snapshot.
- `error`: account-specific error string, or `null`.

Each quota window contains `used_percent`, `remaining_percent`, `reset_at`, and
`window_minutes`.

## Error Model

The CLI is designed to exit `0` in normal diagnostic cases and report failures
per account via the `error` field. Missing registry files, missing auth files,
401/403 responses, network failures, and usage response shape changes should not
crash the whole command.

## Limitations and Safety

v0.1 does not refresh expired tokens. If the usage API returns 401/403, refresh
the account with Codex/codex-auth and run zCounter again.

`wham/usage` is not a stable public API. Its endpoint or response shape may
change without notice.

Tokens are used only for the request header and are not printed.
Be careful when sharing terminal screenshots because account emails, account IDs,
quota values, and error messages may still be visible.
