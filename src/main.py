from __future__ import annotations

import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

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
]

SYNCED = False


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
        synced = await bot.tree.sync()
        print(f"Globally synced {len(synced)} slash commands.")

        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                guild_synced = await bot.tree.sync(guild=guild)
                print(f"Guild sync ({guild.id}) -> {len(guild_synced)} commands")
            except Exception as guild_error:
                print(f"Guild sync failed for {guild.id}: {guild_error}")
    except Exception as error:
        print(f"Failed to sync slash commands: {error}")

    SYNCED = True


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("BOT_TOKEN not set in environment variables.")
    bot.run(TOKEN)
