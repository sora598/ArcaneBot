from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

# ── helpers ──────────────────────────────────────────────────────────────────

def _can_manage_role(bot: commands.Bot, guild: discord.Guild, role: discord.Role) -> bool:
    """Return True if the bot's top role is above the target role."""
    me = guild.me
    if me is None:
        return False
    return me.top_role > role


async def _assign_role_to_members(
    ctx: commands.Context,
    role: discord.Role,
    members: list[discord.Member],
) -> tuple[int, int]:
    """
    Attempt to add *role* to every member in *members*.
    Returns (success_count, skip_count).
    Skips members who already have the role.
    Rate-limit friendly: short sleep every 10 assignments.
    """
    success = 0
    skipped = 0
    for i, member in enumerate(members):
        if role in member.roles:
            skipped += 1
            continue
        try:
            await member.add_roles(role, reason=f"!addrole by {ctx.author}")
            success += 1
        except discord.Forbidden:
            await ctx.send(f"⚠️ Missing permission to assign {role.mention} to {member.mention}.")
        except discord.HTTPException as exc:
            await ctx.send(f"⚠️ Failed to assign role to {member.mention}: {exc}")

        # Avoid hitting the rate limit on large servers
        if i % 10 == 9:
            await asyncio.sleep(1)

    return success, skipped


# ── cog ──────────────────────────────────────────────────────────────────────

class AddRole(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # !addrole
    # ------------------------------------------------------------------
    # Usage:
    #   !addrole @Member @Role          — assign a role to one member
    #   !addrole all @Role              — assign a role to every member
    #   !addrole @ExistingRole @Role    — assign a role to every member
    #                                     who already has @ExistingRole
    # ------------------------------------------------------------------

    @commands.command(name="addrole")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def addrole(
        self,
        ctx: commands.Context,
        target: discord.Member | discord.Role | str,
        role: discord.Role,
    ):
        guild = ctx.guild  # guild_only guarantees this is not None

        # Guard: can the bot actually manage this role?
        if not _can_manage_role(self.bot, guild, role):
            await ctx.send(
                f"❌ I can't assign {role.mention} because my highest role is not above it. "
                "Please move my role higher in the server settings."
            )
            return

        # ── target: single member ─────────────────────────────────────
        if isinstance(target, discord.Member):
            if role in target.roles:
                await ctx.send(f"ℹ️ {target.mention} already has {role.mention}.")
                return
            try:
                await target.add_roles(role, reason=f"!addrole by {ctx.author}")
                await ctx.send(f"✅ Assigned {role.mention} to {target.mention}.")
            except discord.Forbidden:
                await ctx.send("❌ I don't have permission to assign that role.")
            except discord.HTTPException as exc:
                await ctx.send(f"❌ Failed to assign role: {exc}")
            return

        # ── target: "all" keyword ─────────────────────────────────────
        if isinstance(target, str) and target.lower() == "all":
            members = [m for m in guild.members if not m.bot]
            if not members:
                await ctx.send("ℹ️ No non-bot members found.")
                return

            status_msg = await ctx.send(
                f"⏳ Assigning {role.mention} to **{len(members)}** members, please wait…"
            )
            success, skipped = await _assign_role_to_members(ctx, role, members)
            await status_msg.edit(
                content=(
                    f"✅ Done! Assigned {role.mention} to **{success}** member(s). "
                    f"**{skipped}** already had it."
                )
            )
            return

        # ── target: existing role → members who have it ───────────────
        if isinstance(target, discord.Role):
            source_role = target
            if source_role == role:
                await ctx.send("⚠️ The source role and the role to assign are the same.")
                return

            members = [m for m in source_role.members if not m.bot]
            if not members:
                await ctx.send(f"ℹ️ No non-bot members have {source_role.mention}.")
                return

            status_msg = await ctx.send(
                f"⏳ Assigning {role.mention} to **{len(members)}** member(s) who have "
                f"{source_role.mention}, please wait…"
            )
            success, skipped = await _assign_role_to_members(ctx, role, members)
            await status_msg.edit(
                content=(
                    f"✅ Done! Assigned {role.mention} to **{success}** member(s) from "
                    f"{source_role.mention}. **{skipped}** already had it."
                )
            )
            return

        # ── unrecognised target ───────────────────────────────────────
        await ctx.send(
            "❌ Invalid target. Usage:\n"
            "`!addrole @Member @Role` — assign to one member\n"
            "`!addrole all @Role` — assign to everyone\n"
            "`!addrole @ExistingRole @Role` — assign to everyone with a role"
        )

    @addrole.error
    async def addrole_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need the **Manage Roles** permission to use this command.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                "❌ Missing arguments. Usage:\n"
                "`!addrole @Member @Role`\n"
                "`!addrole all @Role`\n"
                "`!addrole @ExistingRole @Role`"
            )
        elif isinstance(error, commands.BadUnionArgument | commands.BadArgument):
            await ctx.send(
                "❌ Couldn't resolve the target or role. Make sure you're mentioning a valid "
                "member, role, or the word `all`, followed by the role to assign."
            )
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("❌ This command can only be used inside a server.")
        else:
            await ctx.send("❌ Something went wrong. Please try again.")
            raise error


# ── setup ─────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AddRole(bot))