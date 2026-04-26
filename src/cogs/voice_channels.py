from __future__ import annotations

import json
from pathlib import Path

import discord
import asyncio
from discord import app_commands
from discord.ext import commands

VOICE_OWNER_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "voice_owners.json"
VOICE_OWNERS: dict[str, dict] = {}


def load_voice_owners() -> dict:
    try:
        with open(VOICE_OWNER_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    with open(VOICE_OWNER_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2)
    return {}


def save_voice_owners() -> None:
    with open(VOICE_OWNER_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(VOICE_OWNERS, f, indent=2)


def get_user_controlled_voice_channel(interaction: discord.Interaction) -> tuple[discord.VoiceChannel | None, str | None]:
    if interaction.guild is None:
        return None, "This command can only be used in a server."

    member = interaction.user
    voice = getattr(member, "voice", None)
    if voice is None or not isinstance(voice.channel, discord.VoiceChannel):
        return None, "You must be connected to your created voice channel to use this command."

    channel = voice.channel
    owner_entry = VOICE_OWNERS.get(str(channel.id))
    is_admin = getattr(member.guild_permissions, "administrator", False)

    if not owner_entry:
        if is_admin:
            return channel, None
        return None, "This voice channel is not registered as a creator channel."

    if int(owner_entry.get("owner_id", 0)) != member.id and not is_admin:
        return None, "Only the voice channel creator can use this command here."

    return channel, None


vc_group = app_commands.Group(name="vc", description="Manage your creator voice channel")


@vc_group.command(name="help", description="Show a tutorial for the creator voice channel commands.")
async def vc_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Creator Voice Channel Help",
        description="Use these slash commands to manage your own creator voice channel.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="/vc create",
        value="Create a new creator voice channel with an optional name and user limit.",
        inline=False,
    )
    embed.add_field(
        name="/vc lock",
        value="Prevent other members from joining your creator voice channel.",
        inline=False,
    )
    embed.add_field(
        name="/vc unlock",
        value="Allow other members to join your creator voice channel again.",
        inline=False,
    )
    embed.add_field(
        name="/vc hide",
        value="Hide your creator voice channel from regular members.",
        inline=False,
    )
    embed.add_field(
        name="/vc show",
        value="Make your creator voice channel visible again.",
        inline=False,
    )
    embed.add_field(
        name="/vc limit",
        value="Set or change the user limit of your creator voice channel.",
        inline=False,
    )
    embed.add_field(
        name="Note",
        value="These are slash commands, so the command itself does not appear in chat. The bot replies privately to keep the channel clean.",
        inline=False,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=30)


@vc_group.command(name="create", description="Create a voice channel with a custom user limit.")
@app_commands.describe(name="Optional name of the voice channel", limit="Maximum participants (0 means unlimited)")
async def create_voice_channel(
    interaction: discord.Interaction,
    name: str | None = None,
    limit: app_commands.Range[int, 0, 99] = 0,
):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True, delete_after=30)
        return

    await interaction.response.defer(ephemeral=True)

    category = None
    channel = interaction.channel
    if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
        category = channel.category

    channel_name = name.strip() if name else ""
    if not channel_name:
        channel_name = interaction.user.display_name

    try:
        voice_channel = await interaction.guild.create_voice_channel(
            name=channel_name,
            category=category,
            user_limit=limit,
            reason=f"Voice channel created by {interaction.user}",
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "I don't have permission to create voice channels. Please grant **Manage Channels**.",
            ephemeral=True,
        )
        return
    except discord.HTTPException as exc:
        await interaction.followup.send(
            f"Failed to create voice channel: `{exc}`",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"✅ Created {voice_channel.mention} with limit **{limit if limit > 0 else 'unlimited'}**.",
        ephemeral=True,
    )

    VOICE_OWNERS[str(voice_channel.id)] = {
        "owner_id": interaction.user.id,
        "guild_id": interaction.guild_id,
    }
    save_voice_owners()

    member = interaction.guild.get_member(interaction.user.id)
    if member is not None:
        try:
            await member.move_to(voice_channel, reason="Auto-join creator to their new voice channel")
        except (discord.Forbidden, discord.HTTPException):
            pass

    # Schedule a cleanup in case the creator never joins
    asyncio.create_task(_cleanup_if_empty(voice_channel))


@vc_group.command(name="lock", description="Lock your creator voice channel (members cannot join).")
async def vc_lock(interaction: discord.Interaction):
    channel, error = get_user_controlled_voice_channel(interaction)
    if error:
        await interaction.response.send_message(error, ephemeral=True, delete_after=30)
        return

    try:
        await channel.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message(f"🔒 Locked {channel.mention}.", ephemeral=True, delete_after=30)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to edit channel permissions.", ephemeral=True, delete_after=30)
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Failed to lock channel: `{exc}`", ephemeral=True, delete_after=30)


