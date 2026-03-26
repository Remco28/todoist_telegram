# Telegram Command Registration

Use this runbook to register the bot's slash-command list with Telegram so clients can show:
- the `/` command picker
- the bot command menu

This project includes a helper script:
- `backend/ops/register_telegram_commands.sh`

## Required Credential

Only one credential is required:
- `TELEGRAM_BOT_TOKEN`

Use the same bot token already configured for the API service. No database credentials, app bearer token, or Telegram user login are needed.

## When To Run It

Run this when:
- setting up a new bot
- changing the supported slash commands
- updating command descriptions

You do not need to run it on every deploy unless the command list changed.

## Local Usage

From the repo root:

```bash
export TELEGRAM_BOT_TOKEN="<your_bot_token>"
./backend/ops/register_telegram_commands.sh
```

Dry-run the payload without calling Telegram:

```bash
export TELEGRAM_BOT_TOKEN="<your_bot_token>"
DRY_RUN=1 ./backend/ops/register_telegram_commands.sh
```

## Coolify / Container Usage

Inside the API container or any shell that already has `TELEGRAM_BOT_TOKEN` set:

```bash
cd /app
./ops/register_telegram_commands.sh
```

## What It Registers

The current command list is:
- `/start` - Link this chat
- `/today` - Show what needs attention today
- `/urgent` - Show high-priority items
- `/web` - Open the web workbench

Compatibility note:
- Slash `/plan`, `/focus`, and `/ask` are retired in favor of the conversation-first flow.
- Hidden `/done` remains as a deterministic fallback during migration, but it is intentionally omitted from the visible Telegram command menu.

## Verification

1. Open the Telegram chat with the bot.
2. Type `/`.
3. Confirm the command list appears.
4. Optionally verify one command such as `/today`.

Telegram clients may take a minute or two to refresh after registration.
