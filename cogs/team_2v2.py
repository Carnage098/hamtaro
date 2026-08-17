from __future__ import annotations

import math
import random
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands

from services.team_2v2_service import (
    A_WIN,
    B_WIN,
    DOUBLE_LOSS,
    resolve_encounter,
    standing_sort_key,
)


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS duo_teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT NOT NULL,
        name TEXT NOT NULL COLLATE NOCASE,
        captain_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(guild_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_team_members (
        team_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        slot INTEGER NOT NULL CHECK(slot IN (1, 2)),
        display_name TEXT NOT NULL,
        deck TEXT,
        joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(team_id, user_id),
        UNIQUE(team_id, slot),
        FOREIGN KEY(team_id) REFERENCES duo_teams(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_team_invites (
        team_id INTEGER PRIMARY KEY,
        invited_user_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_id) REFERENCES duo_teams(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_tournament_modes (
        tournament_id INTEGER PRIMARY KEY,
        participant_mode TEXT NOT NULL DEFAULT 'solo'
            CHECK(participant_mode IN ('solo', 'duo')),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_tournaments (
        tournament_id INTEGER PRIMARY KEY,
        mode TEXT NOT NULL CHECK(mode IN ('swiss', 'elimination')),
        status TEXT NOT NULL DEFAULT 'registration',
        current_round INTEGER NOT NULL DEFAULT 0,
        total_rounds INTEGER NOT NULL DEFAULT 0,
        winner_team_id INTEGER,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP,
        FOREIGN KEY(winner_team_id) REFERENCES duo_teams(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_tournament_entries (
        tournament_id INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        seed INTEGER,
        dropped INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(tournament_id, team_id),
        FOREIGN KEY(team_id) REFERENCES duo_teams(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_entry_members (
        tournament_id INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        slot INTEGER NOT NULL,
        display_name TEXT NOT NULL,
        deck TEXT,
        PRIMARY KEY(tournament_id, team_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL,
        round_no INTEGER NOT NULL,
        match_no INTEGER NOT NULL,
        team_a_id INTEGER NOT NULL,
        team_b_id INTEGER,
        mode TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        winner_team_id INTEGER,
        points_a INTEGER NOT NULL DEFAULT 0,
        points_b INTEGER NOT NULL DEFAULT 0,
        double_loss_count INTEGER NOT NULL DEFAULT 0,
        bye INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(team_a_id) REFERENCES duo_teams(id),
        FOREIGN KEY(team_b_id) REFERENCES duo_teams(id),
        FOREIGN KEY(winner_team_id) REFERENCES duo_teams(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_boards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        board_no INTEGER NOT NULL CHECK(board_no IN (1, 2, 3)),
        player_a_id TEXT NOT NULL,
        player_b_id TEXT NOT NULL,
        result TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        pending_result TEXT,
        reported_by TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(match_id, board_no),
        FOREIGN KEY(match_id) REFERENCES duo_matches(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duo_standings (
        tournament_id INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        points INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0,
        double_losses INTEGER NOT NULL DEFAULT 0,
        byes INTEGER NOT NULL DEFAULT 0,
        board_wins INTEGER NOT NULL DEFAULT 0,
        board_losses INTEGER NOT NULL DEFAULT 0,
        matches_played INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(tournament_id, team_id),
        FOREIGN KEY(team_id) REFERENCES duo_teams(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_duo_matches_tournament_round ON duo_matches(tournament_id, round_no)",
    "CREATE INDEX IF NOT EXISTS idx_duo_boards_match ON duo_boards(match_id)",
)


def _role_names(member: discord.Member) -> set[str]:
    return {role.name.casefold() for role in member.roles}


def _is_staff(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    if user.guild_permissions.administrator or user.guild_permissions.manage_guild:
        return True
    allowed = {"admin", "staff", "modo", "modérateur", "moderateur", "🛑modo"}
    return bool(_role_names(user) & allowed)


async def _require_staff(interaction: discord.Interaction) -> bool:
    if _is_staff(interaction):
        return True
    await interaction.response.send_message(
        "⛔ Cette action est réservée au staff Hamtaro.",
        ephemeral=True,
    )
    return False


class Team2v2Cog(commands.Cog):
    duo = app_commands.Group(
        name="duo",
        description="Tournois Hamtaro en équipes de 2",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        for statement in SCHEMA:
            await self.bot.db.execute(statement)
        await self.bot.db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _team(self, team_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM duo_teams WHERE id = ?",
            (team_id,),
        )

    async def _team_name(self, team_id: int | None) -> str:
        if team_id is None:
            return "—"
        row = await self._team(team_id)
        return row["name"] if row else f"Equipe #{team_id}"

    async def _members(self, team_id: int, tournament_id: int | None = None):
        if tournament_id is not None:
            rows = await self.bot.db.fetchall(
                """
                SELECT user_id, slot, display_name, deck
                FROM duo_entry_members
                WHERE tournament_id = ? AND team_id = ?
                ORDER BY slot
                """,
                (tournament_id, team_id),
            )
            if rows:
                return rows
        return await self.bot.db.fetchall(
            """
            SELECT user_id, slot, display_name, deck
            FROM duo_team_members
            WHERE team_id = ?
            ORDER BY slot
            """,
            (team_id,),
        )

    async def _member_side(self, match, user_id: int | str) -> str | None:
        uid = str(user_id)
        for row in await self._members(match["team_a_id"], match["tournament_id"]):
            if str(row["user_id"]) == uid:
                return "a"
        if match["team_b_id"] is not None:
            for row in await self._members(match["team_b_id"], match["tournament_id"]):
                if str(row["user_id"]) == uid:
                    return "b"
        return None

    async def _registered_elsewhere(
        self,
        tournament_id: int,
        team_id: int,
    ) -> str | None:
        members = await self._members(team_id)
        for member in members:
            row = await self.bot.db.fetchone(
                """
                SELECT t.name AS team_name
                FROM duo_tournament_entries e
                JOIN duo_team_members m ON m.team_id = e.team_id
                JOIN duo_teams t ON t.id = e.team_id
                WHERE e.tournament_id = ?
                  AND m.user_id = ?
                  AND e.team_id <> ?
                LIMIT 1
                """,
                (tournament_id, member["user_id"], team_id),
            )
            if row:
                return row["team_name"]
        return None

    async def set_participant_mode(self, tournament_id: int, participant_mode: str) -> str:
        """Enregistre le type de participant du tournoi Hamtaro natif."""
        normalized = str(participant_mode or "solo").strip().lower()
        aliases = {
            "1v1": "solo",
            "solo": "solo",
            "player": "solo",
            "players": "solo",
            "2v2": "duo",
            "duo": "duo",
            "team": "duo",
            "teams": "duo",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"solo", "duo"}:
            raise ValueError("Type de participants inconnu.")
        await self.bot.db.execute(
            """
            INSERT INTO duo_tournament_modes(tournament_id, participant_mode)
            VALUES (?, ?)
            ON CONFLICT(tournament_id) DO UPDATE SET
                participant_mode = excluded.participant_mode,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(tournament_id), normalized),
            commit=True,
        )
        return normalized

    async def get_participant_mode(self, tournament_id: int) -> str:
        """Les anciens tournois restent automatiquement des tournois solo."""
        row = await self.bot.db.fetchone(
            "SELECT participant_mode FROM duo_tournament_modes WHERE tournament_id = ?",
            (int(tournament_id),),
        )
        if not row:
            return "solo"
        value = str(row["participant_mode"] or "solo").strip().lower()
        return "duo" if value == "duo" else "solo"

    async def is_duo_tournament(self, tournament_id: int) -> bool:
        return await self.get_participant_mode(tournament_id) == "duo"

    async def participant_label(self, tournament_id: int) -> str:
        return "👥 Équipes 2v2" if await self.is_duo_tournament(tournament_id) else "👤 Solo 1v1"

    async def _active_teams_for_user(self, guild_id: int | str, user_id: int | str):
        return await self.bot.db.fetchall(
            """
            SELECT DISTINCT t.*
            FROM duo_teams t
            JOIN duo_team_members m ON m.team_id = t.id
            WHERE t.guild_id = ?
              AND m.user_id = ?
              AND t.status = 'active'
            ORDER BY t.id
            """,
            (str(guild_id), str(user_id)),
        )

    async def _pick_team_for_user(
        self,
        *,
        guild_id: int | str,
        user_id: int | str,
        team_id: int | None = None,
    ):
        if team_id is not None:
            team = await self._team(int(team_id))
            if not team or str(team["guild_id"]) != str(guild_id) or team["status"] != "active":
                raise ValueError("Cette équipe 2v2 n'existe pas ou n'est pas complète.")
            member = await self.bot.db.fetchone(
                "SELECT 1 FROM duo_team_members WHERE team_id = ? AND user_id = ?",
                (int(team_id), str(user_id)),
            )
            if not member:
                raise ValueError("Tu ne fais pas partie de cette équipe.")
            return team

        teams = await self._active_teams_for_user(guild_id, user_id)
        if not teams:
            raise ValueError(
                "Tu n'as aucune équipe 2v2 complète. Crée-la avec `/duo team_create`, "
                "puis ton partenaire utilise `/duo team_accept`."
            )
        if len(teams) > 1:
            ids = ", ".join(f"{row['name']} (#{row['id']})" for row in teams[:8])
            raise ValueError(
                "Tu appartiens à plusieurs équipes. Relance `/register` avec `team_id`. "
                f"Équipes disponibles : {ids}"
            )
        return teams[0]

    async def register_from_native(
        self,
        interaction: discord.Interaction,
        tournament,
        team_id: int | None = None,
        deck: str | None = None,
    ) -> bool:
        """Branche 2v2 appelée par la commande native /register."""
        if not await self.is_duo_tournament(int(tournament.id)):
            return False
        if interaction.guild_id is None:
            raise ValueError("Cette commande doit être utilisée sur un serveur.")

        team = await self._pick_team_for_user(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            team_id=team_id,
        )
        # Si le joueur renseigne un deck directement dans /register, on met
        # à jour son slot avant de figer le roster du tournoi.
        if deck is not None and str(deck).strip():
            await self.bot.db.execute(
                "UPDATE duo_team_members SET deck = ? WHERE team_id = ? AND user_id = ?",
                (str(deck).strip(), int(team["id"]), str(interaction.user.id)),
                commit=True,
            )

        members = await self._members(int(team["id"]))
        if len(members) != 2:
            raise ValueError("L'équipe doit avoir exactement deux joueurs.")

        conflict = await self._registered_elsewhere(int(tournament.id), int(team["id"]))
        if conflict:
            raise ValueError(f"Un membre est déjà inscrit avec **{conflict}**.")

        existing = await self.bot.db.fetchone(
            "SELECT 1 FROM duo_tournament_entries WHERE tournament_id = ? AND team_id = ?",
            (int(tournament.id), int(team["id"])),
        )
        if existing:
            raise ValueError(f"**{team['name']}** est déjà inscrite à ce tournoi.")

        current = int(await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM duo_tournament_entries WHERE tournament_id = ?",
            (int(tournament.id),),
        ) or 0)
        capacity = int(getattr(tournament, "max_players", 0) or 0)
        if capacity > 0 and current >= capacity:
            raise ValueError(f"Le tournoi est complet ({current}/{capacity} équipes).")

        seed = current + 1
        await self.bot.db.execute(
            """
            INSERT INTO duo_tournament_entries(tournament_id, team_id, seed)
            VALUES (?, ?, ?)
            """,
            (int(tournament.id), int(team["id"]), seed),
        )
        for member in members:
            await self.bot.db.execute(
                """
                INSERT INTO duo_entry_members(
                    tournament_id, team_id, user_id, slot, display_name, deck
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(tournament.id), int(team["id"]), member["user_id"],
                    member["slot"], member["display_name"], member["deck"],
                ),
            )
        await self.bot.db.commit()
        current += 1
        await interaction.followup.send(
            f"✅ **{team['name']}** est inscrite au tournoi **{tournament.name}** "
            f"(`{tournament.code}`).\n👥 Équipes : **{current}/{capacity or '∞'}**",
            ephemeral=True,
        )
        return True

    async def unregister_from_native(self, interaction: discord.Interaction, tournament) -> bool:
        if not await self.is_duo_tournament(int(tournament.id)):
            return False
        row = await self.bot.db.fetchone(
            """
            SELECT e.team_id, t.name
            FROM duo_tournament_entries e
            JOIN duo_teams t ON t.id = e.team_id
            JOIN duo_entry_members m
              ON m.tournament_id = e.tournament_id AND m.team_id = e.team_id
            WHERE e.tournament_id = ? AND m.user_id = ?
            LIMIT 1
            """,
            (int(tournament.id), str(interaction.user.id)),
        )
        if not row:
            raise ValueError("Ton équipe n'est pas inscrite à ce tournoi.")
        team_id = int(row["team_id"])
        await self.bot.db.execute(
            "DELETE FROM duo_entry_members WHERE tournament_id = ? AND team_id = ?",
            (int(tournament.id), team_id),
        )
        await self.bot.db.execute(
            "DELETE FROM duo_tournament_entries WHERE tournament_id = ? AND team_id = ?",
            (int(tournament.id), team_id),
            commit=True,
        )
        await interaction.followup.send(
            f"✅ L'équipe **{row['name']}** est désinscrite du tournoi.",
            ephemeral=True,
        )
        return True

    async def update_deck_from_native(
        self,
        interaction: discord.Interaction,
        tournament,
        deck: str,
    ) -> bool:
        if not await self.is_duo_tournament(int(tournament.id)):
            return False
        uid = str(interaction.user.id)
        row = await self.bot.db.fetchone(
            """
            SELECT team_id FROM duo_entry_members
            WHERE tournament_id = ? AND user_id = ?
            LIMIT 1
            """,
            (int(tournament.id), uid),
        )
        if not row:
            raise ValueError("Tu n'es pas inscrit à ce tournoi 2v2.")
        team_id = int(row["team_id"])
        await self.bot.db.execute(
            "UPDATE duo_entry_members SET deck = ? WHERE tournament_id = ? AND user_id = ?",
            (deck.strip(), int(tournament.id), uid),
        )
        await self.bot.db.execute(
            "UPDATE duo_team_members SET deck = ? WHERE team_id = ? AND user_id = ?",
            (deck.strip(), team_id, uid),
            commit=True,
        )
        await interaction.followup.send(
            f"✅ Ton deck 2v2 est maintenant **{deck.strip()}**.",
            ephemeral=True,
        )
        return True

    async def players_from_native(self, interaction: discord.Interaction, tournament) -> bool:
        if not await self.is_duo_tournament(int(tournament.id)):
            return False
        rows = await self.bot.db.fetchall(
            """
            SELECT e.seed, e.team_id, t.name
            FROM duo_tournament_entries e
            JOIN duo_teams t ON t.id = e.team_id
            WHERE e.tournament_id = ? AND e.dropped = 0
            ORDER BY COALESCE(e.seed, 999999), e.team_id
            """,
            (int(tournament.id),),
        )
        if not rows:
            text = "👥 Aucune équipe inscrite pour le moment."
        else:
            lines = [f"👥 **Équipes inscrites — {tournament.name}**"]
            for index, row in enumerate(rows, 1):
                members = await self._members(int(row["team_id"]), int(tournament.id))
                roster = " + ".join(
                    f"<@{m['user_id']}> ({m['deck'] or 'deck ?'})" for m in members
                )
                lines.append(f"**{index}. {row['name']}** — {roster}")
            lines.append(f"\nTotal : **{len(rows)}/{int(getattr(tournament, 'max_players', 0) or 0) or '∞'} équipes**")
            text = "\n".join(lines)
        await interaction.followup.send(text[:1900], ephemeral=False)
        return True

    async def start_from_native(
        self,
        tournament_id: int,
        mode: str,
        total_rounds: int = 0,
    ) -> str:
        """Lance automatiquement le moteur 2v2 depuis /start_tournament ou /swiss_start."""
        if not await self.is_duo_tournament(tournament_id):
            raise ValueError("Ce tournoi n'est pas configuré en 2v2.")
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in {"swiss", "elimination"}:
            raise ValueError("Structure 2v2 inconnue.")

        existing = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (int(tournament_id),),
        )
        if existing and existing["status"] in {"running", "finished"}:
            raise ValueError("Ce tournoi 2v2 est déjà lancé ou terminé.")

        entries = await self.bot.db.fetchall(
            """
            SELECT team_id FROM duo_tournament_entries
            WHERE tournament_id = ? AND dropped = 0
            ORDER BY COALESCE(seed, 999999), team_id
            """,
            (int(tournament_id),),
        )
        team_ids = [int(row["team_id"]) for row in entries]
        if len(team_ids) < 2:
            raise ValueError("Il faut au moins 2 équipes complètes pour lancer le tournoi.")

        if normalized_mode == "swiss":
            rounds = int(total_rounds) if int(total_rounds or 0) > 0 else max(1, math.ceil(math.log2(len(team_ids))))
        else:
            rounds = max(1, math.ceil(math.log2(len(team_ids))))

        await self.bot.db.execute(
            """
            INSERT INTO duo_tournaments(
                tournament_id, mode, status, current_round, total_rounds
            ) VALUES (?, ?, 'running', 0, ?)
            ON CONFLICT(tournament_id) DO UPDATE SET
                mode = excluded.mode,
                status = 'running',
                current_round = 0,
                total_rounds = excluded.total_rounds,
                winner_team_id = NULL,
                finished_at = NULL
            """,
            (int(tournament_id), normalized_mode, rounds),
        )
        for team_id in team_ids:
            await self.bot.db.execute(
                """
                INSERT INTO duo_standings(tournament_id, team_id)
                VALUES (?, ?)
                ON CONFLICT(tournament_id, team_id) DO NOTHING
                """,
                (int(tournament_id), team_id),
            )
        await self.bot.db.execute(
            """
            UPDATE tournaments
            SET status = 'running', started_at = CURRENT_TIMESTAMP,
                current_round = 1, total_rounds = ?
            WHERE id = ?
            """,
            (rounds, int(tournament_id)),
        )
        await self.bot.db.commit()

        if normalized_mode == "swiss":
            await self._create_swiss_round(int(tournament_id), 1)
            return await self.format_swiss_pairings(int(tournament_id), 1)
        await self._create_elimination_round(int(tournament_id), 1, team_ids)
        return await self.format_elimination_round(int(tournament_id), 1)

    async def format_elimination_round(self, tournament_id: int, round_no: int | None = None) -> str:
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (int(tournament_id),),
        )
        if not cfg:
            raise ValueError("Tournoi 2v2 non lancé.")
        round_no = int(round_no or cfg["current_round"])
        rows = await self.bot.db.fetchall(
            """
            SELECT * FROM duo_matches
            WHERE tournament_id = ? AND round_no = ?
            ORDER BY match_no
            """,
            (int(tournament_id), round_no),
        )
        lines = [f"🏆 **Élimination 2v2 — ronde {round_no}**"]
        for row in rows:
            a = await self._team_name(int(row["team_a_id"]))
            b = await self._team_name(int(row["team_b_id"])) if row["team_b_id"] is not None else "BYE"
            lines.append(f"**Match #{row['id']}** · {a} 🆚 {b} · `{row['status']}`")
        return "\n".join(lines)

    async def format_swiss_pairings(self, tournament_id: int, round_no: int | None = None) -> str:
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (int(tournament_id),),
        )
        if not cfg or cfg["mode"] != "swiss":
            raise ValueError("Les rondes suisses 2v2 ne sont pas lancées.")
        round_no = int(round_no or cfg["current_round"])
        rows = await self.bot.db.fetchall(
            """
            SELECT * FROM duo_matches
            WHERE tournament_id = ? AND round_no = ?
            ORDER BY match_no
            """,
            (int(tournament_id), round_no),
        )
        lines = [f"🇨🇭 **Ronde suisse 2v2 — ronde {round_no}**"]
        for index, row in enumerate(rows, 1):
            a = await self._team_name(int(row["team_a_id"]))
            b = await self._team_name(int(row["team_b_id"])) if row["team_b_id"] is not None else "BYE"
            lines.append(f"**Table {index} · match #{row['id']}** — {a} 🆚 {b}")
            if not row["bye"]:
                boards = await self.bot.db.fetchall(
                    "SELECT * FROM duo_boards WHERE match_id = ? ORDER BY board_no",
                    (int(row["id"]),),
                )
                for board in boards:
                    label = "Décisif" if int(board["board_no"]) == 3 else f"Duel {board['board_no']}"
                    lines.append(f"↳ {label}: <@{board['player_a_id']}> vs <@{board['player_b_id']}> · `{board['status']}`")
        return "\n".join(lines)[:1900]

    async def swiss_next_from_native(self, tournament_id: int) -> str:
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (int(tournament_id),),
        )
        if not cfg or cfg["mode"] != "swiss" or cfg["status"] != "running":
            raise ValueError("Aucun tournoi suisse 2v2 actif.")
        current = int(cfg["current_round"])
        pending = int(await self.bot.db.fetchval(
            """
            SELECT COUNT(*) FROM duo_matches
            WHERE tournament_id = ? AND round_no = ?
              AND status NOT IN ('complete', 'complete_penalized', 'double_loss')
            """,
            (int(tournament_id), current),
        ) or 0)
        if pending:
            raise ValueError("La ronde actuelle n'est pas terminée.")
        if current >= int(cfg["total_rounds"]):
            await self.bot.db.execute(
                "UPDATE duo_tournaments SET status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE tournament_id = ?",
                (int(tournament_id),),
            )
            await self.bot.db.execute(
                "UPDATE tournaments SET status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(tournament_id),),
                commit=True,
            )
            return "🏁 Toutes les rondes suisses 2v2 sont terminées."
        next_round = current + 1
        await self._create_swiss_round(int(tournament_id), next_round)
        await self.bot.db.execute(
            "UPDATE tournaments SET current_round = ? WHERE id = ?",
            (next_round, int(tournament_id)),
            commit=True,
        )
        return await self.format_swiss_pairings(int(tournament_id), next_round)

    async def format_swiss_standings(self, tournament_id: int) -> str:
        await self._recompute_standings(int(tournament_id))
        rows = await self._standings_rows(int(tournament_id))
        if not rows:
            raise ValueError("Classement 2v2 vide.")
        lines = [
            "🏆 **Classement suisse 2v2**",
            "`DL` = double loss. À points égaux, toute équipe sans DL passe devant.",
            "",
        ]
        for rank, row in enumerate(rows, 1):
            lines.append(
                f"**{rank}. {row['team_name']}** — **{row['points']} pts** · "
                f"{row['wins']}V/{row['losses']}D · DL {row['double_losses']} · "
                f"Buchholz {row['buchholz']} · Boards {row['board_wins']}-{row['board_losses']}"
            )
        return "\n".join(lines)[:1900]

    async def format_swiss_status(self, tournament_id: int) -> str:
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (int(tournament_id),),
        )
        if not cfg or cfg["mode"] != "swiss":
            raise ValueError("Les rondes suisses 2v2 ne sont pas lancées.")
        pending = int(await self.bot.db.fetchval(
            """
            SELECT COUNT(*) FROM duo_matches
            WHERE tournament_id = ? AND round_no = ?
              AND status NOT IN ('complete', 'complete_penalized', 'double_loss')
            """,
            (int(tournament_id), int(cfg["current_round"])),
        ) or 0)
        return (
            f"🇨🇭 **Suisse 2v2** · statut `{cfg['status']}` · "
            f"ronde **{cfg['current_round']}/{cfg['total_rounds']}** · "
            f"matchs restant à terminer : **{pending}**"
        )

    async def reset_swiss_from_native(self, tournament_id: int) -> None:
        ids = await self.bot.db.fetchall(
            "SELECT id FROM duo_matches WHERE tournament_id = ?",
            (int(tournament_id),),
        )
        for row in ids:
            await self.bot.db.execute("DELETE FROM duo_boards WHERE match_id = ?", (int(row["id"]),))
        await self.bot.db.execute("DELETE FROM duo_matches WHERE tournament_id = ?", (int(tournament_id),))
        await self.bot.db.execute("DELETE FROM duo_standings WHERE tournament_id = ?", (int(tournament_id),))
        await self.bot.db.execute("DELETE FROM duo_tournaments WHERE tournament_id = ?", (int(tournament_id),))
        await self.bot.db.execute(
            "UPDATE tournaments SET status = 'registration', current_round = 0, total_rounds = 0, started_at = NULL, finished_at = NULL WHERE id = ?",
            (int(tournament_id),),
            commit=True,
        )

    async def _create_match(
        self,
        tournament_id: int,
        round_no: int,
        match_no: int,
        team_a_id: int,
        team_b_id: int | None,
        mode: str,
    ) -> int:
        if team_b_id is None:
            cursor = await self.bot.db.execute(
                """
                INSERT INTO duo_matches(
                    tournament_id, round_no, match_no,
                    team_a_id, team_b_id, mode, status,
                    winner_team_id, points_a, points_b, bye
                ) VALUES (?, ?, ?, ?, NULL, ?, 'complete', ?, ?, 0, 1)
                """,
                (
                    tournament_id,
                    round_no,
                    match_no,
                    team_a_id,
                    mode,
                    team_a_id,
                    3 if mode == "swiss" else 0,
                ),
                commit=True,
            )
            return int(cursor.lastrowid)

        cursor = await self.bot.db.execute(
            """
            INSERT INTO duo_matches(
                tournament_id, round_no, match_no,
                team_a_id, team_b_id, mode
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tournament_id, round_no, match_no, team_a_id, team_b_id, mode),
            commit=True,
        )
        match_id = int(cursor.lastrowid)
        members_a = await self._members(team_a_id, tournament_id)
        members_b = await self._members(team_b_id, tournament_id)
        if len(members_a) != 2 or len(members_b) != 2:
            raise RuntimeError("Une équipe 2v2 n'a pas exactement deux membres.")

        for board_no in (1, 2):
            a = members_a[board_no - 1]
            b = members_b[board_no - 1]
            await self.bot.db.execute(
                """
                INSERT INTO duo_boards(
                    match_id, board_no, player_a_id, player_b_id
                ) VALUES (?, ?, ?, ?)
                """,
                (match_id, board_no, a["user_id"], b["user_id"]),
            )
        await self.bot.db.commit()
        return match_id

    async def _create_tiebreak(self, match_id: int) -> None:
        existing = await self.bot.db.fetchone(
            "SELECT id FROM duo_boards WHERE match_id = ? AND board_no = 3",
            (match_id,),
        )
        if existing:
            return

        match = await self.bot.db.fetchone(
            "SELECT * FROM duo_matches WHERE id = ?",
            (match_id,),
        )
        boards = await self.bot.db.fetchall(
            """
            SELECT * FROM duo_boards
            WHERE match_id = ? AND board_no IN (1, 2)
            ORDER BY board_no
            """,
            (match_id,),
        )
        if len(boards) != 2:
            return

        winner_a = None
        winner_b = None
        for board in boards:
            if board["result"] == A_WIN:
                winner_a = board["player_a_id"]
            elif board["result"] == B_WIN:
                winner_b = board["player_b_id"]

        if winner_a is None or winner_b is None:
            return

        await self.bot.db.execute(
            """
            INSERT INTO duo_boards(
                match_id, board_no, player_a_id, player_b_id
            ) VALUES (?, 3, ?, ?)
            """,
            (match_id, winner_a, winner_b),
        )
        await self.bot.db.execute(
            """
            UPDATE duo_matches
            SET status = 'tiebreak', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (match_id,),
            commit=True,
        )

    async def _resolve_match(self, match_id: int) -> None:
        match = await self.bot.db.fetchone(
            "SELECT * FROM duo_matches WHERE id = ?",
            (match_id,),
        )
        if not match or match["bye"]:
            return

        boards = await self.bot.db.fetchall(
            """
            SELECT board_no, result, status
            FROM duo_boards
            WHERE match_id = ?
            ORDER BY board_no
            """,
            (match_id,),
        )
        result_by_board = {
            int(row["board_no"]): row["result"]
            if row["status"] == "complete"
            else None
            for row in boards
        }

        first = result_by_board.get(1)
        second = result_by_board.get(2)
        resolution = resolve_encounter(match["mode"], [first, second])

        if resolution.needs_tiebreak:
            await self._create_tiebreak(match_id)
            return

        # Si le board 3 existe, on refait le calcul avec son résultat.
        if any(int(row["board_no"]) == 3 for row in boards):
            resolution = resolve_encounter(
                match["mode"],
                [first, second, result_by_board.get(3)],
            )

        if resolution.needs_staff:
            await self.bot.db.execute(
                """
                UPDATE duo_matches
                SET status = 'needs_staff',
                    double_loss_count = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (resolution.double_losses, match_id),
                commit=True,
            )
            if match["mode"] == "swiss":
                await self._recompute_standings(match["tournament_id"])
            return

        if not resolution.ready:
            return

        winner_team_id = None
        if resolution.winner_side == "a":
            winner_team_id = match["team_a_id"]
        elif resolution.winner_side == "b":
            winner_team_id = match["team_b_id"]

        all_results = [
            row["result"]
            for row in await self.bot.db.fetchall(
                """
                SELECT result FROM duo_boards
                WHERE match_id = ? AND status = 'complete'
                ORDER BY board_no
                """,
                (match_id,),
            )
        ]
        dl_count = sum(1 for value in all_results if value == DOUBLE_LOSS)

        await self.bot.db.execute(
            """
            UPDATE duo_matches
            SET status = ?,
                winner_team_id = ?,
                points_a = ?,
                points_b = ?,
                double_loss_count = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                resolution.status,
                winner_team_id,
                resolution.points_a,
                resolution.points_b,
                dl_count,
                match_id,
            ),
            commit=True,
        )

        if match["mode"] == "swiss":
            await self._recompute_standings(match["tournament_id"])
        else:
            await self._maybe_advance_elimination(match["tournament_id"])

    async def _recompute_standings(self, tournament_id: int) -> None:
        teams = await self.bot.db.fetchall(
            """
            SELECT team_id
            FROM duo_tournament_entries
            WHERE tournament_id = ? AND dropped = 0
            """,
            (tournament_id,),
        )
        stats = {
            int(r["team_id"]): {
                "points": 0,
                "wins": 0,
                "losses": 0,
                "double_losses": 0,
                "byes": 0,
                "board_wins": 0,
                "board_losses": 0,
                "matches_played": 0,
            }
            for r in teams
        }

        matches = await self.bot.db.fetchall(
            """
            SELECT *
            FROM duo_matches
            WHERE tournament_id = ?
              AND status IN ('complete', 'complete_penalized', 'double_loss')
            ORDER BY round_no, match_no
            """,
            (tournament_id,),
        )
        for match in matches:
            a = int(match["team_a_id"])
            b = int(match["team_b_id"]) if match["team_b_id"] is not None else None
            if a not in stats:
                continue

            stats[a]["matches_played"] += 1
            if b is not None and b in stats:
                stats[b]["matches_played"] += 1

            if match["bye"]:
                stats[a]["points"] += int(match["points_a"])
                stats[a]["wins"] += 1
                stats[a]["byes"] += 1
                continue

            if b is None or b not in stats:
                continue

            stats[a]["points"] += int(match["points_a"])
            stats[b]["points"] += int(match["points_b"])
            dl_count = int(match["double_loss_count"] or 0)
            stats[a]["double_losses"] += dl_count
            stats[b]["double_losses"] += dl_count

            boards = await self.bot.db.fetchall(
                """
                SELECT result
                FROM duo_boards
                WHERE match_id = ? AND status = 'complete'
                """,
                (match["id"],),
            )
            for board in boards:
                if board["result"] == A_WIN:
                    stats[a]["board_wins"] += 1
                    stats[b]["board_losses"] += 1
                elif board["result"] == B_WIN:
                    stats[b]["board_wins"] += 1
                    stats[a]["board_losses"] += 1

            winner = match["winner_team_id"]
            if winner == a:
                stats[a]["wins"] += 1
                stats[b]["losses"] += 1
            elif winner == b:
                stats[b]["wins"] += 1
                stats[a]["losses"] += 1
            elif match["status"] == "double_loss":
                # Une rencontre entièrement perdue sur DL est volontairement
                # traitée comme une défaite des deux côtés.
                stats[a]["losses"] += 1
                stats[b]["losses"] += 1

        for team_id, data in stats.items():
            await self.bot.db.execute(
                """
                INSERT INTO duo_standings(
                    tournament_id, team_id, points, wins, losses,
                    double_losses, byes, board_wins, board_losses,
                    matches_played, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tournament_id, team_id) DO UPDATE SET
                    points = excluded.points,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    double_losses = excluded.double_losses,
                    byes = excluded.byes,
                    board_wins = excluded.board_wins,
                    board_losses = excluded.board_losses,
                    matches_played = excluded.matches_played,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tournament_id,
                    team_id,
                    data["points"],
                    data["wins"],
                    data["losses"],
                    data["double_losses"],
                    data["byes"],
                    data["board_wins"],
                    data["board_losses"],
                    data["matches_played"],
                ),
            )
        await self.bot.db.commit()

    async def _buchholz(self, tournament_id: int, team_id: int) -> int:
        matches = await self.bot.db.fetchall(
            """
            SELECT team_a_id, team_b_id
            FROM duo_matches
            WHERE tournament_id = ?
              AND (team_a_id = ? OR team_b_id = ?)
              AND team_b_id IS NOT NULL
              AND status IN ('complete', 'complete_penalized', 'double_loss')
            """,
            (tournament_id, team_id, team_id),
        )
        total = 0
        for match in matches:
            opponent = (
                int(match["team_b_id"])
                if int(match["team_a_id"]) == team_id
                else int(match["team_a_id"])
            )
            row = await self.bot.db.fetchone(
                """
                SELECT points FROM duo_standings
                WHERE tournament_id = ? AND team_id = ?
                """,
                (tournament_id, opponent),
            )
            if row:
                total += int(row["points"])
        return total

    async def _standings_rows(self, tournament_id: int) -> list[dict]:
        rows = await self.bot.db.fetchall(
            """
            SELECT s.*, t.name AS team_name
            FROM duo_standings s
            JOIN duo_teams t ON t.id = s.team_id
            WHERE s.tournament_id = ?
            """,
            (tournament_id,),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["buchholz"] = await self._buchholz(
                tournament_id,
                int(row["team_id"]),
            )
            result.append(item)
        result.sort(key=standing_sort_key)
        return result

    async def _already_played(
        self,
        tournament_id: int,
        team_a: int,
        team_b: int,
    ) -> bool:
        row = await self.bot.db.fetchone(
            """
            SELECT 1
            FROM duo_matches
            WHERE tournament_id = ?
              AND team_b_id IS NOT NULL
              AND (
                    (team_a_id = ? AND team_b_id = ?)
                 OR (team_a_id = ? AND team_b_id = ?)
              )
            LIMIT 1
            """,
            (tournament_id, team_a, team_b, team_b, team_a),
        )
        return row is not None

    async def _create_swiss_round(self, tournament_id: int, round_no: int) -> None:
        standings = await self._standings_rows(tournament_id)
        if not standings:
            entries = await self.bot.db.fetchall(
                """
                SELECT e.team_id, t.name AS team_name
                FROM duo_tournament_entries e
                JOIN duo_teams t ON t.id = e.team_id
                WHERE e.tournament_id = ? AND e.dropped = 0
                ORDER BY COALESCE(e.seed, 999999), e.team_id
                """,
                (tournament_id,),
            )
            standings = [
                {
                    "team_id": int(row["team_id"]),
                    "team_name": row["team_name"],
                    "points": 0,
                    "double_losses": 0,
                    "wins": 0,
                    "losses": 0,
                    "board_wins": 0,
                    "board_losses": 0,
                    "buchholz": 0,
                }
                for row in entries
            ]

        team_ids = [int(row["team_id"]) for row in standings]

        # BYE : priorité à l'équipe la moins bien classée n'ayant pas encore eu de BYE.
        bye_team = None
        if len(team_ids) % 2:
            for team_id in reversed(team_ids):
                prior = await self.bot.db.fetchone(
                    """
                    SELECT 1 FROM duo_matches
                    WHERE tournament_id = ? AND team_a_id = ? AND bye = 1
                    LIMIT 1
                    """,
                    (tournament_id, team_id),
                )
                if not prior:
                    bye_team = team_id
                    break
            if bye_team is None:
                bye_team = team_ids[-1]
            team_ids.remove(bye_team)

        pairs: list[tuple[int, int]] = []
        pool = team_ids[:]
        while pool:
            a = pool.pop(0)
            opponent_index = None
            for index, b in enumerate(pool):
                if not await self._already_played(tournament_id, a, b):
                    opponent_index = index
                    break
            if opponent_index is None:
                opponent_index = 0
            b = pool.pop(opponent_index)
            pairs.append((a, b))

        match_no = 1
        for a, b in pairs:
            await self._create_match(
                tournament_id, round_no, match_no, a, b, "swiss"
            )
            match_no += 1
        if bye_team is not None:
            await self._create_match(
                tournament_id, round_no, match_no, bye_team, None, "swiss"
            )

        await self.bot.db.execute(
            """
            UPDATE duo_tournaments
            SET current_round = ?, status = 'running'
            WHERE tournament_id = ?
            """,
            (round_no, tournament_id),
            commit=True,
        )
        await self._recompute_standings(tournament_id)

    async def _create_elimination_round(
        self,
        tournament_id: int,
        round_no: int,
        team_ids: list[int],
    ) -> None:
        match_no = 1
        pool = team_ids[:]
        while pool:
            a = pool.pop(0)
            b = pool.pop(0) if pool else None
            await self._create_match(
                tournament_id, round_no, match_no, a, b, "elimination"
            )
            match_no += 1
        await self.bot.db.execute(
            """
            UPDATE duo_tournaments
            SET current_round = ?, status = 'running'
            WHERE tournament_id = ?
            """,
            (round_no, tournament_id),
            commit=True,
        )
        await self._maybe_advance_elimination(tournament_id)

    async def _maybe_advance_elimination(self, tournament_id: int) -> None:
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (tournament_id,),
        )
        if not cfg or cfg["mode"] != "elimination" or cfg["status"] == "finished":
            return

        round_no = int(cfg["current_round"])
        matches = await self.bot.db.fetchall(
            """
            SELECT *
            FROM duo_matches
            WHERE tournament_id = ? AND round_no = ?
            ORDER BY match_no
            """,
            (tournament_id, round_no),
        )
        if not matches:
            return
        if any(row["status"] not in {"complete", "complete_penalized"} for row in matches):
            return
        if any(row["winner_team_id"] is None for row in matches):
            return

        winners = [int(row["winner_team_id"]) for row in matches]
        if len(winners) == 1:
            await self.bot.db.execute(
                """
                UPDATE duo_tournaments
                SET status = 'finished',
                    winner_team_id = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE tournament_id = ?
                """,
                (winners[0], tournament_id),
            )
            winner_name = await self._team_name(winners[0])
            await self.bot.db.execute(
                """
                UPDATE tournaments
                SET status = 'finished', winner_id = ?, winner_name = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (f"team:{winners[0]}", winner_name, tournament_id),
                commit=True,
            )
            return

        await self._create_elimination_round(
            tournament_id,
            round_no + 1,
            winners,
        )

    async def _set_board_result(
        self,
        match_id: int,
        board_no: int,
        result: str,
    ) -> None:
        await self.bot.db.execute(
            """
            UPDATE duo_boards
            SET result = ?,
                status = 'complete',
                pending_result = NULL,
                reported_by = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE match_id = ? AND board_no = ?
            """,
            (result, match_id, board_no),
            commit=True,
        )
        await self._resolve_match(match_id)

    # ------------------------------------------------------------------
    # Commandes équipe
    # ------------------------------------------------------------------
    @duo.command(name="team_create", description="Créer une équipe de 2.")
    @app_commands.describe(
        name="Nom de l'équipe",
        partner="Ton partenaire",
        deck="Ton deck / archétype",
    )
    async def team_create(
        self,
        interaction: discord.Interaction,
        name: str,
        partner: discord.Member,
        deck: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Cette commande doit être utilisée sur un serveur.",
                ephemeral=True,
            )
            return
        if partner.bot or partner.id == interaction.user.id:
            await interaction.response.send_message(
                "Choisis un autre joueur humain comme partenaire.",
                ephemeral=True,
            )
            return

        try:
            cursor = await self.bot.db.execute(
                """
                INSERT INTO duo_teams(guild_id, name, captain_id, status)
                VALUES (?, ?, ?, 'pending')
                """,
                (str(interaction.guild_id), name.strip(), str(interaction.user.id)),
            )
            team_id = int(cursor.lastrowid)
            await self.bot.db.execute(
                """
                INSERT INTO duo_team_members(
                    team_id, user_id, slot, display_name, deck
                ) VALUES (?, ?, 1, ?, ?)
                """,
                (
                    team_id,
                    str(interaction.user.id),
                    interaction.user.display_name,
                    deck.strip(),
                ),
            )
            await self.bot.db.execute(
                """
                INSERT INTO duo_team_invites(team_id, invited_user_id, status)
                VALUES (?, ?, 'pending')
                """,
                (team_id, str(partner.id)),
            )
            await self.bot.db.commit()
        except Exception as error:
            await self.bot.db.rollback()
            await interaction.response.send_message(
                f"❌ Impossible de créer l'équipe : {error}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"🤝 **{name.strip()}** créée.\n"
            f"{partner.mention}, accepte avec `/duo team_accept team_id:{team_id}`.\n"
            f"ID équipe : **{team_id}**"
        )

    @duo.command(name="team_accept", description="Accepter une invitation 2v2.")
    @app_commands.describe(team_id="ID de l'équipe", deck="Ton deck / archétype")
    async def team_accept(
        self,
        interaction: discord.Interaction,
        team_id: int,
        deck: str,
    ) -> None:
        invite = await self.bot.db.fetchone(
            """
            SELECT i.*, t.name
            FROM duo_team_invites i
            JOIN duo_teams t ON t.id = i.team_id
            WHERE i.team_id = ?
              AND i.invited_user_id = ?
              AND i.status = 'pending'
            """,
            (team_id, str(interaction.user.id)),
        )
        if not invite:
            await interaction.response.send_message(
                "❌ Invitation introuvable ou déjà utilisée.",
                ephemeral=True,
            )
            return

        await self.bot.db.execute(
            """
            INSERT INTO duo_team_members(
                team_id, user_id, slot, display_name, deck
            ) VALUES (?, ?, 2, ?, ?)
            """,
            (
                team_id,
                str(interaction.user.id),
                interaction.user.display_name,
                deck.strip(),
            ),
        )
        await self.bot.db.execute(
            "UPDATE duo_team_invites SET status = 'accepted' WHERE team_id = ?",
            (team_id,),
        )
        await self.bot.db.execute(
            "UPDATE duo_teams SET status = 'active' WHERE id = ?",
            (team_id,),
            commit=True,
        )
        await interaction.response.send_message(
            f"✅ Tu as rejoint **{invite['name']}**. L'équipe est prête."
        )

    @duo.command(name="team_info", description="Afficher une équipe 2v2.")
    async def team_info(
        self,
        interaction: discord.Interaction,
        team_id: int,
    ) -> None:
        team = await self._team(team_id)
        if not team:
            await interaction.response.send_message(
                "Equipe introuvable.", ephemeral=True
            )
            return
        members = await self._members(team_id)
        lines = [
            f"👥 **{team['name']}** — `{team['status']}`",
            f"ID : **{team_id}**",
        ]
        for member in members:
            lines.append(
                f"**Slot {member['slot']}** · <@{member['user_id']}>"
                f" — {member['deck'] or 'Deck non renseigné'}"
            )
        await interaction.response.send_message("\n".join(lines))

    # ------------------------------------------------------------------
    # Inscription / lancement
    # ------------------------------------------------------------------
    @duo.command(name="register", description="Inscrire une équipe à un tournoi.")
    async def register(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
        team_id: int,
    ) -> None:
        team = await self._team(team_id)
        if not team or team["status"] != "active":
            await interaction.response.send_message(
                "❌ L'équipe doit exister et être complète.",
                ephemeral=True,
            )
            return
        member_ids = {str(m["user_id"]) for m in await self._members(team_id)}
        if str(interaction.user.id) not in member_ids and not _is_staff(interaction):
            await interaction.response.send_message(
                "❌ Tu ne fais pas partie de cette équipe.",
                ephemeral=True,
            )
            return

        conflict = await self._registered_elsewhere(tournament_id, team_id)
        if conflict:
            await interaction.response.send_message(
                f"❌ Un membre est déjà inscrit avec **{conflict}**.",
                ephemeral=True,
            )
            return

        count = await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM duo_tournament_entries WHERE tournament_id = ?",
            (tournament_id,),
        )
        seed = int(count or 0) + 1
        try:
            await self.bot.db.execute(
                """
                INSERT INTO duo_tournament_entries(
                    tournament_id, team_id, seed
                ) VALUES (?, ?, ?)
                """,
                (tournament_id, team_id, seed),
            )
            for member in await self._members(team_id):
                await self.bot.db.execute(
                    """
                    INSERT INTO duo_entry_members(
                        tournament_id, team_id, user_id,
                        slot, display_name, deck
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tournament_id,
                        team_id,
                        member["user_id"],
                        member["slot"],
                        member["display_name"],
                        member["deck"],
                    ),
                )
            await self.bot.db.commit()
        except Exception as error:
            await self.bot.db.rollback()
            await interaction.response.send_message(
                f"❌ Inscription impossible : {error}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ **{team['name']}** inscrite au tournoi **#{tournament_id}**."
        )

    @duo.command(name="start", description="Lancer le tournoi 2v2.")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Elimination directe", value="elimination"),
            app_commands.Choice(name="Ronde suisse", value="swiss"),
        ]
    )
    async def start(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
        mode: app_commands.Choice[str],
        rounds: int = 0,
    ) -> None:
        if not await _require_staff(interaction):
            return

        existing = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (tournament_id,),
        )
        if existing and existing["status"] in {"running", "finished"}:
            await interaction.response.send_message(
                "❌ Ce tournoi 2v2 est déjà lancé ou terminé.",
                ephemeral=True,
            )
            return

        entries = await self.bot.db.fetchall(
            """
            SELECT team_id
            FROM duo_tournament_entries
            WHERE tournament_id = ? AND dropped = 0
            ORDER BY COALESCE(seed, 999999), team_id
            """,
            (tournament_id,),
        )
        team_ids = [int(r["team_id"]) for r in entries]
        if len(team_ids) < 2:
            await interaction.response.send_message(
                "❌ Il faut au moins 2 équipes.",
                ephemeral=True,
            )
            return

        mode_value = mode.value
        if mode_value == "swiss":
            total_rounds = rounds if rounds > 0 else max(1, math.ceil(math.log2(len(team_ids))))
        else:
            total_rounds = max(1, math.ceil(math.log2(len(team_ids))))

        await self.bot.db.execute(
            """
            INSERT INTO duo_tournaments(
                tournament_id, mode, status, current_round, total_rounds
            ) VALUES (?, ?, 'running', 0, ?)
            ON CONFLICT(tournament_id) DO UPDATE SET
                mode = excluded.mode,
                status = 'running',
                current_round = 0,
                total_rounds = excluded.total_rounds,
                winner_team_id = NULL,
                finished_at = NULL
            """,
            (tournament_id, mode_value, total_rounds),
        )
        for team_id in team_ids:
            await self.bot.db.execute(
                """
                INSERT INTO duo_standings(tournament_id, team_id)
                VALUES (?, ?)
                ON CONFLICT(tournament_id, team_id) DO NOTHING
                """,
                (tournament_id, team_id),
            )
        await self.bot.db.commit()

        if mode_value == "swiss":
            await self._create_swiss_round(tournament_id, 1)
        else:
            await self._create_elimination_round(tournament_id, 1, team_ids)

        await interaction.response.send_message(
            f"🚀 Tournoi **#{tournament_id}** lancé en **{mode.name}**.\n"
            f"Equipes : **{len(team_ids)}** · Rounds prévus : **{total_rounds}**."
        )

    @duo.command(name="pair", description="Créer la prochaine ronde suisse.")
    async def pair(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
    ) -> None:
        if not await _require_staff(interaction):
            return
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (tournament_id,),
        )
        if not cfg or cfg["mode"] != "swiss" or cfg["status"] != "running":
            await interaction.response.send_message(
                "❌ Aucun tournoi suisse 2v2 actif avec cet ID.",
                ephemeral=True,
            )
            return

        current = int(cfg["current_round"])
        pending = await self.bot.db.fetchval(
            """
            SELECT COUNT(*)
            FROM duo_matches
            WHERE tournament_id = ? AND round_no = ?
              AND status NOT IN ('complete', 'complete_penalized', 'double_loss')
            """,
            (tournament_id, current),
        )
        if int(pending or 0) > 0:
            await interaction.response.send_message(
                "⏳ La ronde actuelle n'est pas terminée.",
                ephemeral=True,
            )
            return

        if current >= int(cfg["total_rounds"]):
            await self.bot.db.execute(
                """
                UPDATE duo_tournaments
                SET status = 'finished', finished_at = CURRENT_TIMESTAMP
                WHERE tournament_id = ?
                """,
                (tournament_id,),
                commit=True,
            )
            await interaction.response.send_message(
                "🏁 Toutes les rondes suisses sont terminées."
            )
            return

        await self._create_swiss_round(tournament_id, current + 1)
        await interaction.response.send_message(
            f"🔄 Ronde suisse **{current + 1}** créée."
        )

    # ------------------------------------------------------------------
    # Résultats
    # ------------------------------------------------------------------
    @duo.command(name="report", description="Signaler ton résultat sur un board.")
    @app_commands.choices(
        outcome=[
            app_commands.Choice(name="J'ai gagné", value="win"),
            app_commands.Choice(name="J'ai perdu", value="loss"),
            app_commands.Choice(name="Double loss", value="double_loss"),
        ]
    )
    async def report(
        self,
        interaction: discord.Interaction,
        match_id: int,
        board: int,
        outcome: app_commands.Choice[str],
    ) -> None:
        board_row = await self.bot.db.fetchone(
            """
            SELECT b.*, m.status AS match_status
            FROM duo_boards b
            JOIN duo_matches m ON m.id = b.match_id
            WHERE b.match_id = ? AND b.board_no = ?
            """,
            (match_id, board),
        )
        if not board_row:
            await interaction.response.send_message(
                "Board introuvable.", ephemeral=True
            )
            return
        if board_row["status"] == "complete":
            await interaction.response.send_message(
                "Ce board est déjà validé.", ephemeral=True
            )
            return

        uid = str(interaction.user.id)
        if uid == str(board_row["player_a_id"]):
            side = "a"
        elif uid == str(board_row["player_b_id"]):
            side = "b"
        else:
            await interaction.response.send_message(
                "❌ Tu ne joues pas ce board.",
                ephemeral=True,
            )
            return

        if outcome.value == "double_loss":
            result = DOUBLE_LOSS
        elif outcome.value == "win":
            result = A_WIN if side == "a" else B_WIN
        else:
            result = B_WIN if side == "a" else A_WIN

        await self.bot.db.execute(
            """
            UPDATE duo_boards
            SET status = 'pending_confirmation',
                pending_result = ?,
                reported_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE match_id = ? AND board_no = ?
            """,
            (result, uid, match_id, board),
            commit=True,
        )

        opponent = (
            board_row["player_b_id"]
            if side == "a"
            else board_row["player_a_id"]
        )
        await interaction.response.send_message(
            f"📨 Résultat envoyé. <@{opponent}> doit utiliser "
            f"`/duo confirm match_id:{match_id} board:{board}` "
            f"ou `/duo reject ...`."
        )

    @duo.command(name="confirm", description="Confirmer un résultat 2v2.")
    async def confirm(
        self,
        interaction: discord.Interaction,
        match_id: int,
        board: int,
    ) -> None:
        row = await self.bot.db.fetchone(
            """
            SELECT * FROM duo_boards
            WHERE match_id = ? AND board_no = ?
            """,
            (match_id, board),
        )
        if not row or row["status"] != "pending_confirmation":
            await interaction.response.send_message(
                "Aucun résultat en attente pour ce board.",
                ephemeral=True,
            )
            return

        uid = str(interaction.user.id)
        allowed = uid in {str(row["player_a_id"]), str(row["player_b_id"])}
        if not allowed and not _is_staff(interaction):
            await interaction.response.send_message(
                "❌ Tu ne peux pas confirmer ce résultat.",
                ephemeral=True,
            )
            return
        if uid == str(row["reported_by"]) and not _is_staff(interaction):
            await interaction.response.send_message(
                "❌ Le joueur qui signale ne peut pas s'auto-confirmer.",
                ephemeral=True,
            )
            return

        result = row["pending_result"]
        await self._set_board_result(match_id, board, result)
        await interaction.response.send_message(
            f"✅ Board **{board}** confirmé."
        )

    @duo.command(name="reject", description="Refuser un résultat signalé.")
    async def reject(
        self,
        interaction: discord.Interaction,
        match_id: int,
        board: int,
    ) -> None:
        row = await self.bot.db.fetchone(
            """
            SELECT * FROM duo_boards
            WHERE match_id = ? AND board_no = ?
            """,
            (match_id, board),
        )
        if not row or row["status"] != "pending_confirmation":
            await interaction.response.send_message(
                "Aucun résultat en attente.",
                ephemeral=True,
            )
            return
        uid = str(interaction.user.id)
        allowed = uid in {str(row["player_a_id"]), str(row["player_b_id"])}
        if not allowed and not _is_staff(interaction):
            await interaction.response.send_message(
                "❌ Tu ne peux pas refuser ce résultat.",
                ephemeral=True,
            )
            return
        if uid == str(row["reported_by"]) and not _is_staff(interaction):
            await interaction.response.send_message(
                "❌ Seul l'adversaire ou le staff peut le refuser.",
                ephemeral=True,
            )
            return

        await self.bot.db.execute(
            """
            UPDATE duo_boards
            SET status = 'open',
                pending_result = NULL,
                reported_by = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE match_id = ? AND board_no = ?
            """,
            (match_id, board),
            commit=True,
        )
        await interaction.response.send_message(
            "↩️ Résultat refusé. Le board est rouvert."
        )

    @duo.command(name="admin_result", description="Staff : fixer un résultat de board.")
    @app_commands.choices(
        result=[
            app_commands.Choice(name="Equipe A gagne", value=A_WIN),
            app_commands.Choice(name="Equipe B gagne", value=B_WIN),
            app_commands.Choice(name="Double loss", value=DOUBLE_LOSS),
        ]
    )
    async def admin_result(
        self,
        interaction: discord.Interaction,
        match_id: int,
        board: int,
        result: app_commands.Choice[str],
    ) -> None:
        if not await _require_staff(interaction):
            return
        exists = await self.bot.db.fetchone(
            "SELECT 1 FROM duo_boards WHERE match_id = ? AND board_no = ?",
            (match_id, board),
        )
        if not exists:
            await interaction.response.send_message(
                "Board introuvable.", ephemeral=True
            )
            return
        await self._set_board_result(match_id, board, result.value)
        await interaction.response.send_message(
            f"🛠️ Board {board} fixé sur `{result.value}`."
        )

    @duo.command(
        name="force_winner",
        description="Staff : choisir le vainqueur après une DL bloquante en élimination.",
    )
    async def force_winner(
        self,
        interaction: discord.Interaction,
        match_id: int,
        team_id: int,
    ) -> None:
        if not await _require_staff(interaction):
            return
        match = await self.bot.db.fetchone(
            "SELECT * FROM duo_matches WHERE id = ?",
            (match_id,),
        )
        if not match or match["mode"] != "elimination":
            await interaction.response.send_message(
                "Match d'élimination introuvable.",
                ephemeral=True,
            )
            return
        if team_id not in {
            int(match["team_a_id"]),
            int(match["team_b_id"]) if match["team_b_id"] is not None else -1,
        }:
            await interaction.response.send_message(
                "Cette équipe ne joue pas ce match.",
                ephemeral=True,
            )
            return

        await self.bot.db.execute(
            """
            UPDATE duo_matches
            SET status = 'complete',
                winner_team_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (team_id, match_id),
            commit=True,
        )
        await self._maybe_advance_elimination(match["tournament_id"])
        await interaction.response.send_message(
            f"⚖️ Vainqueur forcé : **{await self._team_name(team_id)}**."
        )

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------
    @duo.command(name="match", description="Afficher une rencontre 2v2.")
    async def match_status(
        self,
        interaction: discord.Interaction,
        match_id: int,
    ) -> None:
        match = await self.bot.db.fetchone(
            "SELECT * FROM duo_matches WHERE id = ?",
            (match_id,),
        )
        if not match:
            await interaction.response.send_message(
                "Match introuvable.", ephemeral=True
            )
            return

        name_a = await self._team_name(match["team_a_id"])
        name_b = await self._team_name(match["team_b_id"])
        lines = [
            f"⚔️ **Match 2v2 #{match_id}** · ronde {match['round_no']}",
            f"**{name_a}** 🆚 **{name_b}**",
            f"Statut : `{match['status']}`",
        ]
        if match["bye"]:
            lines.append(f"🎫 BYE : **{name_a}**")
        else:
            boards = await self.bot.db.fetchall(
                """
                SELECT * FROM duo_boards
                WHERE match_id = ?
                ORDER BY board_no
                """,
                (match_id,),
            )
            for board in boards:
                icon = {
                    "open": "⏳",
                    "pending_confirmation": "📨",
                    "complete": "✅",
                }.get(board["status"], "•")
                label = "Duel décisif" if board["board_no"] == 3 else f"Duel {board['board_no']}"
                lines.append(
                    f"{icon} **{label}** · <@{board['player_a_id']}> "
                    f"vs <@{board['player_b_id']}> · "
                    f"`{board['result'] or board['pending_result'] or 'à jouer'}`"
                )
        if match["double_loss_count"]:
            lines.append(
                "🚨 **Double loss détectée : aucun point suisse ne peut être attribué au vainqueur.**"
            )
        await interaction.response.send_message("\n".join(lines))

    @duo.command(name="standings", description="Classement suisse 2v2.")
    async def standings(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
    ) -> None:
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (tournament_id,),
        )
        if not cfg:
            await interaction.response.send_message(
                "Tournoi 2v2 introuvable.", ephemeral=True
            )
            return
        await self._recompute_standings(tournament_id)
        rows = await self._standings_rows(tournament_id)
        if not rows:
            await interaction.response.send_message(
                "Classement vide.", ephemeral=True
            )
            return

        lines = [
            f"🏆 **Classement 2v2 — tournoi #{tournament_id}**",
            "DL = double loss. A points égaux, toute équipe sans DL passe devant.",
            "",
        ]
        for rank, row in enumerate(rows, 1):
            lines.append(
                f"**{rank}. {row['team_name']}** — "
                f"**{row['points']} pts** · "
                f"{row['wins']}V/{row['losses']}D · "
                f"DL {row['double_losses']} · "
                f"Buchholz {row['buchholz']} · "
                f"Boards {row['board_wins']}-{row['board_losses']}"
            )
        await interaction.response.send_message("\n".join(lines)[:1900])

    @duo.command(name="tournament", description="Etat d'un tournoi 2v2.")
    async def tournament_status(
        self,
        interaction: discord.Interaction,
        tournament_id: int,
    ) -> None:
        cfg = await self.bot.db.fetchone(
            "SELECT * FROM duo_tournaments WHERE tournament_id = ?",
            (tournament_id,),
        )
        if not cfg:
            await interaction.response.send_message(
                "Tournoi 2v2 introuvable.", ephemeral=True
            )
            return
        winner = await self._team_name(cfg["winner_team_id"])
        await interaction.response.send_message(
            f"👥 **Tournoi 2v2 #{tournament_id}**\n"
            f"Mode : **{cfg['mode']}**\n"
            f"Statut : **{cfg['status']}**\n"
            f"Ronde : **{cfg['current_round']}/{cfg['total_rounds']}**\n"
            f"Vainqueur : **{winner if cfg['winner_team_id'] else '—'}**"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Team2v2Cog(bot))
