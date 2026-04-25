from __future__ import annotations

import discord
from discord import app_commands, ui
from discord.ext import commands


HELP_PAGES = [
    {
        "title": "Bot Help",
        "description": "Slash commands in this bot. VC commands are excluded here because they have their own `/vc help`.",
        "fields": [
            ("/help", "Show this command list.", False),
            ("/announce", "Send an anonymous embed message to a channel. Admin only.", False),
            ("/setwelcome", "Set the welcome channel and rules/redirect setup. Admin only.", False),
        ],
    },
    {
        "title": "Roles & Notifications",
        "description": "Commands for creating role opt-in messages and notification posts.",
        "fields": [
            ("/notifyrole", "Post a Sea Beast Hunt notification embed with a toggle button. Admin only.", False),
            ("/setreactionrole", "Post a role toggle message with a button. Admin only.", False),
            ("/seabeasthunt", "Post a Sea Beast Hunt announcement embed. Admin only.", False),
        ],
    },
    {
        "title": "Trading", 
        "description": "Commands for trading setup and trade listings.",
        "fields": [
            ("/setuptrading", "Create the private trading channel, role, and opt-in post. Admin only.", False),
            ("/createtrade", "Create a trade listing with buttons and a discussion thread.", False),
        ],
    },
]


class HelpPager(ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.page_index = 0
        self._sync_buttons()

    def _build_embed(self) -> discord.Embed:
        page = HELP_PAGES[self.page_index]
        embed = discord.Embed(title=page["title"], description=page["description"], color=discord.Color.blurple())
        for name, value, inline in page["fields"]:
            embed.add_field(name=name, value=value, inline=inline)
        embed.set_footer(text=f"Page {self.page_index + 1} of {len(HELP_PAGES)}")
        return embed

    def _sync_buttons(self) -> None:
        self.previous_button.disabled = self.page_index == 0
        self.next_button.disabled = self.page_index >= len(HELP_PAGES) - 1

    @ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.page_index > 0:
            self.page_index -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        if self.page_index < len(HELP_PAGES) - 1:
            self.page_index += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


@app_commands.command(name="help", description="Show the slash command help menu.")
async def help_command(interaction: discord.Interaction):
    view = HelpPager()
    await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=True, delete_after=30)


async def setup(bot: commands.Bot):
    bot.tree.add_command(help_command)