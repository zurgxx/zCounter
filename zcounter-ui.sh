#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -z "${DISCORD_WEBHOOK_URL:-}" ] && [ -f "${HOME}/.config/mlb-radar/discord.env" ]; then
  # shellcheck disable=SC1090
  . "${HOME}/.config/mlb-radar/discord.env"
  export DISCORD_WEBHOOK_URL
fi

exec .venv/bin/python -m zcounter.ui "$@"
