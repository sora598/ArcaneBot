from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import discord
from discord import app_commands
from discord.ext import commands

from cogs.notify_role import load_notify_store

BOT: commands.Bot | None = None

PERIOD_CHOICES = [
    app_commands.Choice(name="AM", value="AM"),
    app_commands.Choice(name="PM", value="PM"),
]


def get_guild_notify_role(guild: discord.Guild) -> discord.Role | None:
    store = load_notify_store()
    for entry in store.values():
        if int(entry.get("guild_id", 0)) == guild.id:
            return guild.get_role(int(entry["role_id"]))
    return None


def is_valid_roblox_share_link(link: str) -> bool:
    try:
        parsed = urlparse(link.strip())
        if parsed.scheme != "https":
            return False
        if parsed.netloc.lower() != "www.roblox.com":
            return False
        if parsed.path.rstrip("/") != "/share":
            return False
        query = parse_qs(parsed.query)
        code = query.get("code", [""])[0].strip()
        link_type = query.get("type", [""])[0].strip()
        return bool(code) and link_type == "Server"
    except Exception:
        return False


@app_commands.command(name="seabeasthunt", description="Post an embed announcing an upcoming Sea Beast Hunt.")
@app_commands.describe(
    hour="Hour of the start time (1–12)",
    minute="Minute of the start time (0–59)",
    period="AM or PM",
    private_server_link="Roblox private server link",
)
@app_commands.choices(period=PERIOD_CHOICES)
async def sea_beast_hunt_announcement(
    interaction: discord.Interaction,
    hour: app_commands.Range[int, 1, 12],
    minute: app_commands.Range[int, 0, 59],
    period: app_commands.Choice[str],
    private_server_link: str,
):
    link = private_server_link.strip()
    if not is_valid_roblox_share_link(link):
        await interaction.response.send_message(
            "❌ Invalid link. Please provide a valid Roblox private server share link.\n"
            "It should look like: `https://www.roblox.com/share?code=...&type=Server`",
            ephemeral=True,
            delete_after=30,
        )
        return

    hour_24 = hour % 12 + (12 if period.value == "PM" else 0)
    tz = timezone(timedelta(hours=8))
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=hour_24, minute=minute, second=0, microsecond=0)
    if start_local <= now_local:
        start_local += timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    unix_ts = int(start_utc.timestamp())

    now_utc = datetime.now(timezone.utc)
    minutes_until_start = max(0, int((start_utc - now_utc).total_seconds() / 60))
    discord_time = f"<t:{unix_ts}:t>"
    discord_relative = f"<t:{unix_ts}:R>"

    notify_role = get_guild_notify_role(interaction.guild)
    ping_text = notify_role.mention if (notify_role and minutes_until_start <= 30) else None

    embed = discord.Embed(
        title="🌊 Sea Beast Hunt Announcement",
        description="A Sea Beast Hunt is being organized. Join in if you are available!",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Host", value=interaction.user.mention, inline=False)
    embed.add_field(name="Start Time", value=f"{discord_time} ({discord_relative})", inline=True)
    embed.add_field(name="Private Server", value=f"[Join Server]({link})", inline=True)
    embed.set_footer(text="Good luck and happy hunting.")

    if ping_text:
        await interaction.response.send_message(content=ping_text, embed=embed)
    else:
        await interaction.response.send_message(embed=embed)

    if BOT is not None and notify_role and minutes_until_start > 30:
        delay = (minutes_until_start - 30) * 60

        async def _schedule_ping():
            await asyncio.sleep(delay)
            role = get_guild_notify_role(interaction.guild)
            if role is None:
                return
            channel = interaction.channel
            if channel is None:
                try:
                    channel = await BOT.fetch_channel(interaction.channel_id)
                except discord.DiscordException:
                    return
            try:
                await channel.send(
                    f"{role.mention} ⏰ The Sea Beast Hunt hosted by {interaction.user.mention} starts in **30 minutes**! "
                    f"[Join Server]({link})"
                )
            except discord.DiscordException as exc:
                print(f"Scheduled sea beast ping failed: {exc}")

        BOT.loop.create_task(_schedule_ping())


@sea_beast_hunt_announcement.error
async def sea_beast_hunt_announcement_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ This command is restricted to server administrators.",
            ephemeral=True,
            delete_after=30,
        )


async def setup(bot: commands.Bot):
    global BOT
    BOT = bot
    bot.tree.add_command(sea_beast_hunt_announcement)
