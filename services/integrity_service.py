from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import discord

from config import DATABASE, STAFF_DASHBOARD_ENABLED, STAFF_DASHBOARD_TOKEN
from services.database_maintenance import quick_check


@dataclass(slots=True)
class DoctorCheck:
    key: str
    label: str
    status: str
    message: str
    critical: bool = False

    @property
    def emoji(self) -> str:
        return {
            "ok": "✅",
            "warning": "⚠️",
            "error": "❌",
            "info": "ℹ️",
        }.get(self.status, "ℹ️")


class IntegrityService:
    """Vérifie la santé réelle du bot, de Discord et des tournois."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.db = bot.db

    async def run_doctor(
        self,
        guild: discord.Guild,
    ) -> list[DoctorCheck]:
        checks: list[DoctorCheck] = []

        database_ok, database_message = await quick_check()
        checks.append(
            DoctorCheck(
                key="database",
                label="Base SQLite",
                status="ok" if database_ok else "error",
                message=(
                    "Intégrité SQLite valide."
                    if database_ok
                    else database_message[:600]
                ),
                critical=True,
            )
        )

        persistent = (
            str(DATABASE).startswith("/data/")
            or bool(os.getenv("RAILWAY_VOLUME_MOUNT_PATH"))
        )
        checks.append(
            DoctorCheck(
                key="volume",
                label="Volume Railway",
                status="ok" if persistent else "warning",
                message=(
                    f"Base persistante : {DATABASE}"
                    if persistent
                    else "La base n'est pas située sur un volume Railway persistant."
                ),
                critical=False,
            )
        )

        failed = getattr(self.bot, "failed_extensions", {})
        checks.append(
            DoctorCheck(
                key="cogs",
                label="Modules du bot",
                status="ok" if not failed else "error",
                message=(
                    f"{len(self.bot.extensions)} modules chargés."
                    if not failed
                    else "Modules en échec : " + ", ".join(sorted(failed))
                ),
                critical=True,
            )
        )

        me = guild.me
        if me is None and self.bot.user is not None:
            me = guild.get_member(self.bot.user.id)
        if me is None:
            checks.append(
                DoctorCheck(
                    key="permissions",
                    label="Permissions Discord",
                    status="error",
                    message="Impossible de retrouver le membre Hamtaro dans le serveur.",
                    critical=True,
                )
            )
        else:
            permissions = me.guild_permissions
            required = {
                "send_messages": "Envoyer des messages",
                "embed_links": "Intégrer des liens",
                "attach_files": "Joindre des fichiers",
                "read_message_history": "Voir l'historique",
                "create_public_threads": "Créer des fils publics",
                "create_private_threads": "Créer des fils privés",
                "send_messages_in_threads": "Écrire dans les fils",
            }
            missing = [
                label
                for attribute, label in required.items()
                if not bool(getattr(permissions, attribute, False))
            ]
            checks.append(
                DoctorCheck(
                    key="permissions",
                    label="Permissions Discord",
                    status="ok" if not missing else "warning",
                    message=(
                        "Toutes les permissions principales sont présentes."
                        if not missing
                        else "Permissions manquantes : " + ", ".join(missing)
                    ),
                    critical=False,
                )
            )

        guild_id = str(guild.id)
        settings = await self.db.fetchone(
            "SELECT * FROM result_settings WHERE guild_id = ?",
            (guild_id,),
        )
        settings_data = dict(settings) if settings is not None else {}
        validation_id = settings_data.get("validation_channel_id") or os.getenv(
            "VALIDATION_RESULTS_CHANNEL_ID"
        )
        if validation_id and str(validation_id).isdigit():
            validation_channel = guild.get_channel(int(validation_id))
        else:
            validation_channel = None
        checks.append(
            DoctorCheck(
                key="validation_channel",
                label="Salon de validation",
                status="ok" if validation_channel is not None else "warning",
                message=(
                    f"Configuré sur #{validation_channel.name}."
                    if validation_channel is not None
                    else "Aucun salon de validation accessible n'est configuré."
                ),
            )
        )

        active_count = await self.db.fetchval(
            """
            SELECT COUNT(*)
            FROM tournaments
            WHERE guild_id = ?
              AND status NOT IN ('finished', 'cancelled')
            """,
            (guild_id,),
        )
        checks.append(
            DoctorCheck(
                key="active_tournaments",
                label="Tournois actifs",
                status="info",
                message=f"{int(active_count or 0)} tournoi(s) actif(s).",
            )
        )

        invalid_matches = await self.db.fetchall(
            """
            SELECT id, tournament_id, status
            FROM matches
            WHERE tournament_id IN (
                SELECT id FROM tournaments WHERE guild_id = ?
            )
            AND (
                (player1_id IS NOT NULL AND player1_id = player2_id)
                OR (
                    status IN ('validated', 'completed')
                    AND is_bye = 0
                    AND winner_id IS NULL
                )
                OR (
                    winner_id IS NOT NULL
                    AND winner_id NOT IN (player1_id, player2_id)
                )
            )
            LIMIT 25
            """,
            (guild_id,),
        )
        checks.append(
            DoctorCheck(
                key="invalid_matches",
                label="Cohérence des matchs",
                status="ok" if not invalid_matches else "error",
                message=(
                    "Aucun match incohérent détecté."
                    if not invalid_matches
                    else f"{len(invalid_matches)} match(s) incohérent(s) détecté(s)."
                ),
                critical=bool(invalid_matches),
            )
        )

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
        checks.append(
            DoctorCheck(
                key="orphan_results",
                label="Demandes de résultat",
                status="ok" if not orphan_requests else "warning",
                message=(
                    "Aucune demande orpheline."
                    if not orphan_requests
                    else f"{int(orphan_requests)} demande(s) orpheline(s)."
                ),
            )
        )

        website_loaded = "cogs.public_website" in self.bot.extensions
        checks.append(
            DoctorCheck(
                key="website",
                label="Site public",
                status="ok" if website_loaded else "error",
                message=(
                    "Le module du site est chargé."
                    if website_loaded
                    else "Le module cogs.public_website n'est pas chargé."
                ),
                critical=True,
            )
        )

        if STAFF_DASHBOARD_ENABLED:
            dashboard_ok = len(STAFF_DASHBOARD_TOKEN) >= 24
            checks.append(
                DoctorCheck(
                    key="dashboard",
                    label="Tableau de bord staff",
                    status="ok" if dashboard_ok else "warning",
                    message=(
                        "Protection par jeton configurée."
                        if dashboard_ok
                        else "Définis STAFF_DASHBOARD_TOKEN avec au moins 24 caractères."
                    ),
                )
            )

        return checks

    async def summary(self, guild: discord.Guild) -> dict[str, Any]:
        checks = await self.run_doctor(guild)
        return {
            "checks": checks,
            "ok": sum(check.status == "ok" for check in checks),
            "warnings": sum(check.status == "warning" for check in checks),
            "errors": sum(check.status == "error" for check in checks),
            "critical_errors": sum(
                check.status == "error" and check.critical for check in checks
            ),
        }
