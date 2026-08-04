from __future__ import annotations

import os
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import PROFESSIONAL_TOOLS_ENABLED
from services.audit_compatibility import AuditCompatibilityService
from services.audit_service import AuditService
from services.integrity_service import IntegrityService
from services.self_test_service import TournamentSelfTestService
from utils.permissions import staff_only


class CleanupConfirmView(discord.ui.View):
    def __init__(self, cog: "ProfessionalToolsCog", requester_id: int) -> None:
        super().__init__(timeout=90)
        self.cog = cog
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            "❌ Seule la personne ayant demandé le nettoyage peut confirmer.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Confirmer le nettoyage sûr",
        emoji="🧹",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        button.disabled = True
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True  # type: ignore[assignment]
        await interaction.response.edit_message(view=self)
        deleted = await self.cog.cleanup_orphans(interaction)
        await interaction.followup.send(
            "✅ Nettoyage terminé : "
            f"**{deleted['result_requests']}** demande(s) de résultat orpheline(s) et "
            f"**{deleted['contexts']}** contexte(s) de tournoi invalide(s) supprimé(s).",
            ephemeral=True,
        )
        self.stop()

    @discord.ui.button(
        label="Annuler",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True  # type: ignore[assignment]
        await interaction.response.edit_message(
            content="Nettoyage annulé.",
            embed=None,
            view=self,
        )
        self.stop()


class ProfessionalToolsCog(commands.Cog):
    """Diagnostic, tests automatiques, audit et maintenance sûre."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db
        self.integrity = IntegrityService(bot)
        self.self_test = TournamentSelfTestService(self.db)
        self.audit = AuditService(self.db)
        self.audit_compatibility = AuditCompatibilityService(self.db)

    async def cog_load(self) -> None:
        if PROFESSIONAL_TOOLS_ENABLED:
            await self.audit_compatibility.install()

    @app_commands.command(
        name="hamtaro_doctor",
        description="Faire un diagnostic complet de Hamtaro et du serveur",
    )
    @staff_only()
    async def hamtaro_doctor(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        summary = await self.integrity.summary(interaction.guild)
        checks = summary["checks"]

        colour = (
            discord.Colour.red()
            if summary["critical_errors"]
            else discord.Colour.orange()
            if summary["warnings"] or summary["errors"]
            else discord.Colour.green()
        )
        embed = discord.Embed(
            title="🩺 Diagnostic complet de Hamtaro",
            description=(
                f"✅ **{summary['ok']}** contrôle(s) correct(s) · "
                f"⚠️ **{summary['warnings']}** avertissement(s) · "
                f"❌ **{summary['errors']}** erreur(s)"
            ),
            colour=colour,
        )
        for check in checks[:25]:
            embed.add_field(
                name=f"{check.emoji} {check.label}",
                value=check.message[:1000],
                inline=False,
            )
        embed.set_footer(
            text=(
                "Les erreurs critiques doivent être corrigées avant un tournoi officiel."
            )
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="hamtaro_test",
        description="Tester automatiquement le noyau tournoi sans garder de données fictives",
    )
    @staff_only()
    async def hamtaro_test(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        steps = await self.self_test.run(
            guild_id=str(interaction.guild.id),
            actor_id=str(interaction.user.id),
        )
        success = all(step.ok for step in steps)
        embed = discord.Embed(
            title="🧪 Test automatique Hamtaro",
            description=(
                "Tous les tests sont réussis. Les données fictives ont été annulées."
                if success
                else "Au moins une étape a échoué. Aucun faux tournoi n'a été conservé."
            ),
            colour=(
                discord.Colour.green() if success else discord.Colour.red()
            ),
        )
        embed.add_field(
            name="Rapport",
            value="\n".join(
                f"{'✅' if step.ok else '❌'} **{step.label}** — {step.detail}"
                for step in steps
            )[:4000],
            inline=False,
        )
        await self.audit.record(
            guild_id=str(interaction.guild.id),
            actor_id=str(interaction.user.id),
            actor_name=str(interaction.user),
            action="self_test_completed" if success else "self_test_failed",
            entity_type="system",
            details={
                "steps": [
                    {"label": step.label, "ok": step.ok, "detail": step.detail}
                    for step in steps
                ]
            },
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="audit_history",
        description="Afficher les dernières actions sensibles enregistrées",
    )
    @app_commands.describe(
        limite="Nombre d'actions à afficher, de 1 à 25",
        code="Code facultatif d'un tournoi",
    )
    @staff_only()
    async def audit_history(
        self,
        interaction: discord.Interaction,
        limite: app_commands.Range[int, 1, 25] = 10,
        code: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)

        tournament_id: int | None = None
        if code:
            row = await self.db.fetchone(
                "SELECT id FROM tournaments WHERE guild_id = ? AND UPPER(code) = ?",
                (str(interaction.guild.id), code.strip().upper()),
            )
            if row is None:
                await interaction.followup.send(
                    "❌ Aucun tournoi ne correspond à ce code.",
                    ephemeral=True,
                )
                return
            tournament_id = int(row[0])

        entries = await self.audit.recent(
            guild_id=str(interaction.guild.id),
            limit=int(limite),
            tournament_id=tournament_id,
        )
        if not entries:
            await interaction.followup.send(
                "ℹ️ Aucune action d'audit n'est encore enregistrée.",
                ephemeral=True,
            )
            return

        lines: list[str] = []
        for entry in entries:
            target = ""
            if entry.entity_type or entry.entity_id:
                target = f" · `{entry.entity_type or '?'}:{entry.entity_id or '?'}`"
            actor = entry.actor_name or entry.actor_id or "Système"
            lines.append(
                f"`#{entry.id}` **{entry.action}**{target}\n"
                f"↳ {actor} · {entry.created_at or 'date inconnue'}"
            )

        embed = discord.Embed(
            title="📚 Journal d'audit Hamtaro",
            description="\n\n".join(lines)[:4000],
            colour=discord.Colour.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="hamtaro_cleanup",
        description="Préparer un nettoyage non destructif des données orphelines",
    )
    @staff_only()
    async def hamtaro_cleanup(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur.",
                ephemeral=True,
            )
            return
        guild_id = str(interaction.guild.id)
        orphan_requests = await self.db.fetchval(
            """
            SELECT COUNT(*)
            FROM result_requests r
            WHERE r.guild_id = ?
              AND (
                    (r.match_kind = 'bracket' AND NOT EXISTS (
                        SELECT 1 FROM matches m WHERE m.id = r.match_id
                    ))
                 OR (r.match_kind = 'swiss' AND NOT EXISTS (
                        SELECT 1 FROM swiss_matches s WHERE s.id = r.match_id
                    ))
              )
            """,
            (guild_id,),
        )
        contexts = await self.db.fetchval(
            """
            SELECT COUNT(*)
            FROM tournament_contexts c
            WHERE c.guild_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM tournaments t WHERE t.id = c.tournament_id
              )
            """,
            (guild_id,),
        )
        embed = discord.Embed(
            title="🧹 Nettoyage sûr Hamtaro",
            description=(
                "Cette action supprime uniquement les références dont la donnée principale "
                "n'existe déjà plus. Elle ne touche pas aux tournois, joueurs ou matchs valides."
            ),
            colour=discord.Colour.orange(),
        )
        embed.add_field(
            name="Éléments détectés",
            value=(
                f"Demandes de résultat orphelines : **{int(orphan_requests or 0)}**\n"
                f"Contextes de salon invalides : **{int(contexts or 0)}**"
            ),
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=CleanupConfirmView(self, interaction.user.id),
            ephemeral=True,
        )

    async def cleanup_orphans(
        self,
        interaction: discord.Interaction,
    ) -> dict[str, int]:
        if interaction.guild is None:
            raise ValueError("Serveur introuvable.")
        guild_id = str(interaction.guild.id)
        conn = self.db._connection()
        await conn.execute("BEGIN IMMEDIATE")
        try:
            result_cursor = await conn.execute(
                """
                DELETE FROM result_requests
                WHERE guild_id = ?
                  AND (
                        (match_kind = 'bracket' AND NOT EXISTS (
                            SELECT 1 FROM matches m WHERE m.id = result_requests.match_id
                        ))
                     OR (match_kind = 'swiss' AND NOT EXISTS (
                            SELECT 1 FROM swiss_matches s WHERE s.id = result_requests.match_id
                        ))
                  )
                """,
                (guild_id,),
            )
            context_cursor = await conn.execute(
                """
                DELETE FROM tournament_contexts
                WHERE guild_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM tournaments t
                      WHERE t.id = tournament_contexts.tournament_id
                  )
                """,
                (guild_id,),
            )
            deleted = {
                "result_requests": max(0, int(result_cursor.rowcount or 0)),
                "contexts": max(0, int(context_cursor.rowcount or 0)),
            }
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

        await self.audit.record(
            guild_id=guild_id,
            actor_id=str(interaction.user.id),
            actor_name=str(interaction.user),
            action="safe_orphan_cleanup",
            entity_type="system",
            details=deleted,
        )
        return deleted

    @app_commands.command(
        name="staff_dashboard",
        description="Afficher l'adresse du tableau de bord staff protégé",
    )
    @staff_only()
    async def staff_dashboard(self, interaction: discord.Interaction) -> None:
        base_url = os.getenv("WEBSITE_BASE_URL", "").strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "❌ WEBSITE_BASE_URL n'est pas correctement configurée.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🛡️ Tableau de bord staff Hamtaro",
            description=(
                "Le tableau de bord est protégé par le jeton Railway "
                "`STAFF_DASHBOARD_TOKEN`. Ne partage jamais ce jeton dans un salon."
            ),
            url=f"{base_url}/staff",
            colour=discord.Colour.dark_gold(),
        )
        view = discord.ui.View(timeout=120)
        view.add_item(
            discord.ui.Button(
                label="Ouvrir le tableau de bord",
                emoji="🛡️",
                style=discord.ButtonStyle.link,
                url=f"{base_url}/staff",
            )
        )
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfessionalToolsCog(bot))
