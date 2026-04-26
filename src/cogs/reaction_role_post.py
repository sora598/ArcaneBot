from __future__ import annotations

import json
import os
from pathlib import Path

import discord
from discord import app_commands, ui
from discord.ext import commands


REACTION_ROLE_POSTS_PATH = Path(__file__).resolve().parent.parent / "reaction_role_posts.json"


def load_reaction_role_posts() -> dict:
    """Load persisted role-post messages from disk."""
    try:
        with open(REACTION_ROLE_POSTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        with open(REACTION_ROLE_POSTS_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}


def save_reaction_role_posts(store: dict) -> None:
    """Persist role-post messages to disk."""
    with open(REACTION_ROLE_POSTS_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def can_manage_role(bot: commands.Bot, guild: discord.Guild, role: discord.Role) -> bool:
    bot_member = guild.me or guild.get_member(bot.user.id if bot.user else 0)
    if bot_member is None:
        return False
    if role.is_default() or role.managed:
        return False
    return bot_member.top_role > role


class ReactionRoleButtonView(ui.View):
    """Persistent button view used by /setreactionrole."""

    def __init__(self, bot: commands.Bot, role_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.role_id = role_id

    @ui.button(label="Get Role", style=discord.ButtonStyle.success, custom_id="setreactionrole_toggle_button")
    async def toggle_role(self, interaction: discord.Interaction, button: ui.Button):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This button only works in a server.", ephemeral=True, delete_after=30)
            return

        role = guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "This role no longer exists. Please ask an admin to repost the message.",
                ephemeral=True,
                delete_after=30,
            )
            return

        if not can_manage_role(self.bot, guild, role):
            await interaction.response.send_message(
                "I can't manage that role anymore. My highest role may be below it.",
                ephemeral=True,
                delete_after=30,
            )
            return

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(f"{role.mention} removed.", ephemeral=True, delete_after=30)
            else:
                await member.add_roles(role)
                await interaction.response.send_message(f"{role.mention} granted, you can now view the available channels in the server.\n some roles might require additional steps", ephemeral=True, delete_after=30)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to update roles. Check my role hierarchy and permissions.",
                ephemeral=True,
                delete_after=30,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Something went wrong: `{e}`", ephemeral=True, delete_after=30)


class ReactionRolePostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reaction_role_posts = load_reaction_role_posts()

    async def cog_load(self):
        restored = 0
        for message_id_str, entry in self.reaction_role_posts.items():
            try:
                message_id = int(message_id_str)
                role_id = int(entry["role_id"])
                self.bot.add_view(ReactionRoleButtonView(self.bot, role_id), message_id=message_id)
                restored += 1
            except (KeyError, ValueError, TypeError) as exc:
                print(f"Skipping reaction-role entry {message_id_str}: {exc}")
        print(f"Restored reaction-role views: {restored}")

    @app_commands.command(name="setreactionrole", description="Post a message with a button that toggles a role.")
    @app_commands.describe(
        message="The message text to post",
        role="The role to give/remove when the button is clicked",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_reactionrole(self, interaction: discord.Interaction, message: str, role: discord.Role):
        """Post a role-toggle message with a button instead of legacy reaction emojis."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True, delete_after=30)
            return

        if not can_manage_role(self.bot, interaction.guild, role):
            await interaction.response.send_message(
                "I can't manage that role. Make sure it isn't managed/default and that my highest role is above it.",
                ephemeral=True,
                delete_after=30,
            )
            return

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="Role Assignment",
            description=message,
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Click the button to get the role {role.name}.")

        view = ReactionRoleButtonView(self.bot, role.id)
        posted_message = await interaction.channel.send(embed=embed, view=view)

        self.reaction_role_posts[str(posted_message.id)] = {
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "role_id": role.id,
            "message": message,
        }
        save_reaction_role_posts(self.reaction_role_posts)
        self.bot.add_view(view, message_id=posted_message.id)

        await interaction.followup.send("✅ Role post created.", ephemeral=True)

    @set_reactionrole.error
    async def set_reactionrole_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ This command is restricted to server administrators.",
                ephemeral=True,
                delete_after=30,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRolePostCog(bot))
