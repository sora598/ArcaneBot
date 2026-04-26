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
SEA_BEAST_PING_TASKS: dict[int, asyncio.Task] = {}

PERIOD_CHOICES = [
    app_commands.Choice(name="AM", value="AM"),
    app_commands.Choice(name="PM", value="PM"),
]


class SeaBeastHuntView(discord.ui.View):
    def __init__(self, host_id: int, start_utc: datetime):
        super().__init__(timeout=None)
        self.host_id = host_id
        self.start_utc = start_utc

    @discord.ui.button(label="Cancel Hunt", style=discord.ButtonStyle.danger, custom_id="seabeasthunt_cancel")
    async def cancel_hunt(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(
                "Only the person who created this Sea Beast Hunt can cancel it.",
                ephemeral=True,
                delete_after=30,
            )
            return

        message = interaction.message
        if message is None:
            await interaction.response.send_message(
                "I couldn't find the hunt message to cancel.",
                ephemeral=True,
                delete_after=30,
            )
            return

        if datetime.now(timezone.utc) >= self.start_utc:
            await interaction.response.send_message(
                "This Sea Beast Hunt has already started and can no longer be cancelled.",
                ephemeral=True,
                delete_after=30,
            )
            return

        reminder_task = SEA_BEAST_PING_TASKS.pop(message.id, None)
        if reminder_task and not reminder_task.done():
            reminder_task.cancel()

        for child in self.children:
            child.disabled = True

        embed = message.embeds[0] if message.embeds else discord.Embed(title="Sea Beast Hunt Announcement")
        embed.color = discord.Color.red()
        embed.add_field(name="Status", value="Cancelled", inline=False)
        embed.set_footer(text="This Sea Beast Hunt was cancelled by the host.")

        await interaction.response.edit_message(embed=embed, view=self)


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
    now_local_slot = now_local.replace(second=0, microsecond=0)
    if start_local < now_local_slot:
        start_local += timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    unix_ts = int(start_utc.timestamp())

    now_utc = datetime.now(timezone.utc)
    seconds_until_start = max(0, int((start_utc - now_utc).total_seconds()))
    minutes_until_start = max(0, int(seconds_until_start / 60))
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

    view = SeaBeastHuntView(host_id=interaction.user.id, start_utc=start_utc)
    announcement_view = view if seconds_until_start > 0 else None

    if ping_text:
        await interaction.response.send_message(content=ping_text, embed=embed, view=announcement_view)
    else:
        await interaction.response.send_message(embed=embed, view=announcement_view)

    posted_message = await interaction.original_response()

    async def _remove_cancel_button_once_started() -> None:
        try:
            await posted_message.edit(view=None)
        except discord.DiscordException:
            return

    if BOT is not None and notify_role and seconds_until_start == 0:
        await _remove_cancel_button_once_started()
        channel = interaction.channel
        if channel is None:
            try:
                channel = await BOT.fetch_channel(interaction.channel_id)
            except discord.DiscordException:
                channel = None

        if channel is not None:
            try:
                await channel.send(
                    f"{notify_role.mention} 🚨 The Sea Beast Hunt hosted by {interaction.user.mention} is starting **now**! "
                    f"[Join Server]({link})"
                )
            except discord.DiscordException as exc:
                print(f"Immediate sea beast ping failed: {exc}")

    if BOT is not None and notify_role and seconds_until_start > 0:
        t30_delay = max(0, seconds_until_start - (30 * 60)) if seconds_until_start > 30 * 60 else None
        start_delay = seconds_until_start

        async def _send_ping(message_text: str):
            role = get_guild_notify_role(interaction.guild)
            if role is None:
                return
            channel = interaction.channel
            if channel is None:
                try:
                    channel = await BOT.fetch_channel(interaction.channel_id)
                except discord.DiscordException:
                    return
            await channel.send(message_text)

        async def _schedule_ping():
            try:
                if t30_delay is not None:
                    await asyncio.sleep(t30_delay)
                    await _send_ping(
                        f"{notify_role.mention} ⏰ The Sea Beast Hunt hosted by {interaction.user.mention} starts in **30 minutes**! "
                        f"[Join Server]({link})"
                    )

                    remaining = max(0, start_delay - t30_delay)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                else:
                    await asyncio.sleep(start_delay)

                await _remove_cancel_button_once_started()
                await _send_ping(
                    f"{notify_role.mention} 🚨 The Sea Beast Hunt hosted by {interaction.user.mention} is starting **now**! "
                    f"[Join Server]({link})"
                )
            except asyncio.CancelledError:
                return
            except discord.DiscordException as exc:
                print(f"Scheduled sea beast ping failed: {exc}")
            finally:
                SEA_BEAST_PING_TASKS.pop(posted_message.id, None)

        SEA_BEAST_PING_TASKS[posted_message.id] = BOT.loop.create_task(_schedule_ping())


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