@vc_group.command(name="unlock", description="Unlock your creator voice channel (members can join again).")
async def vc_unlock(interaction: discord.Interaction):
    channel, error = get_user_controlled_voice_channel(interaction)
    if error:
        await interaction.response.send_message(error, ephemeral=True, delete_after=30)
        return

    try:
        await channel.set_permissions(interaction.guild.default_role, connect=True)
        await interaction.response.send_message(f"🔓 Unlocked {channel.mention}.", ephemeral=True, delete_after=30)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to edit channel permissions.", ephemeral=True, delete_after=30)
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Failed to unlock channel: `{exc}`", ephemeral=True, delete_after=30)


@vc_group.command(name="hide", description="Hide your creator voice channel from non-admin members.")
async def vc_hide(interaction: discord.Interaction):
    channel, error = get_user_controlled_voice_channel(interaction)
    if error:
        await interaction.response.send_message(error, ephemeral=True, delete_after=30)
        return

    try:
        await channel.set_permissions(interaction.guild.default_role, view_channel=False)
        await interaction.response.send_message(
            f"🙈 Hid {channel.mention} from regular members (admins still have access).",
            ephemeral=True,
            delete_after=30,
        )
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to edit channel permissions.", ephemeral=True, delete_after=30)
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Failed to hide channel: `{exc}`", ephemeral=True, delete_after=30)


@vc_group.command(name="show", description="Show your creator voice channel to members again.")
async def vc_show(interaction: discord.Interaction):
    channel, error = get_user_controlled_voice_channel(interaction)
    if error:
        await interaction.response.send_message(error, ephemeral=True, delete_after=30)
        return

    try:
        await channel.set_permissions(interaction.guild.default_role, view_channel=True)
        await interaction.response.send_message(f"👁️ Made {channel.mention} visible again.", ephemeral=True, delete_after=30)
    except discord.Forbidden:
        await interaction.response.send_message("I don't have permission to edit channel permissions.", ephemeral=True, delete_after=30)
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Failed to show channel: `{exc}`", ephemeral=True, delete_after=30)


async def _cleanup_if_empty(channel: discord.VoiceChannel, delay: int = 30) -> None:
    """Delete a creator voice channel if it's still empty after `delay` seconds."""
    await asyncio.sleep(delay)

    channel_key = str(channel.id)
    if channel_key not in VOICE_OWNERS:
        return  # Already deleted or not a creator channel

    if len(channel.members) > 0:
        return  # Someone joined, leave it alone

    try:
        await channel.delete(reason="Auto-delete: creator channel was never joined")
    except (discord.Forbidden, discord.HTTPException):
        return

    VOICE_OWNERS.pop(channel_key, None)
    save_voice_owners()
    
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    left_channel = before.channel
    if not isinstance(left_channel, discord.VoiceChannel):
        return

    channel_key = str(left_channel.id)
    if channel_key not in VOICE_OWNERS:
        return

    await asyncio.sleep(10)

    # Re-check AFTER the sleep — another coroutine may have already cleaned up
    if channel_key not in VOICE_OWNERS:
        return
    if len(left_channel.members) > 0:
        return

    try:
        await left_channel.delete(reason="Auto-delete empty creator voice channel after delay")
    except (discord.Forbidden, discord.HTTPException):
        return

    VOICE_OWNERS.pop(channel_key, None)
    save_voice_owners()

@vc_group.command(
    name="limit",
    description="Set or change the user limit of your creator voice channel."
)
@app_commands.describe(
    limit="Maximum participants (0 means unlimited)"
)
async def vc_limit(
    interaction: discord.Interaction,
    limit: app_commands.Range[int, 0, 99]
):
    channel, error = get_user_controlled_voice_channel(interaction)

    if error:
        await interaction.response.send_message(error, ephemeral=True, delete_after=30)
        return

    try:
        await channel.edit(user_limit=limit)

        await interaction.response.send_message(
            f"👥 Set user limit of {channel.mention} to "
            f"**{limit if limit > 0 else 'unlimited'}**.",
            ephemeral=True,
            delete_after=30,
        )

    except discord.Forbidden:
        await interaction.response.send_message(
            "I don't have permission to edit this voice channel.",
            ephemeral=True,
            delete_after=30,
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            f"Failed to update user limit: `{exc}`",
            ephemeral=True,
            delete_after=30,
        )
        
async def setup(bot: commands.Bot):
    global VOICE_OWNERS
    VOICE_OWNERS = load_voice_owners()

    bot.tree.add_command(vc_group)
    bot.add_listener(on_voice_state_update, "on_voice_state_update")
