from __future__ import annotations

import re
import unicodedata
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import error_embed, success_embed
from utils.permissions import is_staff_member


def normalize_archetype_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


class ArchetypeCatalogCog(commands.Cog):
    """Catalogue de decks indépendant des inscriptions de joueurs."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db

    async def cog_load(self) -> None:
        await self._ensure_table()

    async def _ensure_table(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS archetype_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                description TEXT,
                playstyle TEXT,
                format TEXT,
                artwork_url TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, normalized_name)
            )
            """
        )
        await self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_archetype_catalog_guild_name
            ON archetype_catalog(guild_id, normalized_name)
            """
        )
        await self.db.commit()

    @staticmethod
    def _is_staff(member: discord.abc.User) -> bool:
        return bool(
            isinstance(member, discord.Member)
            and (
                member.guild_permissions.administrator
                or member.guild_permissions.manage_guild
                or is_staff_member(member)
            )
        )

    async def _ensure_staff(self, interaction: discord.Interaction) -> bool:
        if self._is_staff(interaction.user):
            return True
        await interaction.response.send_message(
            "❌ Seul le staff peut modifier le catalogue des archétypes.",
            ephemeral=True,
        )
        return False

    async def _autocomplete_name(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        await self._ensure_table()
        rows = await self.db.fetchall(
            """
            SELECT name FROM archetype_catalog
            WHERE guild_id = ? AND LOWER(name) LIKE LOWER(?)
            ORDER BY name LIMIT 25
            """,
            (str(interaction.guild.id), f"%{current.strip()}%"),
        )
        return [
            app_commands.Choice(name=str(row["name"])[:100], value=str(row["name"]))
            for row in rows
        ]

    @app_commands.command(
        name="archetype_add",
        description="Créer une fiche de deck/archétype même sans joueur inscrit",
    )
    @app_commands.describe(
        name="Nom officiel affiché sur le site",
        description="Courte présentation de l'archétype",
        playstyle="Style de jeu ou plan principal",
        format="Format de référence facultatif",
        artwork_url="Artwork par défaut facultatif",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def archetype_add(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str | None = None,
        playstyle: str | None = None,
        format: str | None = None,
        artwork_url: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        if interaction.guild is None:
            return
        clean_name = " ".join(name.split()).strip()
        normalized = normalize_archetype_name(clean_name)
        if len(clean_name) < 2 or not normalized:
            await interaction.response.send_message(
                "❌ Le nom de l'archétype est invalide.", ephemeral=True
            )
            return
        await self._ensure_table()
        existing = await self.db.fetchone(
            "SELECT id FROM archetype_catalog WHERE guild_id = ? AND normalized_name = ?",
            (str(interaction.guild.id), normalized),
        )
        if existing is not None:
            await interaction.response.send_message(
                "❌ Cette fiche existe déjà. Utilise `/archetype_edit`.", ephemeral=True
            )
            return
        await self.db.execute(
            """
            INSERT INTO archetype_catalog (
                guild_id, name, normalized_name, description, playstyle,
                format, artwork_url, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(interaction.guild.id),
                clean_name,
                normalized,
                (description or "").strip() or None,
                (playstyle or "").strip() or None,
                (format or "").strip() or None,
                (artwork_url or "").strip() or None,
                str(interaction.user.id),
            ),
        )
        await self.db.commit()
        await interaction.response.send_message(
            embed=success_embed(
                title="Archétype ajouté",
                description=(
                    f"**{clean_name}** existe maintenant dans le catalogue, même avec "
                    "0 joueur. Les futures inscriptions portant ce nom seront rattachées "
                    "automatiquement à cette fiche."
                ),
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="archetype_edit",
        description="Modifier une fiche de deck/archétype du catalogue",
    )
    @app_commands.describe(
        name="Archétype à modifier",
        new_name="Nouveau nom facultatif",
        description="Nouvelle description facultative",
        playstyle="Nouveau style de jeu facultatif",
        format="Nouveau format de référence facultatif",
        artwork_url="Nouvel artwork facultatif",
    )
    @app_commands.autocomplete(name=_autocomplete_name)
    @app_commands.default_permissions(manage_guild=True)
    async def archetype_edit(
        self,
        interaction: discord.Interaction,
        name: str,
        new_name: str | None = None,
        description: str | None = None,
        playstyle: str | None = None,
        format: str | None = None,
        artwork_url: str | None = None,
    ) -> None:
        if not await self._ensure_staff(interaction):
            return
        if interaction.guild is None:
            return
        await self._ensure_table()
        normalized = normalize_archetype_name(name)
        row = await self.db.fetchone(
            "SELECT * FROM archetype_catalog WHERE guild_id = ? AND normalized_name = ?",
            (str(interaction.guild.id), normalized),
        )
        if row is None:
            await interaction.response.send_message(
                embed=error_embed(title="Archétype introuvable", description=name),
                ephemeral=True,
            )
            return
        current = dict(row)
        final_name = " ".join((new_name or current["name"]).split()).strip()
        final_normalized = normalize_archetype_name(final_name)
        await self.db.execute(
            """
            UPDATE archetype_catalog
            SET name = ?, normalized_name = ?, description = ?, playstyle = ?,
                format = ?, artwork_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                final_name,
                final_normalized,
                current.get("description") if description is None else (description.strip() or None),
                current.get("playstyle") if playstyle is None else (playstyle.strip() or None),
                current.get("format") if format is None else (format.strip() or None),
                current.get("artwork_url") if artwork_url is None else (artwork_url.strip() or None),
                int(current["id"]),
            ),
        )
        await self.db.commit()
        await interaction.response.send_message(
            embed=success_embed(
                title="Archétype mis à jour",
                description=f"La fiche **{final_name}** a été enregistrée.",
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="archetype_list",
        description="Voir les fiches de decks/archétypes créées manuellement",
    )
    async def archetype_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Serveur requis.", ephemeral=True)
            return
        await self._ensure_table()
        rows = await self.db.fetchall(
            """
            SELECT name, format, playstyle FROM archetype_catalog
            WHERE guild_id = ? ORDER BY LOWER(name) LIMIT 50
            """,
            (str(interaction.guild.id),),
        )
        if not rows:
            await interaction.response.send_message(
                "📭 Aucune fiche d'archétype indépendante n'a encore été créée.",
                ephemeral=True,
            )
            return
        lines = []
        for row in rows:
            item = dict(row)
            details = []
            if item.get("format"):
                details.append(str(item["format"]))
            if item.get("playstyle"):
                details.append(str(item["playstyle"]))
            suffix = f" — {' · '.join(details)}" if details else ""
            lines.append(f"• **{item['name']}**{suffix}")
        embed = discord.Embed(
            title="🎴 Catalogue des archétypes Hamtaro",
            description="\n".join(lines)[:4000],
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ArchetypeCatalogCog(bot))
