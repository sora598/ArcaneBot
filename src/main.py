# Arcane-Bot: Discord Reaction Role Bot
# --------------------------------------
# This bot assigns or removes roles based on user reactions to a specific message.
# Security best practices are followed: no hardcoded secrets, minimal permissions, and error handling.

import os  # For environment variable access
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs
import discord  # Discord API wrapper
from discord.ext import commands  # Bot command framework
from discord import app_commands  # For slash commands
from discord import ui, Interaction  # For slash commands and UI components
from dotenv import load_dotenv  # For loading .env files

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")  # Discord bot token (keep this secret!)

# Configure Discord intents (permissions)
# Only enable what is necessary for security
intents = discord.Intents.default()
intents.guilds = True  # Needed for guild (server) events
intents.members = True  # Needed to fetch and manage members
intents.reactions = True  # Needed to listen for reaction events

# Initialize the bot with command prefix and intents
bot = commands.Bot(command_prefix="!", intents=intents)

# Sync tree for slash commands
tree = bot.tree  # Assign the bot's command tree to the variable `tree`

# --- File paths ---
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "reaction_roles_config.json")
ITEM_LIST_PATH = os.path.join(os.path.dirname(__file__), "item_list.json")
TRADE_STORE_PATH = os.path.join(os.path.dirname(__file__), "active_trades.json")
NOTIFY_STORE_PATH = os.path.join(os.path.dirname(__file__), "notify_roles.json")
WELCOME_STORE_PATH = os.path.join(os.path.dirname(__file__), "welcome_config.json")


# --- Notify Role persistence helpers ---

