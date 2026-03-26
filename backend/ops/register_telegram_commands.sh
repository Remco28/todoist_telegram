#!/usr/bin/env bash
set -euo pipefail

TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
if [[ -z "${TELEGRAM_BOT_TOKEN}" ]]; then
  echo "TELEGRAM_BOT_TOKEN is required." >&2
  exit 1
fi

TELEGRAM_API_BASE="${TELEGRAM_API_BASE:-https://api.telegram.org}"
DRY_RUN="${DRY_RUN:-0}"

read -r -d '' COMMANDS_JSON <<'JSON' || true
[
  {"command":"start","description":"Link this chat"},
  {"command":"today","description":"Show what needs attention today"},
  {"command":"urgent","description":"Show high-priority items"},
  {"command":"web","description":"Open the web workbench"}
]
JSON

echo "Registering Telegram bot commands:"
echo "${COMMANDS_JSON}"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "DRY_RUN=1 set; skipping Telegram API call."
  exit 0
fi

response="$(curl -fsS \
  -X POST "${TELEGRAM_API_BASE}/bot${TELEGRAM_BOT_TOKEN}/setMyCommands" \
  -H "Content-Type: application/json" \
  -d "{\"commands\":${COMMANDS_JSON}}")"

echo "${response}"

if [[ "${response}" != *'"ok":true'* ]]; then
  echo "Telegram command registration did not return ok=true." >&2
  exit 1
fi

echo "Telegram commands registered successfully."
echo "Clients may take a minute or two to refresh the command list."
