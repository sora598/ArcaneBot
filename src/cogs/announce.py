from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


@app_commands.command(name="announce", description="Send an anonymous embed message to a channel.")
@app_commands.describe(
    channel="Channel to send the message in (optional; defaults to current channel)",
    title="Title of the embed",
    message="Body text of the embed",
    color="Hex color for the embed (e.g. ff0000 for red). Defaults to blurple.",
    image_url="Optional image URL to attach at the bottom of the embed",
)
@app_commands.checks.has_permissions(administrator=True)
async def announce(
    interaction: discord.Interaction,
    title: str,
    message: str,
    channel: discord.TextChannel | None = None,
    color: str = None,
    image_url: str = None,
):
    target_channel = channel or interaction.channel
    if target_channel is None:
        await interaction.response.send_message(
            "❌ Could not determine a target channel.",
            ephemeral=True,
        )
        return

    embed_color = discord.Color.blurple()
    if color:
        try:
            embed_color = discord.Color(int(color.lstrip("#"), 16))
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid color. Use a hex value like `ff0000` or `#ff0000`.",
                ephemeral=True,
            )
            return

    formatted_content = message.replace("\\n", "\n")
    
    embed = discord.Embed(
        title=title,
        description=formatted_content,
        color=embed_color,
        timestamp=datetime.now(timezone.utc),
    )
    if image_url:
        embed.set_image(url=image_url)

    try:
        await target_channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Announcement sent to {target_channel.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ I don't have permission to send messages in {target_channel.mention}.",
            ephemeral=True,
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(f"❌ Failed to send the message: `{e}`", ephemeral=True)


@announce.error
async def announce_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ This command is restricted to server administrators.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    bot.tree.add_command(announce)
