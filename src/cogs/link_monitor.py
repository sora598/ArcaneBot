from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from cogs.sea_beast_hunt import is_valid_roblox_share_link

WARNINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "warnings.json"
URL_REGEX = re.compile(r"https?://\S+", re.IGNORECASE)


def load_warnings() -> dict:
    try:
        with open(WARNINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_warnings(data: dict) -> None:
    WARNINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WARNINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_user_warnings(guild_id: int, user_id: int) -> int:
    data = load_warnings()
    return data.get(str(guild_id), {}).get(str(user_id), 0)


def increment_warnings(guild_id: int, user_id: int) -> int:
    data = load_warnings()
    g_id = str(guild_id)
    u_id = str(user_id)
    if g_id not in data:
        data[g_id] = {}
    if u_id not in data[g_id]:
        data[g_id][u_id] = 0
    data[g_id][u_id] += 1
    save_warnings(data)
    return data[g_id][u_id]


def reset_warnings(guild_id: int, user_id: int) -> None:
    data = load_warnings()
    g_id = str(guild_id)
    u_id = str(user_id)
    if g_id in data and u_id in data[g_id]:
        del data[g_id][u_id]
        if not data[g_id]:
            del data[g_id]
        save_warnings(data)


def contains_disallowed_link(content: str) -> bool:
    matches = URL_REGEX.findall(content)
    for url in matches:
        if not is_valid_roblox_share_link(url):
            return True
    return False


def ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


async def apply_warning(member: discord.Member, reason: str | None = None) -> tuple[int, str]:
    """Increment warnings and apply escalating moderation. Returns (count, action_taken)."""
    count = increment_warnings(member.guild.id, member.id)

    if count == 1:
        duration = timedelta(minutes=5)
        action = "5-minute timeout"
        try:
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason or f"Link monitor offense #{count}")
        except discord.Forbidden:
            action = "5-minute timeout"
    elif count == 3:
        duration = timedelta(hours=1)
        action = "1-hour timeout"
        try:
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason or f"Link monitor offense #{count}")
        except discord.Forbidden:
            action = "1-hour timeout"
    elif count == 5:
        action = "kick"
        try:
            await member.kick(reason=reason or f"Link monitor: 5th offense")
        except discord.Forbidden:
            action = "kick"
    else:
        action = "warning recorded"

    return count, action


class LinkMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        if message.author.bot:
            return
#        if message.author.guild_permissions.manage_messages:
#            return
        if not URL_REGEX.search(message.content):
            return
        if not contains_disallowed_link(message.content):
            return

        # Delete offending message immediately
        try:
            await message.delete()
        except discord.Forbidden:
            return
        except discord.HTTPException:
            pass

        member = message.guild.get_member(message.author.id)
        if member is None:
            return

        count, action = await apply_warning(member, reason="Sent prohibited link")

        # Vanishing channel warning
        try:
            await message.channel.send(
                f"⚠️ {message.author.mention} prohibited link detected! "
                f"This is your **{count}{ordinal(count)}** offense. Action: **{action}**.",
                delete_after=10,
            )
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        await self.on_message(after)

    @app_commands.command(name="warn", description="Manually warn a member.")
    @app_commands.describe(member="The member to warn", message="Optional reason or note to include with the warning")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        message: str | None = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True, delete_after=10
            )
            return

        await interaction.response.defer(ephemeral=True)
        note = message.strip() if message else None
        reason = f"Manual warning by {interaction.user}"
        if note:
            reason = f"{reason}: {note}"

        count, action = await apply_warning(member, reason=reason)
        warning_summary = (
            f"✅ {member.mention} has been warned. This is their **{count}{ordinal(count)}** offense. "
            f"Action: **{action}**."
        )
        if note:
            warning_summary = f"{warning_summary}\nNote: {note}"

        await interaction.followup.send(warning_summary, ephemeral=True)

        try:
            channel_note = f"\nNote: {note}" if note else ""
            await interaction.channel.send(
                f"⚠️ {member.mention} has been warned by a moderator. "
                f"This is their **{count}{ordinal(count)}** offense. Action: **{action}**.{channel_note}",
                delete_after=10,
            )
        except discord.Forbidden:
            pass

    @warn.error
    async def warn_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need **Manage Messages** permission to use this command.",
                ephemeral=True,
                delete_after=10,
            )

    @app_commands.command(name="clearwarns", description="Clear all warnings for a member.")
    @app_commands.describe(member="The member whose warnings to clear")
    @app_commands.checks.has_permissions(administrator=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True, delete_after=10
            )
            return

        reset_warnings(interaction.guild.id, member.id)

        untimeout_note = ""
        try:
            await member.timeout(None, reason=f"Warnings cleared by {interaction.user}")
            untimeout_note = " and their timeout has been removed"
        except discord.Forbidden:
            untimeout_note = ""
        except discord.HTTPException:
            untimeout_note = ""

        await interaction.response.send_message(
            f"✅ Warnings for {member.mention} have been cleared{untimeout_note}.",
            ephemeral=True,
            delete_after=10,
        )

    @clearwarns.error
    async def clearwarns_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ This command is restricted to server administrators.",
                ephemeral=True,
                delete_after=10,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(LinkMonitor(bot))

