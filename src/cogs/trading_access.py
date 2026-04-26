from __future__ import annotations

import json
from pathlib import Path

import discord
from discord import app_commands, ui
from discord.ext import commands

TRADING_STORE_PATH = Path(__file__).resolve().parent.parent / "trading_config.json"
TRADING_CONFIG: dict = {}
BOT: commands.Bot | None = None


def load_trading_config() -> dict:
    try:
        with open(TRADING_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_trading_config(cfg: dict):
    with open(TRADING_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


class TradingAccessView(ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @ui.button(label="Get Trading Access", style=discord.ButtonStyle.success, custom_id="trading_access_button", emoji="🤝")
    async def trading_access_button(self, interaction: discord.Interaction, button: ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "The trading role no longer exists. Please ask an admin to re-run `/setuptrading`.",
                ephemeral=True,
                delete_after=30,
            )
            return

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(
                    f"✅ {role.mention} removed. You no longer have access to the trading channel.",
                    ephemeral=True,
                    delete_after=30,
                )
            else:
                await member.add_roles(role)
                await interaction.response.send_message(
                    f"✅ {role.mention} granted! You now have access to the trading channel.",
                    ephemeral=True,
                    delete_after=30,
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to assign that role. Make sure my role is above the trading role.",
                ephemeral=True,
                delete_after=30,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(f"Something went wrong: `{e}`", ephemeral=True, delete_after=30)


@app_commands.command(name="setuptrading", description="Create a private trading channel + access role and post the opt-in embed.")
@app_commands.describe(
    post_channel="Channel where the opt-in embed will be posted",
    trading_channel_name="Name for the new private trading channel (default: trading)",
    role_name="Name for the new trading access role (default: Trader)",
    category="Category to place the trading channel in (optional)",
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_trading(
    interaction: discord.Interaction,
    post_channel: discord.TextChannel,
    trading_channel_name: str = "trading",
    role_name: str = "Trader",
    category: discord.CategoryChannel = None,
):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    guild_key = str(guild.id)

    existing_cfg = TRADING_CONFIG.get(guild_key, {})
    trading_role = None
    if existing_cfg.get("role_id"):
        trading_role = guild.get_role(existing_cfg["role_id"])

    if trading_role is None:
        try:
            trading_role = await guild.create_role(
                name=role_name,
                mentionable=False,
                reason="Trading access role created by /setuptrading",
            )
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to create roles.", ephemeral=True)
            return

    trading_channel = None
    if existing_cfg.get("channel_id"):
        trading_channel = guild.get_channel(existing_cfg["channel_id"])

    if trading_channel is None:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            trading_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        try:
            trading_channel = await guild.create_text_channel(
                name=trading_channel_name,
                overwrites=overwrites,
                category=category,
                reason="Private trading channel created by /setuptrading",
            )
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to create channels.", ephemeral=True)
            return
    else:
        try:
            await trading_channel.set_permissions(
                trading_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        except discord.Forbidden:
            pass

    embed = discord.Embed(
        title="🤝 Trading Channel Access",
        description=f"Want access to Trading channel?\n\nClick the button below to get the trading role. Click again to remove it.",
        color=discord.Color.gold(),
    )
    embed.set_footer(text="Trading access is toggled by the button below.")

    view = TradingAccessView(trading_role.id)
    opt_in_message = await post_channel.send(embed=embed, view=view)
    if BOT is not None:
        BOT.add_view(view, message_id=opt_in_message.id)

    TRADING_CONFIG[guild_key] = {
        "role_id": trading_role.id,
        "channel_id": trading_channel.id,
        "message_id": opt_in_message.id,
        "post_channel_id": post_channel.id,
    }
    save_trading_config(TRADING_CONFIG)

    await interaction.followup.send(
        f"Done! Role: {trading_role.mention}, Channel: {trading_channel.mention}, Opt-in embed posted in: {post_channel.mention}",
        ephemeral=True,
    )


@setup_trading.error
async def setup_trading_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Administrator** permission to use this command.",
            ephemeral=True,
            delete_after=30,
        )

import time
from datetime import timedelta

class TradingChannelGuard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Store timestamps per user
        self.user_messages = {}

        # Spam settings
        self.SPAM_LIMIT = 5        # messages
        self.SPAM_INTERVAL = 10    # seconds
        self.MUTE_DURATION = 300   # 5 minutes

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return  # allow bot messages

        if not message.guild:
            return  # ignore DMs

        guild_key = str(message.guild.id)
        trading_cfg = TRADING_CONFIG.get(guild_key)

        if not trading_cfg:
            return

        trading_channel_id = trading_cfg.get("channel_id")

        # 🚫 Only block the main trading channel (threads are safe)
        if message.channel.id == trading_channel_id:
            try:
                # -------------------------
                # SPAM DETECTION
                # -------------------------

                now = time.time()

                timestamps = self.user_messages.get(
                    message.author.id,
                    []
                )

                # Keep recent timestamps only
                timestamps = [
                    t for t in timestamps
                    if now - t < self.SPAM_INTERVAL
                ]

                timestamps.append(now)

                self.user_messages[
                    message.author.id
                ] = timestamps

                # If spam detected → timeout user
                if len(timestamps) >= self.SPAM_LIMIT:

                    try:
                        await message.author.timeout(
                            timedelta(seconds=self.MUTE_DURATION),
                            reason="Spam detected in trading channel"
                        )

                        timeout_embed = discord.Embed(
                            title="🚫 Spam Detected",
                            description=(
                                f"{message.author.mention}, "
                                "you have been muted for **5 minutes** "
                                "for spamming in the trading channel."
                            ),
                            color=discord.Color.red(),
                        )

                        warn = await message.channel.send(
                            embed=timeout_embed
                        )

                        await warn.delete(delay=10)

                        # Reset counter after mute
                        self.user_messages[
                            message.author.id
                        ] = []

                    except discord.Forbidden:
                        print("Missing timeout permissions.")

                # -------------------------
                # NORMAL DELETE + WARNING
                # -------------------------

                await message.delete()

                embed = discord.Embed(
                    title="🚫 Trading Channel Notice",
                    description=(
                        f"{message.author.mention}, please use **`/createtrade`** "
                        "to post trades.\n\n"
                        "Use the trade buttons to open a **private thread** "
                        "for discussion."
                    ),
                    color=discord.Color.orange(),
                )

                embed.set_footer(
                    text="This message will be removed in 10 seconds."
                )

                warning = await message.channel.send(
                    embed=embed
                )

                # Delete warning after 10 seconds
                await warning.delete(delay=10)

            except discord.Forbidden:
                print("Missing permissions to delete messages.")

        await self.bot.process_commands(message)
                
async def setup(bot: commands.Bot):
    global TRADING_CONFIG, BOT
    BOT = bot
    TRADING_CONFIG = load_trading_config()
    
    await bot.add_cog(TradingChannelGuard(bot))
    
    bot.tree.add_command(setup_trading)

    restored = 0
    for guild_key, entry in TRADING_CONFIG.items():
        try:
            message_id = int(entry["message_id"])
            role_id = int(entry["role_id"])
            bot.add_view(TradingAccessView(role_id), message_id=message_id)
            restored += 1
        except (KeyError, ValueError, TypeError) as exc:
            print(f"Skipping trading entry {guild_key}: {exc}")
    print(f"Restored trading-access views: {restored}")
