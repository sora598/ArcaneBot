from __future__ import annotations

import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv


EXTENSIONS = [
    "cogs.help",
    "cogs.notify_role",
    "cogs.reaction_role_post",
    "cogs.trade_system",
    "cogs.sea_beast_hunt",
    "cogs.welcome",
    "cogs.trading_access",
    "cogs.announce",
    "cogs.voice_channels",
    "cogs.add_role",
]

SYNCED = False


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.reactions = True
    intents.message_content = True

    bot = commands.Bot(
        command_prefix="!",
        intents=intents,
        help_command=None,
    )

    @bot.event
    async def setup_hook():
        for extension in EXTENSIONS:
            await bot.load_extension(extension)

    @bot.event
    async def on_ready():
        global SYNCED

        print(f"Logged in as {bot.user}")

        if SYNCED:
            return

        try:
            # Remove any previously-synced guild commands so they don't
            # appear duplicated alongside global commands.
            for guild in bot.guilds:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
                print(f"Cleared guild commands for {guild.id}")

            synced = await bot.tree.sync()
            print(f"Globally synced {len(synced)} slash commands.")

        except Exception as error:
            print(f"Failed to sync slash commands: {error}")

        SYNCED = True

    return bot


def main():
    load_dotenv()

    TOKEN = os.getenv("BOT_TOKEN")

    if not TOKEN:
        raise ValueError("BOT_TOKEN not set.")

    bot = create_bot()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()