def load_notify_store() -> dict:
    """Load persisted notify-role message registry from disk."""
    try:
        with open(NOTIFY_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # File missing or corrupt — create a blank notify store
        with open(NOTIFY_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}


def save_notify_store(store: dict):
    """Persist notify-role message registry to disk."""
    with open(NOTIFY_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


# In-memory registry: message_id (str) -> {guild_id, channel_id, role_id}
NOTIFY_STORE: dict = load_notify_store()


class NotifyRoleButtonView(ui.View):
    """
    Persistent button view for toggling a notification role.
    The role is looked up from the guild at interaction time using the stored
    role_id, so the view survives bot restarts without holding a stale object.
    """

    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @ui.button(label="Get Notified!", style=discord.ButtonStyle.primary, custom_id="notify_role_button")
    async def notify_button(self, interaction: discord.Interaction, button: ui.Button):
        # Re-resolve role from guild at interaction time (works after restarts)
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "The notification role no longer exists. Please ask an admin to re-run `/notifyrole`.",
                ephemeral=True,
            )
            return

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(f"{role.mention} role removed.", ephemeral=True)
            else:
                await member.add_roles(role)
                await interaction.response.send_message(
                    f"{role.mention} Role Obtained! You will be notified if someone starts a sea beast hunt!",
                    ephemeral=True,
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ ISomething went wrong please try again later.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Something went wrong while updating your role: `{e}`",
                ephemeral=True,
            )


# Slash command to send the notification embed with button
@tree.command(name="notifyrole", description="Send a notification embed with a button for Sea Beast Hunt role.")
@app_commands.describe(role="The role to assign/remove for notifications.")
async def notifyrole(interaction: discord.Interaction, role: discord.Role):
    embed = discord.Embed(
        title="Sea Beast Hunt Notifications",
        description=(
            "Want to be notified when someone is organizing a Sea Beast Hunt? "
            "Click the button below to receive or remove the notification role!"
        ),
        color=discord.Color.blue()
    )
    view = NotifyRoleButtonView(role.id)

    # Send the embed anonymously via the channel (not via interaction response)
    # so the bot appears as the sender rather than the command invoker.
    message = await interaction.channel.send(embed=embed, view=view)

    # Acknowledge the interaction ephemerally so Discord doesn't show "failed"
    await interaction.response.send_message(
        "✅ Notification role embed posted!", ephemeral=True
    )

    # Persist message so the view is re-registered on restart
    NOTIFY_STORE[str(message.id)] = {
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "role_id": role.id,
    }
    save_notify_store(NOTIFY_STORE)
    # Register it immediately so it's live without a restart
    bot.add_view(view, message_id=message.id)


# --- Multi-server dynamic configuration ---
# Load and persist the REACTION_ROLE_CONFIG dictionary from a JSON file
TRADE_TYPES = [
    app_commands.Choice(name="Trading X for Y", value="trade_for"),
    app_commands.Choice(name="Looking For X, Offering Y", value="lf_offer"),
    app_commands.Choice(name="Trading X, Looking For Offers", value="trade_for_offers"),
]

# Runtime trade store (message_id -> metadata), persisted to JSON.
ACTIVE_TRADES = {}
TRADES_RESTORED = False


def load_trade_store():
    """Load active trade metadata from JSON storage."""
    try:
        with open(TRADE_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            trades = data.get("trades", {})
            if isinstance(trades, dict):
                return trades
    except (FileNotFoundError, json.JSONDecodeError):
        # File missing or corrupt — create a blank trade store
        with open(TRADE_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump({"trades": {}}, f, indent=2)
    return {}


def save_trade_store():
    """Persist active trade metadata to JSON storage."""
    payload = {"trades": ACTIVE_TRADES}
    with open(TRADE_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def parse_expires_at(expires_at):
    """Parse an ISO timestamp safely; fallback to 12h from now on invalid values."""
    try:
        dt = datetime.fromisoformat(expires_at)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return datetime.now(timezone.utc) + timedelta(hours=12)


def load_item_list():
    """Load item names from item_list.json for autocomplete."""
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
        # File missing or corrupt — create a blank item list
        with open(ITEM_LIST_PATH, "w", encoding="utf-8") as f:
            json.dump({"items": []}, f, indent=2)
    return []


ITEM_LIST = load_item_list()


def get_item_autocomplete_choices(current):
    """Return safe autocomplete choices from the latest item_list.json content."""
    try:
        items = load_item_list()
        query = (current or "").lower().strip()

        if query:
            filtered = [item for item in items if query in item.lower()]
        else:
            filtered = items

        # Discord choice name/value max length is 100.
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
    except Exception as e:
        # Avoid surfacing callback errors to users as "options failed to load".
        print(f"Autocomplete error: {e}")
        return [app_commands.Choice(name="Item list unavailable", value="Item list unavailable")]


def build_trade_embed(user, trade_type, item1, amount1, item2, amount2):
    """Create the public trade listing embed."""
    labels = {
        "trade_for": ("Trading", "For"),
        "lf_offer": ("Looking For", "Offering"),
        "trade_for_offers": ("Trading", "Looking For"),
    }
    label_a, label_b = labels.get(trade_type, ("Item A", "Item B"))

    embed = discord.Embed(
        title="Trade Listing",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name=label_a, value=f"{item1} x{amount1}", inline=True)
    if trade_type == "trade_for_offers":
        embed.add_field(name=label_b, value="Any reasonable offers", inline=True)
    else:
        embed.add_field(name=label_b, value=f"{item2} x{amount2}", inline=True)
    embed.add_field(name="Trader", value=user.mention, inline=False)
    embed.set_footer(text="Use the buttons below to ask, complete, or cancel this trade.")
    return embed


class TradeActionsView(ui.View):
    """Buttons for asking and closing trade listings."""

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
        thread_id = trade.get("thread_id")
        if thread_id:
            thread = interaction.guild.get_thread(thread_id)
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

        creator_id = trade.get("creator_id")
        creator = interaction.guild.get_member(creator_id)
        if creator is None:
            await interaction.response.send_message("Trade creator is no longer available.", ephemeral=True)
            return

        thread_id = trade.get("thread_id")
        thread = interaction.guild.get_thread(thread_id) if thread_id else None
        if thread is None:
            try:
                thread = await interaction.message.create_thread(
                    name=f"trade-{creator.display_name}-{interaction.user.display_name}"[:100],
                    auto_archive_duration=1440,
                    reason="Trade discussion thread created",
                )
                trade["thread_id"] = thread.id
                save_trade_store()
            except discord.DiscordException:
                await interaction.response.send_message(
                    "I could not create a trade thread here. Please check thread permissions.",
                    ephemeral=True,
                )
                return

        await thread.send(
            f"{creator.mention} {interaction.user.mention} is asking for this trade. "
            "Use this thread to discuss details."
        )
        await interaction.response.send_message(f"Trade thread ready: {thread.mention}", ephemeral=True)

    @ui.button(label="Mark Completed", style=discord.ButtonStyle.success, custom_id="trade_complete_button")
    async def mark_completed(self, interaction, button):
        await self._close_trade(interaction, "completed")

    @ui.button(label="Cancel Trade", style=discord.ButtonStyle.danger, custom_id="trade_cancel_button")
    async def cancel_trade(self, interaction, button):
        await self._close_trade(interaction, "cancelled")


async def auto_close_trade_after_delay(message_id, delay_seconds):
    """Close trade automatically after a delay if still active."""
    await asyncio.sleep(max(0, int(delay_seconds)))
    message_key = str(message_id)
    trade = ACTIVE_TRADES.get(message_key)
    if not trade:
        return

    ACTIVE_TRADES.pop(message_key, None)
    save_trade_store()

    channel = bot.get_channel(trade.get("channel_id"))
    if channel is None:
        try:
            channel = await bot.fetch_channel(trade.get("channel_id"))
        except discord.DiscordException:
            channel = None

    if channel is None:
        return

    try:
        message = await channel.fetch_message(message_id)
    except discord.DiscordException:
        message = None

    if message:
        thread_id = trade.get("thread_id")
        if thread_id:
            thread = message.guild.get_thread(thread_id)
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
    """Register a trade in-memory, persist it, and schedule expiration task."""
    message_key = str(message_id)
    ACTIVE_TRADES[message_key] = trade_data
    save_trade_store()

    bot.add_view(TradeActionsView(trade_data["creator_id"]), message_id=message_id)
    expires_at = parse_expires_at(trade_data.get("expires_at"))
    delay_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
    bot.loop.create_task(auto_close_trade_after_delay(message_id, delay_seconds))


async def restore_active_trades():
    """Restore active trades from JSON and re-register persistent views/tasks."""
    loaded = load_trade_store()
    now = datetime.now(timezone.utc)
    restored = 0
    expired = 0

    for message_key, trade in loaded.items():
        try:
            message_id = int(message_key)
        except (TypeError, ValueError):
            continue

        status = str(trade.get("status", "active"))
        if status != "active":
            continue

        expires_at = parse_expires_at(trade.get("expires_at"))
        if expires_at <= now:
            # Expired while bot was offline; schedule immediate cleanup.
            ACTIVE_TRADES[str(message_id)] = trade
            bot.loop.create_task(auto_close_trade_after_delay(message_id, 0))
            expired += 1
            continue

        ACTIVE_TRADES[str(message_id)] = trade
        bot.add_view(TradeActionsView(trade.get("creator_id")), message_id=message_id)
        delay_seconds = (expires_at - now).total_seconds()
        bot.loop.create_task(auto_close_trade_after_delay(message_id, delay_seconds))
        restored += 1

    save_trade_store()
    print(f"Restored active trades: {restored}; expired queued: {expired}")

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return _int_keys(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        # File missing or corrupt — create a fresh empty config
        default = {}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default

def save_config(config):
    # Convert all int keys to strings for JSON serialization
    def _str_keys(d):
        if isinstance(d, dict):
            return {str(k): _str_keys(v) for k, v in d.items()}
        return d
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(_str_keys(config), f, indent=4)

def _int_keys(d):
    if isinstance(d, dict):
        return {int(k) if k.isdigit() else k: _int_keys(v) for k, v in d.items()}
    return d

REACTION_ROLE_CONFIG = load_config()


@tree.command(name="createtrade", description="Create a trade listing with buttons and a discussion thread.")
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

    embed = build_trade_embed(
        interaction.user,
        trade_type.value,
        item1,
        amount1,
        item2,
        amount2,
    )
    view = TradeActionsView(interaction.user.id)

    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    trade_data = {
        "creator_id": interaction.user.id,
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "thread_id": None,
        "status": "active",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
    }
    register_trade_runtime(message.id, trade_data)


def _get_guild_notify_role(guild: discord.Guild) -> discord.Role | None:
    """Return the notify role for the given guild, or None if not set."""
    for entry in NOTIFY_STORE.values():
        if int(entry.get("guild_id", 0)) == guild.id:
            return guild.get_role(int(entry["role_id"]))
    return None


_ROBLOX_SHARE_RE = re.compile(
    r'^(?=.*[?&]code=[^&\s]+)'
    r'(?=.*[?&]type=Server)'
    r'https://www\.roblox\.com/share\?[^\s]+$'
)


_PERIOD_CHOICES = [
    app_commands.Choice(name="AM", value="AM"),
    app_commands.Choice(name="PM", value="PM"),
]

@tree.command(name="seabeasthunt", description="Post an embed announcing an upcoming Sea Beast Hunt.")
@app_commands.describe(
    hour="Hour of the start time (1–12)",
    minute="Minute of the start time (0–59)",
    period="AM or PM",
    private_server_link="Roblox private server link",
)
@app_commands.choices(period=_PERIOD_CHOICES)
async def sea_beast_hunt_announcement(
    interaction: discord.Interaction,
    hour: app_commands.Range[int, 1, 12],
    minute: app_commands.Range[int, 0, 59],
    period: app_commands.Choice[str],
    private_server_link: str,
):
    link = private_server_link.strip()

    if not _ROBLOX_SHARE_RE.match(link):
        await interaction.response.send_message(
            "❌ Invalid link. Please provide a valid Roblox private server share link.\n"
            "It should look like: `https://www.roblox.com/share?code=...&type=Server`",
            ephemeral=True,
        )
        return

    # Convert 12-hour clock to 24-hour
    hour_24 = hour % 12 + (12 if period.value == "PM" else 0)

    # Host's time is always interpreted as UTC+8 (Philippines)
    tz = timezone(timedelta(hours=8))
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=hour_24, minute=minute, second=0, microsecond=0)
    # If the time has already passed today, assume the host means tomorrow
    if start_local <= now_local:
        start_local += timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    unix_ts = int(start_utc.timestamp())

    # Compute minutes until start from the timestamp
    now_utc = datetime.now(timezone.utc)
    minutes_until_start = max(0, int((start_utc - now_utc).total_seconds() / 60))

    # Discord dynamic timestamps — each viewer sees their own local time automatically
    discord_time = f"<t:{unix_ts}:t>"     # e.g. "8:30 PM"
    discord_relative = f"<t:{unix_ts}:R>" # e.g. "in 25 minutes"

    notify_role = _get_guild_notify_role(interaction.guild)
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

    if ping_text:
        # Send the ping as content so the role actually gets notified, embed alongside
        await interaction.response.send_message(content=ping_text, embed=embed)
    else:
        await interaction.response.send_message(embed=embed)

    # If hunt is more than 30 min away, schedule a ping when it hits 30 min remaining
    if notify_role and minutes_until_start > 30:
        delay = (minutes_until_start - 30) * 60

        async def _schedule_ping():
            await asyncio.sleep(delay)
            role = _get_guild_notify_role(interaction.guild)
            if role is None:
                return
            channel = interaction.channel
            if channel is None:
                try:
                    channel = await bot.fetch_channel(interaction.channel_id)
                except discord.DiscordException:
                    return
            try:
                await channel.send(
                    f"{role.mention} ⏰ The Sea Beast Hunt hosted by "
                    f"{interaction.user.mention} starts in **30 minutes**! "
                    f"[Join Server]({link})"
                )
            except discord.DiscordException as e:
                print(f"Scheduled sea beast ping failed: {e}")

        bot.loop.create_task(_schedule_ping())


@create_trade.autocomplete("item1")
async def item1_autocomplete(interaction: Interaction, current: str):
    return get_item_autocomplete_choices(current)


@create_trade.autocomplete("item2")
async def item2_autocomplete(interaction: Interaction, current: str):
    return get_item_autocomplete_choices(current)


@tree.command(name="setreactionrole", description="Set a reaction role mapping for this server.")
@app_commands.describe(
    message_id="The message ID to watch for reactions",
    emoji="The emoji to use for the reaction",
    role="The role to assign when the emoji is used"
)
async def set_reaction_role(
    interaction: discord.Interaction,
    message_id: str,
    emoji: str,
    role: discord.Role
):
    """
    Slash command to set or update a reaction role mapping for this server.
    Usage: /setreactionrole <message_id> <emoji> <role>
    """
    # Defer ephemerally immediately so the invoker is not shown publicly
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild_id
    try:
        msg_id = int(message_id)
    except ValueError:
        await interaction.followup.send("Invalid message ID.", ephemeral=True)
        return
    if guild_id not in REACTION_ROLE_CONFIG:
        REACTION_ROLE_CONFIG[guild_id] = {}
    if msg_id not in REACTION_ROLE_CONFIG[guild_id]:
        REACTION_ROLE_CONFIG[guild_id][msg_id] = {}
    REACTION_ROLE_CONFIG[guild_id][msg_id][emoji] = role.id
    save_config(REACTION_ROLE_CONFIG)
    await interaction.followup.send(
        f"Reaction role set: On message `{msg_id}`, reacting with `{emoji}` will give the role `{role.name}`.",
        ephemeral=True
    )

@bot.event
async def on_ready():
    """Event: Called when the bot is ready and connected to Discord."""
    global TRADES_RESTORED
    print(f"Logged in as {bot.user}")
    print(f"Trade item list loaded: {len(load_item_list())} items")

    # Restore persistent notify-role button views
    restored_notify = 0
    for message_id_str, entry in NOTIFY_STORE.items():
        try:
            message_id = int(message_id_str)
            role_id = int(entry["role_id"])
            bot.add_view(NotifyRoleButtonView(role_id), message_id=message_id)
            restored_notify += 1
        except (KeyError, ValueError, TypeError) as e:
            print(f"Skipping notify entry {message_id_str}: {e}")
    print(f"Restored notify-role views: {restored_notify}")

    # Restore persistent trading access button views
    restored_trading = 0
    for guild_key, entry in TRADING_CONFIG.items():
        try:
            message_id = int(entry["message_id"])
            role_id = int(entry["role_id"])
            bot.add_view(TradingAccessView(role_id), message_id=message_id)
            restored_trading += 1
        except (KeyError, ValueError, TypeError) as e:
            print(f"Skipping trading entry {guild_key}: {e}")
    print(f"Restored trading-access views: {restored_trading}")

    if not TRADES_RESTORED:
        await restore_active_trades()
        TRADES_RESTORED = True
    try:
        synced = await tree.sync()
        print(f"Globally synced {len(synced)} slash commands.")

        # Also sync per guild so command/autocomplete updates apply quickly in servers.
        for guild in bot.guilds:
            try:
                tree.copy_global_to(guild=guild)
                guild_synced = await tree.sync(guild=guild)
                print(f"Guild sync ({guild.id}) -> {len(guild_synced)} commands")
            except Exception as guild_error:
                print(f"Guild sync failed for {guild.id}: {guild_error}")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")

def get_guild_role_member(payload):
    """
    Helper function to fetch guild, role, and member objects from a reaction payload,
    using the dynamic REACTION_ROLE_CONFIG for multi-server support.
    Returns (guild, role, member) or (None, None, None) if not found or not configured.
    """
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return None, None, None
    guild_config = REACTION_ROLE_CONFIG.get(payload.guild_id, {})
    message_config = guild_config.get(payload.message_id, {})
    role_id = message_config.get(str(payload.emoji))


# ---------------------------------------------------------------------------
# Welcome system
# ---------------------------------------------------------------------------

def load_welcome_config() -> dict:
    """Load per-guild welcome config from disk. Schema:
    { "<guild_id>": { "welcome_channel_id": int, "redirect_channel_id": int } }
    """
    try:
        with open(WELCOME_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # File missing or corrupt — create a blank welcome config
        with open(WELCOME_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
        return {}


def save_welcome_config(cfg: dict):
    with open(WELCOME_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


WELCOME_CONFIG: dict = load_welcome_config()


@tree.command(name="setwelcome", description="Configure the welcome message and redirect channel for new members.")
@app_commands.describe(
    welcome_channel="Channel where the welcome message is posted",
    redirect_channel="Channel new members are directed to visit first",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def set_welcome(
    interaction: discord.Interaction,
    welcome_channel: discord.TextChannel,
    redirect_channel: discord.TextChannel,
):
    await interaction.response.defer(ephemeral=True)

    guild_key = str(interaction.guild_id)
    WELCOME_CONFIG[guild_key] = {
        "welcome_channel_id": welcome_channel.id,
        "redirect_channel_id": redirect_channel.id,
    }
    save_welcome_config(WELCOME_CONFIG)

    # Post the server rules embed to the redirect channel
    rules_embed = discord.Embed(
        title="📜 Server Rules",
        color=discord.Color.red(),
    )
    rules_embed.add_field(
        name="1. Be Respectful",
        value="Treat everyone with respect. No harassment, bullying, hate speech, or discrimination of any kind.",
        inline=False,
    )
    rules_embed.add_field(
        name="2. No Spam or Flooding",
        value="Avoid sending repeated messages, excessive emojis, or unnecessary mentions.",
        inline=False,
    )
    rules_embed.add_field(
        name="3. Keep It Appropriate",
        value="No NSFW, explicit, or offensive content. Keep discussions suitable for all members (unless in designated channels).",
        inline=False,
    )
    rules_embed.add_field(
        name="4. Use Channels Properly",
        value="Stick to the purpose of each channel. Don't post unrelated content in the wrong channels.",
        inline=False,
    )
    rules_embed.add_field(
        name="5. No Unauthorized Links",
        value="Do not send suspicious, harmful, or unauthorized links. Only share links in allowed channels.",
        inline=False,
    )
    rules_embed.add_field(
        name="6. Follow Discord Terms of Service",
        value="All members must follow the rules set by Discord and its Community Guidelines.",
        inline=False,
    )
    rules_embed.add_field(
        name="7. No Self-Promotion Without Permission",
        value="Advertising, promotions, or invites to other servers are not allowed unless approved by staff.",
        inline=False,
    )
    rules_embed.add_field(
        name="8. Respect Privacy",
        value="Do not share personal information (yours or others') without consent.",
        inline=False,
    )
    rules_embed.add_field(
        name="9. Listen to Staff",
        value="Follow instructions from moderators and admins. Their decisions are final.",
        inline=False,
    )
    rules_embed.add_field(
        name="10. Use Common Sense",
        value="If something feels wrong or harmful, don't do it.",
        inline=False,
    )
    rules_embed.add_field(
        name="⚠️ Consequences",
        value="Breaking the rules may result in:\n> ⚠️ Warning\n> 🔇 Mute\n> 👢 Kick\n> 🔨 Ban",
        inline=False,
    )
    rules_embed.set_footer(text="By staying in this server, you agree to abide by these rules.")

    try:
        await redirect_channel.send(embed=rules_embed)
    except discord.Forbidden:
        await interaction.followup.send(
            f"⚠️ Config saved but I couldn't send the rules to {redirect_channel.mention}. "
            "Please check my permissions in that channel.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"✅ Welcome messages will be sent to {welcome_channel.mention}, "
        f"new members will be directed to {redirect_channel.mention}, "
        f"and the server rules have been posted there.",
        ephemeral=True,
    )


@set_welcome.error
async def set_welcome_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Manage Server** permission to use this command.",
            ephemeral=True,
        )


@bot.event
async def on_member_join(member: discord.Member):
    guild_key = str(member.guild.id)
    cfg = WELCOME_CONFIG.get(guild_key)
    if not cfg:
        return  # No welcome config set for this guild

    welcome_channel = member.guild.get_channel(cfg.get("welcome_channel_id"))
    redirect_channel = member.guild.get_channel(cfg.get("redirect_channel_id"))

    if welcome_channel is None or redirect_channel is None:
        return

    embed = discord.Embed(
        title=f"Welcome to {member.guild.name}!",
        description=(
            f"Hey {member.mention}, glad to have you here! 👋\n\n"
            f"Please head over to {redirect_channel.mention} to get started."
        ),
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Member #{member.guild.member_count}")

    try:
        await welcome_channel.send(embed=embed)
    except discord.Forbidden:
        print(f"Missing permission to send welcome message in {welcome_channel.id}")




# ---------------------------------------------------------------------------
# Trading Access System
# Stores per-guild: the trading role id, trading channel id, and the
# message id of the opt-in embed so the button survives restarts.
# ---------------------------------------------------------------------------

TRADING_STORE_PATH = os.path.join(os.path.dirname(__file__), "trading_config.json")


def load_trading_config() -> dict:
    try:
        with open(TRADING_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_trading_config(cfg: dict):
    with open(TRADING_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


TRADING_CONFIG: dict = load_trading_config()


class TradingAccessView(ui.View):
    """Persistent button that grants/removes the trading channel access role."""

    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @ui.button(
        label="Get Trading Access",
        style=discord.ButtonStyle.success,
        custom_id="trading_access_button",
        emoji="🤝",
    )
    async def trading_access_button(self, interaction: discord.Interaction, button: ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                "⚠️ The trading role no longer exists. Please ask an admin to re-run `/setuptrading`.",
                ephemeral=True,
            )
            return

        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.response.send_message(
                    f"✅ {role.mention} removed. You no longer have access to the trading channel.",
                    ephemeral=True,
                )
            else:
                await member.add_roles(role)
                await interaction.response.send_message(
                    f"✅ {role.mention} granted! You now have access to the trading channel.",
                    ephemeral=True,
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ I don\'t have permission to assign that role.\n"
                "Make sure my role is **above** the trading role in Server Settings → Roles.",
                ephemeral=True,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Something went wrong: `{e}`",
                ephemeral=True,
            )


@tree.command(
    name="setuptrading",
    description="Create a private trading channel + access role and post the opt-in embed.",
)
@app_commands.describe(
    post_channel="Channel where the opt-in embed will be posted",
    trading_channel_name="Name for the new private trading channel (default: trading)",
    role_name="Name for the new trading access role (default: Trader)",
    category="Category to place the trading channel in (optional)",
)
@app_commands.checks.has_permissions(manage_guild=True)
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

    # ── 1. Create (or reuse) the trading access role ──────────────────────
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
            await interaction.followup.send(
                "❌ I don\'t have permission to create roles. Please give me **Manage Roles**.",
                ephemeral=True,
            )
            return

    # ── 2. Create (or reuse) the private trading channel ──────────────────
    trading_channel = None
    if existing_cfg.get("channel_id"):
        trading_channel = guild.get_channel(existing_cfg["channel_id"])

    if trading_channel is None:
        # Only the trading role (and admins) can see this channel
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
            await interaction.followup.send(
                "❌ I don\'t have permission to create channels. Please give me **Manage Channels**.",
                ephemeral=True,
            )
            return
    else:
        # Channel already exists — make sure the role has access
        try:
            await trading_channel.set_permissions(
                trading_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
        except discord.Forbidden:
            pass

    # ── 3. Post the opt-in embed ───────────────────────────────────────────
    embed = discord.Embed(
        title="🤝 Trading Channel Access",
        description=(
            f"Want access to {trading_channel.mention}?\n\n"
            "Click the button below to get the trading role. "
            "Click again to remove it."
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="Trading access is toggled by the button below.")

    view = TradingAccessView(trading_role.id)
    opt_in_message = await post_channel.send(embed=embed, view=view)

    # Register the view immediately so it works without restart
    bot.add_view(view, message_id=opt_in_message.id)

    # ── 4. Persist config ─────────────────────────────────────────────────
    TRADING_CONFIG[guild_key] = {
        "role_id": trading_role.id,
        "channel_id": trading_channel.id,
        "message_id": opt_in_message.id,
        "post_channel_id": post_channel.id,
    }
    save_trading_config(TRADING_CONFIG)

    await interaction.followup.send(
        f"✅ Done!\n"
        f"**Role:** {trading_role.mention}\n"
        f"**Channel:** {trading_channel.mention}\n"
        f"**Opt-in embed posted in:** {post_channel.mention}",
        ephemeral=True,
    )


@setup_trading.error
async def setup_trading_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ You need the **Manage Server** permission to use this command.",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Admin Announce — sends an anonymous embed to any channel
# ---------------------------------------------------------------------------

@tree.command(
    name="announce",
    description="[Admin] Send an anonymous embed message to a channel.",
)
@app_commands.describe(
    channel="Channel to send the message in",
    title="Title of the embed",
    message="Body text of the embed",
    color="Hex color for the embed (e.g. ff0000 for red). Defaults to blurple.",
    image_url="Optional image URL to attach at the bottom of the embed",
)
@app_commands.checks.has_permissions(administrator=True)
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    message: str,
    color: str = None,
    image_url: str = None,
):
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

    embed = discord.Embed(
        title=title,
        description=message,
        color=embed_color,
        timestamp=datetime.now(timezone.utc),
    )
    if image_url:
        embed.set_image(url=image_url)

    try:
        await channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Announcement sent to {channel.mention}.",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ I don't have permission to send messages in {channel.mention}.",
            ephemeral=True,
        )
    except discord.HTTPException as e:
        await interaction.response.send_message(
            f"❌ Failed to send the message: `{e}`",
            ephemeral=True,
        )


@announce.error
async def announce_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "❌ This command is restricted to server administrators.",
            ephemeral=True,
        )


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("BOT_TOKEN not set in environment variables.")
    bot.run(TOKEN)