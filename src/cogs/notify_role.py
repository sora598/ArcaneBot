from __future__ import annotations

import json
import os
from pathlib import Path

import discord
from discord import app_commands, ui
from discord.ext import commands

NOTIFY_STORE_PATH = Path(__file__).resolve().parent.parent / "notify_roles.json"
BOT: commands.Bot | None = None
NOTIFY_STORE: dict = {}


def load_notify_store() -> dict:
    try:
        with open(NOTIFY_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        with open(NOTIFY_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}


def save_notify_store(store: dict) -> None:
    with open(NOTIFY_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def can_manage_role(guild: discord.Guild, role: discord.Role) -> bool:
    if BOT is None:
        return False
    bot_member = guild.me or guild.get_member(BOT.user.id if BOT.user else 0)
    if bot_member is None:
        return False
    if role.is_default() or role.managed:
        return False
    return bot_member.top_role > role


class NotifyRoleButtonView(ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @ui.button(label="Get Notified!", style=discord.ButtonStyle.primary, custom_id="notify_role_button")
    async def notify_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("This button only works in a server.", ephemeral=True, delete_after=30)
            return

        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "The notification role no longer exists. Please ask an admin to re-run `/notifyrole`.",
                ephemeral=True,
                delete_after=30,
            )
            return

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(f"{role.mention} role removed.", ephemeral=True, delete_after=30)
            else:
                await member.add_roles(role)
                await interaction.response.send_message(
                    f"{role.mention} Role Obtained! You will be notified if someone starts a sea beast hunt!",
                    ephemeral=True,
                    delete_after=30,
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Something went wrong please try again later.",
                ephemeral=True,
                delete_after=30,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"Something went wrong while updating your role: `{e}`",
                ephemeral=True,
                delete_after=30,
            )


@app_commands.command(name="notifyrole", description="Send a notification embed with a button for Sea Beast Hunt role.")
@app_commands.describe(role="The role to assign/remove for notifications.")
@app_commands.checks.has_permissions(administrator=True)
async def notifyrole(interaction: discord.Interaction, role: discord.Role):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True, delete_after=30)
        return

    if not can_manage_role(interaction.guild, role):
        await interaction.response.send_message(
            "I can't manage that role. Make sure it isn't managed/default and that my highest role is above it.",
            ephemeral=True,
            delete_after=30,
        )
        return

    await interaction.response.defer(ephemeral=True)

    embed = discord.Embed(
        title="Sea Beast Hunt Notifications",
        description=(
            "Want to be notified when someone is organizing a Sea Beast Hunt? "
            "Click the button below to receive or remove the notification role!"
        ),
        color=discord.Color.blue(),
    )
    view = NotifyRoleButtonView(role.id)
    message = await interaction.channel.send(embed=embed, view=view)

    NOTIFY_STORE[str(message.id)] = {
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "role_id": role.id,
    }
    save_notify_store(NOTIFY_STORE)
    if BOT is not None:
        BOT.add_view(view, message_id=message.id)

    await interaction.followup.send("✅ Notification role embed posted!", ephemeral=True, delete_after=30)


@notifyrole.error
async def notifyrole_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ This command is restricted to server administrators.",
            ephemeral=True,
            delete_after=30,
        )


async def setup(bot: commands.Bot):
    global BOT, NOTIFY_STORE
    BOT = bot
    NOTIFY_STORE = load_notify_store()
    bot.tree.add_command(notifyrole)

    restored = 0
    for message_id_str, entry in NOTIFY_STORE.items():
        try:
            message_id = int(message_id_str)
            role_id = int(entry["role_id"])
            bot.add_view(NotifyRoleButtonView(role_id), message_id=message_id)
            restored += 1
        except (KeyError, ValueError, TypeError) as exc:
            print(f"Skipping notify entry {message_id_str}: {exc}")
    print(f"Restored notify-role views: {restored}")
