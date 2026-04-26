from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from .reaction_role_post import (
    ReactionRoleButtonView,
    can_manage_role,
    load_reaction_role_posts,
    save_reaction_role_posts,
)

WELCOME_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "welcome_config.json"

# Single shared dict — never reassigned, only mutated in-place so all
# references across the module always point to the same object.
WELCOME_CONFIG: dict = {}
_config_ready: bool = False


def load_welcome_config() -> None:
    """Load persisted config into the shared WELCOME_CONFIG dict in-place."""
    global _config_ready
    try:
        with open(WELCOME_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
        with open(WELCOME_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    WELCOME_CONFIG.clear()
    WELCOME_CONFIG.update(data)
    _config_ready = True


def save_welcome_config() -> None:
    """Persist the current state of the shared WELCOME_CONFIG dict."""
    with open(WELCOME_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(WELCOME_CONFIG, f, indent=2)


async def resolve_text_channel(guild: discord.Guild, channel_id: int | None) -> discord.TextChannel | None:
    if not channel_id:
        return None

    channel = guild.get_channel(int(channel_id))
    if isinstance(channel, discord.TextChannel):
        return channel

    try:
        fetched = await guild.fetch_channel(int(channel_id))
    except discord.DiscordException:
        return None

    if isinstance(fetched, discord.TextChannel):
        return fetched
    return None


@app_commands.command(name="setwelcome", description="Configure the welcome message and redirect channel for new members.")
@app_commands.describe(
    welcome_channel="Channel where the welcome message is posted",
    redirect_channel="Channel new members are directed to visit first",
    post_rules="Whether to post the server rules embed in the redirect channel (default: True)",
    role="Optional role to toggle with a button under the rules embed",
    button_text="Optional custom text for the role button on this rules message",
)
@app_commands.checks.has_permissions(administrator=True)
async def set_welcome(
    interaction: discord.Interaction,
    welcome_channel: discord.TextChannel,
    redirect_channel: discord.TextChannel,
    post_rules: bool = True,
    role: discord.Role | None = None,
    button_text: str | None = None,
):
    await interaction.response.defer(ephemeral=True)

    try:
        guild_key = str(interaction.guild_id)
        WELCOME_CONFIG[guild_key] = {
            "welcome_channel_id": welcome_channel.id,
            "redirect_channel_id": redirect_channel.id,
        }
        save_welcome_config()

        rules_embed = discord.Embed(title="📜 Server Rules", color=discord.Color.red())
        rules_embed.add_field(name="1. Be Respectful", value="Treat everyone with respect. No harassment, bullying, hate speech, or discrimination of any kind.", inline=False)
        rules_embed.add_field(name="2. No Spam or Flooding", value="Avoid sending repeated messages, excessive emojis, or unnecessary mentions.", inline=False)
        rules_embed.add_field(name="3. Keep It Appropriate", value="No NSFW, explicit, or offensive content. Keep discussions suitable for all members (unless in designated channels).", inline=False)
        rules_embed.add_field(name="4. Use Channels Properly", value="Stick to the purpose of each channel. Don't post unrelated content in the wrong channels.", inline=False)
        rules_embed.add_field(name="5. No Unauthorized Links", value="Do not send suspicious, harmful, or unauthorized links. Only share links in allowed channels.", inline=False)
        rules_embed.add_field(name="6. Follow Discord Terms of Service", value="All members must follow the rules set by Discord and its Community Guidelines.", inline=False)
        rules_embed.add_field(name="7. No Self-Promotion Without Permission", value="Advertising, promotions, or invites to other servers are not allowed unless approved by staff.", inline=False)
        rules_embed.add_field(name="8. Respect Privacy", value="Do not share personal information (yours or others') without consent.", inline=False)
        rules_embed.add_field(name="9. Listen to Staff", value="Follow instructions from moderators and admins. Their decisions are final.", inline=False)
        rules_embed.add_field(name="10. Use Common Sense", value="If something feels wrong or harmful, don't do it.", inline=False)
        rules_embed.add_field(name="⚠️ Consequences", value="Breaking the rules may result in:\n> ⚠️ Warning\n> 🔇 Mute\n> 👢 Kick\n> 🔨 Ban", inline=False)
        rules_embed.set_footer(text="By Clicking the button below, you agree to follow these rules and respect the community. Enjoy your stay! 🎉")

        view = None
        if role is not None:
            if interaction.guild is None or not can_manage_role(interaction.client, interaction.guild, role):
                await interaction.followup.send(
                    "⚠️ Config saved, but I can't manage that role. Make sure my highest role is above it.",
                    ephemeral=True,
                )
                return
            view = ReactionRoleButtonView(interaction.client, role.id)

            if button_text is not None:
                custom_label = button_text.strip()
                if not custom_label:
                    await interaction.followup.send(
                        "⚠️ Button text cannot be empty.",
                        ephemeral=True,
                    )
                    return
                if len(custom_label) > 80:
                    await interaction.followup.send(
                        "⚠️ Button text must be 80 characters or less.",
                        ephemeral=True,
                    )
                    return

                for child in view.children:
                    if isinstance(child, discord.ui.Button):
                        child.label = custom_label
                        break

        posted_message = None
        if post_rules:
            try:
                posted_message = await redirect_channel.send(embed=rules_embed, view=view)
            except (discord.Forbidden, discord.HTTPException):
                await interaction.followup.send(
                    f"⚠️ Config saved but I couldn't send the rules to {redirect_channel.mention}. Please check my permissions in that channel.",
                    ephemeral=True,
                )
                return
        elif role is not None:
            await interaction.followup.send(
                "⚠️ A role button cannot be assigned when rules posting is disabled.",
                ephemeral=True,
            )
            return

        if role is not None and view is not None and posted_message is not None:
            reaction_role_posts = load_reaction_role_posts()
            reaction_role_posts[str(posted_message.id)] = {
                "guild_id": interaction.guild_id,
                "channel_id": redirect_channel.id,
                "role_id": role.id,
                "message": "Rules acceptance role toggle",
            }
            save_reaction_role_posts(reaction_role_posts)
            interaction.client.add_view(view, message_id=posted_message.id)

        rules_note = f" The server rules have been posted in {redirect_channel.mention}." if post_rules else ""
        await interaction.followup.send(
            f"✅ Welcome messages will be sent to {welcome_channel.mention}, and new members will be directed to {redirect_channel.mention}.{rules_note}",
            ephemeral=True,
        )
    except Exception as exc:
        print(f"setwelcome failed: {exc}")
        await interaction.followup.send(
            "❌ Something went wrong while configuring welcome settings. Please try again.",
            ephemeral=True,
        )


@set_welcome.error
async def set_welcome_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        if interaction.response.is_done():
            await interaction.followup.send(
                "❌ You need the **Administrator** permission to use this command.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ You need the **Administrator** permission to use this command.",
                ephemeral=True,
            )


async def on_member_join(member: discord.Member):
    if not _config_ready:
        print("on_member_join fired before config was loaded — skipping.")
        return

    guild_key = str(member.guild.id)
    cfg = WELCOME_CONFIG.get(guild_key)
    if not cfg:
        return

    welcome_channel = await resolve_text_channel(member.guild, cfg.get("welcome_channel_id"))
    redirect_channel = await resolve_text_channel(member.guild, cfg.get("redirect_channel_id"))
    if welcome_channel is None or redirect_channel is None:
        return

    embed = discord.Embed(
        title=f"Welcome to {member.guild.name}!",
        description=f"Hey {member.mention}, glad to have you here! 👋\n\nPlease head over to {redirect_channel.mention} to get started.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Member #{member.guild.member_count}")

    try:
        await welcome_channel.send(embed=embed)
    except discord.Forbidden:
        print(f"Missing permission to send welcome message in {welcome_channel.id}")


async def setup(bot: commands.Bot):
    load_welcome_config()
    bot.tree.add_command(set_welcome)
    bot.add_listener(on_member_join, "on_member_join")