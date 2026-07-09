from __future__ import annotations

import aiosqlite
import discord

from discord.ext import commands
from discord import app_commands

from utils.permissions import staff_only

try:
    from config import DATABASE
except ImportError:
    from database import DATABASE


class StaffLogsCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await self._init_tables()

    async def _init_tables(self):
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS staff_logs_config (
                    guild_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS staff_logs_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    staff_id TEXT NOT NULL,
                    staff_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_id TEXT,
                    target_name TEXT,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_staff_logs_guild
                ON staff_logs_entries(guild_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_staff_logs_staff
                ON staff_logs_entries(staff_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_staff_logs_target
                ON staff_logs_entries(target_id)
            """)

            await db.commit()

    def _guild_id(self, interaction: discord.Interaction) -> str:
        if interaction.guild is None:
            raise ValueError(
                "Cette commande doit être utilisée dans un serveur."
            )

        return str(interaction.guild.id)

    async def _get_log_channel_id(self, guild_id: str) -> str | None:
        async with aiosqlite.connect(DATABASE) as db:
            cursor = await db.execute("""
                SELECT channel_id
                FROM staff_logs_config
                WHERE guild_id = ?
            """, (guild_id,))

            row = await cursor.fetchone()

        if row is None:
            return None

        return row[0]

    async def _save_log_channel(
        self,
        guild_id: str,
        channel_id: str,
        updated_by: str,
    ) -> None:

        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                INSERT INTO staff_logs_config (
                    guild_id,
                    channel_id,
                    updated_by
                )
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id)
                DO UPDATE SET
                    channel_id = excluded.channel_id,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                guild_id,
                channel_id,
                updated_by,
            ))

            await db.commit()

    async def _insert_log(
        self,
        guild_id: str,
        staff_id: str,
        staff_name: str,
        action: str,
        target_id: str | None,
        target_name: str | None,
        reason: str | None,
    ) -> None:

        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("""
                INSERT INTO staff_logs_entries (
                    guild_id,
                    staff_id,
                    staff_name,
                    action,
                    target_id,
                    target_name,
                    reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                guild_id,
                staff_id,
                staff_name,
                action,
                target_id,
                target_name,
                reason,
            ))

            await db.commit()

    async def _send_to_log_channel(
        self,
        guild: discord.Guild,
        action: str,
        staff: discord.abc.User,
        target: discord.abc.User | None,
        reason: str | None,
    ) -> None:

        guild_id = str(guild.id)
        channel_id = await self._get_log_channel_id(guild_id)

        if channel_id is None:
            return

        channel = guild.get_channel(int(channel_id))

        if channel is None:
            return

        if not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="🛡️ Log staff",
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="Action",
            value=action,
            inline=False,
        )

        embed.add_field(
            name="Staff",
            value=f"{staff.mention} (`{staff.id}`)",
            inline=False,
        )

        if target is not None:
            embed.add_field(
                name="Joueur concerné",
                value=f"{target.mention} (`{target.id}`)",
                inline=False,
            )

        embed.add_field(
            name="Raison",
            value=reason or "Aucune raison indiquée.",
            inline=False,
        )

        embed.set_footer(
            text="Hamtaro Staff Logs"
        )

        await channel.send(
            embed=embed
        )

    # ==========================================================
    # CONFIG SALON LOGS
    # ==========================================================

    @app_commands.command(
        name="staff_logs_setup",
        description="Définir le salon des logs staff"
    )
    @app_commands.describe(
        channel="Salon où Hamtaro enverra les logs staff"
    )
    @staff_only()
    async def staff_logs_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            guild_id = self._guild_id(interaction)

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        await self._save_log_channel(
            guild_id=guild_id,
            channel_id=str(channel.id),
            updated_by=str(interaction.user.id),
        )

        await interaction.followup.send(
            f"✅ Salon des logs staff défini sur {channel.mention}.",
            ephemeral=True,
        )

    # ==========================================================
    # VOIR SALON LOGS
    # ==========================================================

    @app_commands.command(
        name="staff_logs_channel",
        description="Voir le salon actuel des logs staff"
    )
    @staff_only()
    async def staff_logs_channel(
        self,
        interaction: discord.Interaction,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            guild_id = self._guild_id(interaction)

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        channel_id = await self._get_log_channel_id(guild_id)

        if channel_id is None:
            await interaction.followup.send(
                "❌ Aucun salon de logs staff n'est configuré.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(int(channel_id))

        if channel is None:
            await interaction.followup.send(
                f"⚠️ Un salon est configuré, mais je ne le trouve plus : `{channel_id}`.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"🛡️ Salon actuel des logs staff : {channel.mention}",
            ephemeral=True,
        )

    # ==========================================================
    # LOG MANUEL
    # ==========================================================

    @app_commands.command(
        name="staff_log",
        description="Créer un log staff manuel"
    )
    @app_commands.describe(
        action="Action effectuée",
        member="Joueur concerné",
        reason="Raison ou détail du log"
    )
    @staff_only()
    async def staff_log(
        self,
        interaction: discord.Interaction,
        action: str,
        member: discord.Member | None = None,
        reason: str | None = None,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            guild_id = self._guild_id(interaction)

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        target_id = str(member.id) if member is not None else None
        target_name = str(member) if member is not None else None

        await self._insert_log(
            guild_id=guild_id,
            staff_id=str(interaction.user.id),
            staff_name=str(interaction.user),
            action=action,
            target_id=target_id,
            target_name=target_name,
            reason=reason,
        )

        if interaction.guild is not None:
            await self._send_to_log_channel(
                guild=interaction.guild,
                action=action,
                staff=interaction.user,
                target=member,
                reason=reason,
            )

        await interaction.followup.send(
            "✅ Log staff enregistré.",
            ephemeral=True,
        )

    # ==========================================================
    # HISTORIQUE LOGS STAFF
    # ==========================================================

    @app_commands.command(
        name="staff_logs_history",
        description="Voir les derniers logs staff"
    )
    @app_commands.describe(
        member="Filtrer par joueur concerné",
        limit="Nombre de logs à afficher entre 1 et 10"
    )
    @staff_only()
    async def staff_logs_history(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        limit: int = 5,
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        if limit < 1:
            limit = 1

        if limit > 10:
            limit = 10

        try:
            guild_id = self._guild_id(interaction)

        except ValueError as error:
            await interaction.followup.send(
                f"❌ {error}",
                ephemeral=True,
            )
            return

        async with aiosqlite.connect(DATABASE) as db:
            db.row_factory = aiosqlite.Row

            if member is None:
                cursor = await db.execute("""
                    SELECT *
                    FROM staff_logs_entries
                    WHERE guild_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (
                    guild_id,
                    limit,
                ))

            else:
                cursor = await db.execute("""
                    SELECT *
                    FROM staff_logs_entries
                    WHERE guild_id = ?
                    AND target_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (
                    guild_id,
                    str(member.id),
                    limit,
                ))

            rows = list(await cursor.fetchall())

        if not rows:
            await interaction.followup.send(
                "❌ Aucun log staff trouvé.",
                ephemeral=True,
            )
            return

        lines = []

        for row in rows:
            target = row["target_name"] or "Aucun joueur ciblé"
            reason = row["reason"] or "Aucune raison"

            lines.append(
                f"🛡️ **{row['action']}**\n"
                f"Staff : `{row['staff_name']}`\n"
                f"Cible : `{target}`\n"
                f"Raison : {reason}\n"
                f"Date : `{row['created_at']}`"
            )

        embed = discord.Embed(
            title="🛡️ Historique des logs staff",
            description="\n\n".join(lines),
            color=discord.Color.orange(),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        StaffLogsCog(bot)
    )
