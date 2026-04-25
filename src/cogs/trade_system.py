from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import Interaction, app_commands, ui
from discord.ext import commands

ITEM_LIST_PATH = Path(__file__).resolve().parent.parent / "item_list.json"
TRADE_STORE_PATH = Path(__file__).resolve().parent.parent / "active_trades.json"
BOT: commands.Bot | None = None
ACTIVE_TRADES: dict[str, dict] = {}
TRADES_RESTORED = False

TRADE_TYPES = [
    app_commands.Choice(name="Trading X for Y", value="trade_for"),
    app_commands.Choice(name="Looking For X, Offering Y", value="lf_offer"),
    app_commands.Choice(name="Trading X, Looking For Offers", value="trade_for_offers"),
]


def load_trade_store() -> dict:
    try:
        with open(TRADE_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            trades = data.get("trades", {})
            if isinstance(trades, dict):
                return trades
    except (FileNotFoundError, json.JSONDecodeError):
        with open(TRADE_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump({"trades": {}}, f, indent=2)
    return {}


def save_trade_store() -> None:
    with open(TRADE_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump({"trades": ACTIVE_TRADES}, f, indent=2)


def parse_expires_at(expires_at):
    try:
        dt = datetime.fromisoformat(expires_at)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return datetime.now(timezone.utc) + timedelta(hours=12)


def load_item_list() -> list[str]:
    try:
        with open(ITEM_LIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data.get("items", [])
            if isinstance(items, list):
                cleaned = []
                seen = set()
                for item in items:
                    if not isinstance(item, str):
                        continue
                    value = item.strip()
                    if not value:
                        continue
                    if len(value) > 100:
                        value = value[:100]
                    if value in seen:
                        continue
                    seen.add(value)
                    cleaned.append(value)
                return cleaned
    except (FileNotFoundError, json.JSONDecodeError):
        with open(ITEM_LIST_PATH, "w", encoding="utf-8") as f:
            json.dump({"items": []}, f, indent=2)
    return []


def get_item_autocomplete_choices(current: str):
    try:
        items = load_item_list()
        query = (current or "").lower().strip()
        filtered = [item for item in items if not query or query in item.lower()]

        choices = []
        seen = set()
        for item in filtered:
            value = item.strip()[:100]
            if not value or value in seen:
                continue
            seen.add(value)
            choices.append(app_commands.Choice(name=value, value=value))

        if not choices:
            return [app_commands.Choice(name="No matching item found", value="No matching item found")]
        return choices[:25]
    except Exception as exc:
        print(f"Autocomplete error: {exc}")
        return [app_commands.Choice(name="Item list unavailable", value="Item list unavailable")]


def build_trade_embed(user, trade_type, item1, amount1, item2, amount2):
    labels = {
        "trade_for": ("Trading", "For"),
        "lf_offer": ("Looking For", "Offering"),
        "trade_for_offers": ("Trading", "Looking For"),
    }
    label_a, label_b = labels.get(trade_type, ("Item A", "Item B"))

    embed = discord.Embed(title="Trade Listing", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name=label_a, value=f"{item1} x{amount1}", inline=True)
    if trade_type == "trade_for_offers":
        embed.add_field(name=label_b, value="Any reasonable offers", inline=True)
    else:
        embed.add_field(name=label_b, value=f"{item2} x{amount2}", inline=True)
    embed.add_field(name="Trader", value=user.mention, inline=False)
    embed.set_footer(text="Use the buttons below to ask, complete, or cancel this trade.")
    return embed



class CloseThreadView(ui.View):
    """
    Buttons sent inside each private trade thread.
    The creator can reject (close) this specific thread.
    The asker can also withdraw their own request.
    """

    def __init__(self, creator_id: int, asker_id: int):
        super().__init__(timeout=None)
        self.creator_id = creator_id
        self.asker_id = asker_id

    async def _close_this_thread(self, interaction: discord.Interaction, closed_by: str):
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await interaction.response.send_message("This can only be used inside a thread.", ephemeral=True)
            return

        # Remove this thread from the trade's threads_by_user registry
        for trade in ACTIVE_TRADES.values():
            threads_by_user: dict = trade.get("threads_by_user", {})
            for user_id, tid in list(threads_by_user.items()):
                if int(tid) == thread.id:
                    del threads_by_user[user_id]
                    save_trade_store()
                    break

        await interaction.response.send_message(
            f"Thread closed by {closed_by}.", ephemeral=False
        )
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.DiscordException:
            pass
        await asyncio.sleep(3)
        try:
            await thread.delete(reason=f"Trade thread closed by {closed_by}")
        except discord.DiscordException:
            try:
                await thread.edit(archived=True, locked=True, reason=f"Trade thread closed by {closed_by}")
            except discord.DiscordException:
                pass

    @ui.button(label="Reject Request", style=discord.ButtonStyle.danger, custom_id="close_thread_creator")
    async def reject_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message("Only the trade creator can reject this request.", ephemeral=True)
            return
        await self._close_this_thread(interaction, "the trade creator")

    @ui.button(label="Withdraw Request", style=discord.ButtonStyle.secondary, custom_id="close_thread_asker")
    async def withdraw_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.asker_id:
            await interaction.response.send_message("Only the requester can withdraw this request.", ephemeral=True)
            return
        await self._close_this_thread(interaction, "the requester")


class TradeActionsView(ui.View):
    def __init__(self, creator_id):
        super().__init__(timeout=None)
        self.creator_id = creator_id

    async def _close_trade(self, interaction, reason):
        message_key = str(interaction.message.id)
        trade = ACTIVE_TRADES.get(message_key)
        if not trade:
            await interaction.response.send_message("This trade is already closed.", ephemeral=True)
            return

        if interaction.user.id != self.creator_id:
            await interaction.response.send_message("Only the trade creator can do that.", ephemeral=True)
            return

        trade["status"] = reason
        # Close all per-user private threads
        threads_by_user: dict = trade.get("threads_by_user", {})
        for thread_id in threads_by_user.values():
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                try:
                    await thread.send(f"Trade {reason} by {interaction.user.mention}.")
                except discord.DiscordException:
                    pass
                try:
                    await thread.delete(reason=f"Trade {reason}")
                except discord.DiscordException:
                    try:
                        await thread.edit(archived=True, locked=True, reason=f"Trade {reason}")
                    except discord.DiscordException:
                        pass

        ACTIVE_TRADES.pop(message_key, None)
        save_trade_store()

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="Trade Listing")
        embed.color = discord.Color.red() if reason == "cancelled" else discord.Color.green()
        embed.add_field(name="Status", value=reason.capitalize(), inline=False)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Ask For Trade", style=discord.ButtonStyle.primary, custom_id="trade_ask_button")
    async def ask_for_trade(self, interaction, button):
        message_key = str(interaction.message.id)
        trade = ACTIVE_TRADES.get(message_key)
        if not trade:
            await interaction.response.send_message("This trade is no longer active.", ephemeral=True)
            return

        # Prevent the trade creator from opening a thread with themselves
        creator_id = trade.get("creator_id")
        if interaction.user.id == creator_id:
            await interaction.response.send_message(
                "You cannot ask for your own trade.", ephemeral=True
            )
            return

        creator = interaction.guild.get_member(creator_id)
        if creator is None:
            await interaction.response.send_message("Trade creator is no longer available.", ephemeral=True)
            return

        # Each asker gets their own private thread — reuse if one already exists
        threads_by_user: dict = trade.setdefault("threads_by_user", {})
        existing_thread_id = threads_by_user.get(str(interaction.user.id))
        thread = interaction.guild.get_thread(existing_thread_id) if existing_thread_id else None

        if thread is None:
            try:
                thread = await interaction.channel.create_thread(
                    name=f"trade-{creator.display_name}-{interaction.user.display_name}"[:100],
                    type=discord.ChannelType.private_thread,
                    auto_archive_duration=1440,
                    invitable=False,
                    reason="Private trade discussion thread",
                )
                await thread.add_user(creator)
                await thread.add_user(interaction.user)

                threads_by_user[str(interaction.user.id)] = thread.id
                save_trade_store()
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I don't have permission to create private threads here. "
                    "Please make sure I have the **Create Private Threads** permission.",
                    ephemeral=True,
                )
                return
            except discord.DiscordException:
                await interaction.response.send_message(
                    "I could not create a trade thread here. Please check thread permissions.",
                    ephemeral=True,
                )
                return

            await thread.send(
                f"{creator.mention} {interaction.user.mention} is interested in this trade. "
                "Use this thread to discuss details. This thread is private — only you two can see it.",
                view=CloseThreadView(creator_id=creator_id, asker_id=interaction.user.id),
            )

        await interaction.response.send_message(f"Your private trade thread: {thread.mention}", ephemeral=True)

    @ui.button(label="Mark Completed", style=discord.ButtonStyle.success, custom_id="trade_complete_button")
    async def mark_completed(self, interaction, button):
        await self._close_trade(interaction, "completed")

    @ui.button(label="Cancel Trade", style=discord.ButtonStyle.danger, custom_id="trade_cancel_button")
    async def cancel_trade(self, interaction, button):
        await self._close_trade(interaction, "cancelled")


async def auto_close_trade_after_delay(message_id, delay_seconds):
    await asyncio.sleep(max(0, int(delay_seconds)))
    message_key = str(message_id)
    trade = ACTIVE_TRADES.get(message_key)
    if not trade:
        return

    ACTIVE_TRADES.pop(message_key, None)
    save_trade_store()

    if BOT is None:
        return

    channel = BOT.get_channel(trade.get("channel_id"))
    if channel is None:
        try:
            channel = await BOT.fetch_channel(trade.get("channel_id"))
        except discord.DiscordException:
            channel = None

    if channel is None:
        return

    try:
        message = await channel.fetch_message(message_id)
    except discord.DiscordException:
        message = None

    if message:
        threads_by_user: dict = trade.get("threads_by_user", {})
        for thread_id in threads_by_user.values():
            thread = message.guild.get_thread(int(thread_id))
            if thread:
                try:
                    await thread.send("This trade expired after 12 hours.")
                except discord.DiscordException:
                    pass
                try:
                    await thread.delete(reason="Trade expired after 12 hours")
                except discord.DiscordException:
                    try:
                        await thread.edit(archived=True, locked=True, reason="Trade expired after 12 hours")
                    except discord.DiscordException:
                        pass

        embed = message.embeds[0] if message.embeds else discord.Embed(title="Trade Listing")
        embed.color = discord.Color.dark_grey()
        embed.add_field(name="Status", value="Expired (12h)", inline=False)
        view = TradeActionsView(trade.get("creator_id"))
        for child in view.children:
            child.disabled = True
        try:
            await message.edit(embed=embed, view=view)
        except discord.DiscordException:
            pass


def register_trade_runtime(message_id, trade_data):
    message_key = str(message_id)
    ACTIVE_TRADES[message_key] = trade_data
    save_trade_store()

    if BOT is not None:
        BOT.add_view(TradeActionsView(trade_data["creator_id"]), message_id=message_id)
        expires_at = parse_expires_at(trade_data.get("expires_at"))
        delay_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
        BOT.loop.create_task(auto_close_trade_after_delay(message_id, delay_seconds))


async def restore_active_trades():
    loaded = load_trade_store()
    now = datetime.now(timezone.utc)
    restored = 0
    expired = 0

    for message_key, trade in loaded.items():
        try:
            message_id = int(message_key)
        except (TypeError, ValueError):
            continue

        if str(trade.get("status", "active")) != "active":
            continue

        expires_at = parse_expires_at(trade.get("expires_at"))
        if expires_at <= now:
            ACTIVE_TRADES[str(message_id)] = trade
            if BOT is not None:
                BOT.loop.create_task(auto_close_trade_after_delay(message_id, 0))
            expired += 1
            continue

        ACTIVE_TRADES[str(message_id)] = trade
        if BOT is not None:
            BOT.add_view(TradeActionsView(trade.get("creator_id")), message_id=message_id)
            delay_seconds = (expires_at - now).total_seconds()
            BOT.loop.create_task(auto_close_trade_after_delay(message_id, delay_seconds))
        restored += 1

    save_trade_store()
    print(f"Restored active trades: {restored}; expired queued: {expired}")


@app_commands.command(name="createtrade", description="Create a trade listing with buttons and a discussion thread.")
@app_commands.describe(
    trade_type="Pick how this trade should be listed",
    item1="Primary item",
    amount1="Primary item amount",
    item2="Secondary item (ignored for 'Looking For Offers')",
    amount2="Secondary item amount (ignored for 'Looking For Offers')",
)
@app_commands.choices(trade_type=TRADE_TYPES)
async def create_trade(
    interaction: discord.Interaction,
    trade_type: app_commands.Choice[str],
    item1: str,
    amount1: app_commands.Range[int, 1, 1_000_000],
    item2: str | None = None,
    amount2: app_commands.Range[int, 1, 1_000_000] | None = None,
):
    if trade_type.value != "trade_for_offers" and (not item2 or amount2 is None):
        await interaction.response.send_message(
            "For this trade type, please provide item2 and amount2.",
            ephemeral=True,
        )
        return

    if trade_type.value == "trade_for_offers":
        item2 = item2 or "Offers"
        amount2 = amount2 or 1

    embed = build_trade_embed(interaction.user, trade_type.value, item1, amount1, item2, amount2)
    view = TradeActionsView(interaction.user.id)

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    trade_data = {
        "creator_id": interaction.user.id,
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "threads_by_user": {},  # str(user_id) -> private thread_id
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
    }
    register_trade_runtime(message.id, trade_data)


@create_trade.autocomplete("item1")
async def item1_autocomplete(interaction: Interaction, current: str):
    return get_item_autocomplete_choices(current)


@create_trade.autocomplete("item2")
async def item2_autocomplete(interaction: Interaction, current: str):
    return get_item_autocomplete_choices(current)


async def setup(bot: commands.Bot):
    global BOT, TRADES_RESTORED, ACTIVE_TRADES
    BOT = bot
    ACTIVE_TRADES = load_trade_store()
    bot.tree.add_command(create_trade)

    if not TRADES_RESTORED:
        await restore_active_trades()
        TRADES_RESTORED = True