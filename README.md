# Arcane Bot

Arcane Bot is a Discord slash-command bot focused on community utility features:
- Welcome flow and rules onboarding
- Role toggle posts and notification roles
- Trade listing and private trade threads
- Sea Beast Hunt announcements
- Creator voice channel controls
- Admin announcement embeds

## Features

### Welcome and Onboarding
- Set a welcome channel and redirect channel with /setwelcome
- Automatically posts a welcome embed when a member joins
- Automatically posts a redirect prompt in the configured redirect channel
- Optionally adds a role button under the rules post

### Roles and Notifications
- /notifyrole posts a role-toggle button for Sea Beast Hunt notifications
- /setreactionrole posts generic role-toggle button messages

### Trading
- /setuptrading creates and manages private trading access setup
- /createtrade creates trade listings with interactive buttons
- Per-user private trade discussion threads

### Sea Beast Hunt
- /seabeasthunt posts a hunt announcement
- Includes host-only cancel button on the posted hunt message
- Optional scheduled notification ping for the notify role

### Voice Channels
- /vc create to create creator voice channels
- /vc lock, /vc unlock, /vc hide, /vc show, /vc limit
- /vc help for quick command usage

### Announcements
- /announce sends anonymous embed announcements to a target channel

## Project Structure

- src/main.py: bot entrypoint and extension loading
- src/cogs/: slash command modules
- src/*.json: persistent runtime storage files
- tests/: pytest tests

## Requirements

- Python 3.11+
- A Discord bot application and token

Main Python packages:
- discord.py
- python-dotenv
- pytest (for tests)

## Setup

1. Create and activate a virtual environment.

   Windows PowerShell example:

       python -m venv .venv
       .\.venv\Scripts\Activate.ps1

2. Install dependencies.

       pip install discord.py python-dotenv pytest

3. Create a .env file in the project root with:

       BOT_TOKEN=your_discord_bot_token_here

4. Ensure your bot has required intents and permissions in the Discord Developer Portal:
- Server Members Intent enabled
- Permissions for sending messages, managing roles, and managing channels where needed

## Run

From the project root:

    python src/main.py

On startup, the bot loads cogs and syncs slash commands globally and per guild.

## Tests

Run the test suite from the project root:

    python -m pytest -q .

## Slash Commands

General:
- /help
- /announce

Welcome:
- /setwelcome

Roles:
- /notifyrole
- /setreactionrole

Trading:
- /setuptrading
- /createtrade

Sea Beast Hunt:
- /seabeasthunt

Voice:
- /vc help
- /vc create
- /vc lock
- /vc unlock
- /vc hide
- /vc show
- /vc limit

## Data Files

The bot persists configuration and runtime data in JSON files under src:
- welcome_config.json
- notify_roles.json
- reaction_role_posts.json
- trading_config.json
- active_trades.json
- voice_owners.json
- item_list.json
- reaction_roles_config.json

## Troubleshooting

If slash commands do not update:
- restart the bot
- verify the bot token and guild membership
- wait for global command propagation if needed

If a command appears stuck on thinking:
- check bot console logs for runtime exceptions
- verify bot permissions in target channels
- confirm role hierarchy allows role assignment when using role commands

## Notes

- Most admin-only flows validate permissions before applying changes.
- Ephemeral interaction responses are configured to auto-delete after 30 seconds where supported.
