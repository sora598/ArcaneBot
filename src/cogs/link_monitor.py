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
WARNINGS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "warnings_config.json"
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


def load_warnings_config() -> dict:
    try:
        with open(WARNINGS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_warnings_config(data: dict) -> None:
    WARNINGS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WARNINGS_CONFIG_PATH, "w", encoding="utf-8") as f:
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
    """Return the ordinal suffix (st, nd, rd, th) for a number."""
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


async def apply_warning(member: discord.Member, reason: str | None = None, link_text: str | None = None) -> tuple[int, str]:
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
        duration = timedelta(hours=12)
        action = "12-hour timeout"
        try:
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason or f"Link monitor offense #{count}")
        except discord.Forbidden:
            action = "12-hour timeout"
    elif count == 6:
        duration = timedelta(hours=12)
        action = "12-hour timeout"
        try:
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason or f"Link monitor offense #{count}")
        except discord.Forbidden:
            action = "12-hour timeout"
    elif count == 7:
        duration = timedelta(hours=24)
        action = "24-hour timeout"
        try:
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason or f"Link monitor offense #{count}")
        except discord.Forbidden:
            action = "24-hour timeout"
    elif count == 8:
        duration = timedelta(hours=36)
        action = "36-hour timeout"
        try:
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason or f"Link monitor offense #{count}")
        except discord.Forbidden:
            action = "36-hour timeout"
    elif count == 9:
        duration = timedelta(days=7)
        action = "1-week timeout"
        try:
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason or f"Link monitor offense #{count}")
        except discord.Forbidden:
            action = "1-week timeout"
    elif count == 10:
        action = "ban"
        try:
            await member.ban(reason=reason or f"Link monitor: 10th offense")
        except discord.Forbidden:
            action = "ban"
    else:
        action = "warning recorded"

    # Send notification to warnings channel
    await send_warning_notification(member.guild, member, count, action, reason, link_text)

    return count, action


async def send_warning_notification(
    guild: discord.Guild,
    member: discord.Member,
    count: int,
    action: str,
    reason: str | None = None,
    link_text: str | None = None,
) -> None:
    """Send a warning notification to the configured warnings channel."""
    try:
        config = load_warnings_config()
        guild_config = config.get(str(guild.id))
        
        if not guild_config or "notification_channel_id" not in guild_config:
            return
        
        channel_id = guild_config["notification_channel_id"]
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        
        embed = discord.Embed(
            title="⚠️ Member Warning",
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Member", value=f"{member.mention} ({member})", inline=False)
        embed.add_field(name="Offense Count", value=f"**{count}{ordinal(count)}** offense", inline=True)
        embed.add_field(name="Action Taken", value=f"**{action}**", inline=True)
        
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        
        if link_text:
            # Truncate link if too long for embed field
            display_link = link_text[:1024] if len(link_text) > 1024 else link_text
            embed.add_field(name="Link Sent", value=f"```{display_link}```", inline=False)
        
        embed.set_footer(text=f"User ID: {member.id}")
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass
    except discord.HTTPException:
        pass
    except Exception:
        pass


class LinkMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        if message.author.bot:
            return
        # Remove permission check - warnings should be recorded for EVERYONE
        if not URL_REGEX.search(message.content):
            return
        if not contains_disallowed_link(message.content):
            return

        # Extract the link text
        link_text = URL_REGEX.search(message.content).group()

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

        count, action = await apply_warning(member, reason="Sent prohibited link", link_text=link_text)

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

    @app_commands.command(name="setwarnschannel", description="Set the channel where warning notifications will be sent.")
    @app_commands.describe(channel="The channel to send warning notifications to (or leave empty to disable)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setwarnschannel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True, delete_after=10
            )
            return

        config = load_warnings_config()
        guild_config = config.get(str(interaction.guild.id), {})

        if channel is None:
            # Disable warnings channel
            if "notification_channel_id" in guild_config:
                del guild_config["notification_channel_id"]
                config[str(interaction.guild.id)] = guild_config
                save_warnings_config(config)
                await interaction.response.send_message(
                    "✅ Warning notifications have been **disabled**.",
                    ephemeral=True,
                    delete_after=10,
                )
            else:
                await interaction.response.send_message(
                    "❌ No warnings channel is currently set.",
                    ephemeral=True,
                    delete_after=10,
                )
        else:
            # Set warnings channel
            guild_config["notification_channel_id"] = channel.id
            config[str(interaction.guild.id)] = guild_config
            save_warnings_config(config)
            await interaction.response.send_message(
                f"✅ Warning notifications will now be sent to {channel.mention}.",
                ephemeral=True,
                delete_after=10,
            )

    @setwarnschannel.error
    async def setwarnschannel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ This command is restricted to server administrators.",
                ephemeral=True,
                delete_after=10,
            )

    @app_commands.command(name="viewwarns", description="View all members with warnings in this server.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def viewwarns(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True, delete_after=10
            )
            return

        await interaction.response.defer(ephemeral=True)

        data = load_warnings()
        guild_warnings = data.get(str(interaction.guild.id), {})

        if not guild_warnings:
            await interaction.followup.send(
                "✅ No members have warnings in this server.",
                ephemeral=True,
            )
            return

        # Sort by warning count (highest first)
        sorted_warnings = sorted(guild_warnings.items(), key=lambda x: x[1], reverse=True)

        embed = discord.Embed(
            title="📋 Server Warnings List",
            description=f"Total members with warnings: {len(sorted_warnings)}",
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc),
        )

        # Build warning list
        warning_text = ""
        for user_id, warning_count in sorted_warnings:
            try:
                user = await interaction.client.fetch_user(int(user_id))
                user_display = f"{user.mention} ({user})"
            except (discord.NotFound, discord.HTTPException):
                user_display = f"<@{user_id}> (User ID: {user_id})"

            warning_text += f"\n{user_display} — **{warning_count}{ordinal(warning_count)}** offense"

        # Split into multiple fields if too long
        if len(warning_text) > 1024:
            fields = [warning_text[i : i + 1024] for i in range(0, len(warning_text), 1024)]
            for idx, field_text in enumerate(fields, 1):
                embed.add_field(
                    name=f"Warnings (Part {idx})" if idx > 1 else "Warnings",
                    value=field_text,
                    inline=False,
                )
        else:
            embed.add_field(name="Warnings", value=warning_text, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @viewwarns.error
    async def viewwarns_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need **Manage Messages** permission to use this command.",
                ephemeral=True,
                delete_after=10,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(LinkMonitor(bot))

