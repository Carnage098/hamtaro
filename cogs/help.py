from __future__ import annotations

import discord

from discord.ext import commands
from discord import app_commands


class HelpCog(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot

    # ==========================================================
    # OUTILS DE DÉTECTION
    # ==========================================================

    def _has_role_name(
        self,
        member: discord.Member,
        role_names: list[str],
    ) -> bool:

        member_roles = [
            role.name.lower()
            for role in member.roles
        ]

        wanted_roles = [
            role_name.lower()
            for role_name in role_names
        ]

        return any(
            role_name in member_roles
            for role_name in wanted_roles
        )

    def _is_admin(
        self,
        member: discord.Member,
    ) -> bool:

        return bool(
            member.guild_permissions.administrator
            or self._has_role_name(
                member,
                [
                    "admin",
                    "administrateur",
                    "administrator",
                    "owner",
                    "propriétaire",
                    "fondateur",
                ],
            )
        )

    def _is_staff(
        self,
        member: discord.Member,
    ) -> bool:

        if self._is_admin(member):
            return True

        return bool(
            member.guild_permissions.manage_guild
            or member.guild_permissions.manage_messages
            or member.guild_permissions.manage_roles
            or self._has_role_name(
                member,
                [
                    "staff",
                    "modo",
                    "modérateur",
                    "moderateur",
                    "arbitre",
                    "judge",
                    "orga",
                    "organisateur",
                    "tournoi staff",
                ],
            )
        )

    def _detect_profile(
        self,
        member: discord.Member,
    ) -> str:

        if self._is_admin(member):
            return "admin"

        if self._is_staff(member):
            return "staff"

        return "joueur"

    # ==========================================================
    # EMBEDS
    # ==========================================================

    def _base_embed(
        self,
        title: str,
        description: str,
    ) -> discord.Embed:

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.orange(),
        )

        embed.set_footer(
            text="Hamtaro — Bot de tournois Yu-Gi-Oh!"
        )

        return embed

    def _player_help_embed(
        self,
    ) -> discord.Embed:

        embed = self._base_embed(
            title="🐹 Aide Hamtaro — Joueur",
            description=(
                "Voici les commandes utiles pour participer à un tournoi."
            ),
        )

        embed.add_field(
            name="🎮 Participer à un tournoi",
            value=(
                "`/register` — S'inscrire au tournoi actif.\n"
                "`/profile` — Voir son profil joueur.\n"
                "`/match_history` — Voir son historique de matchs, si disponible."
            ),
            inline=False,
        )

        embed.add_field(
            name="🏆 Voir le tournoi",
            value=(
                "`/bracket` — Voir l'arbre du tournoi à élimination directe.\n"
                "`/swiss_pairings` — Voir les pairings des rondes suisses.\n"
                "`/swiss_standings` — Voir le classement suisse.\n"
                "`/swiss_status` — Voir l'état actuel des rondes suisses."
            ),
            inline=False,
        )

        embed.add_field(
            name="📌 Règles importantes",
            value=(
                "• Si tu t'inscris, tu es considéré comme disponible.\n"
                "• Le check-in n'est plus obligatoire.\n"
                "• En tournoi à élimination directe, il faut forcément un gagnant, ça ne fonctionne pas comme les rondes suisses.\n"
                "• En rondes suisses, un **double loss** peut être donné si le match n'est pas terminé dans le temps prévu (50 minutes, règles officielles de Konami)."
            ),
            inline=False,
        )

        embed.add_field(
            name="⏱️ Double loss",
            value=(
                "Le double loss est réservé aux **rondes suisses**.\n"
                "Il donne **0 point aux deux joueurs** et compte comme une pénalité plus importante qu'une simple défaite dans le classement."
            ),
            inline=False,
        )

        return embed

    def _staff_help_embed(
        self,
    ) -> discord.Embed:

        embed = self._base_embed(
            title="🐹 Aide Hamtaro — Staff",
            description=(
                "Voici les commandes utiles pour gérer les matchs et aider au bon déroulement du tournoi."
            ),
        )

        embed.add_field(
            name="🎯 Gestion des résultats",
            value=(
                "`/result` — Enregistrer ou signaler un résultat de match.\n"
                "`/swiss_result` — Valider le résultat d'une table suisse.\n"
                "`/swiss_result table:1 resultat:Double loss` — Mettre une double loss en ronde suisse.\n"
                "`/repair_tournament` — Réparer un tournoi bloqué."
            ),
            inline=False,
        )

        embed.add_field(
            name="🏆 Rondes suisses",
            value=(
                "`/swiss_pairings` — Afficher les pairings.\n"
                "`/swiss_standings` — Afficher le classement.\n"
                "`/swiss_status` — Voir l'état des rondes suisses.\n"
                "`/swiss_next` — Générer la ronde suisse suivante."
            ),
            inline=False,
        )

        embed.add_field(
            name="👥 Gestion des joueurs",
            value=(
                "`/add_admin_player` — Ajouter un joueur manuellement.\n"
                "`/remove_player` — Retirer un joueur du tournoi.\n"
                "`/profile` — Consulter le profil d'un joueur.\n"
                "`/match_history` — Vérifier l'historique d'un joueur, si disponible."
            ),
            inline=False,
        )

        embed.add_field(
            name="⚠️ Rappel staff",
            value=(
                "• Ne génère pas la ronde suivante si tous les résultats ne sont pas validés.\n"
                "• Le double loss existe uniquement en rondes suisses.\n"
                "• En cas de bug, note la commande utilisée, la table, la ronde et fais une capture pour l'envoyer au développeur."
            ),
            inline=False,
        )

        return embed

    def _admin_help_embed(
        self,
    ) -> discord.Embed:

        embed = self._base_embed(
            title="🐹 Aide Hamtaro — Admin",
            description=(
                "Voici les commandes importantes pour configurer, lancer et administrer les tournois."
            ),
        )

        embed.add_field(
            name="🛠️ Création et gestion du tournoi",
            value=(
                "`/create_tournament` — Créer un nouveau tournoi.\n"
                "`/start_tournament` — Lancer un tournoi à élimination directe.\n"
                "`/end_tournament` — Terminer le tournoi actif, une fois avoir trouvé le grand vainqueur.\n"
                "`/tournament_status` — Voir le statut du tournoi actif."
            ),
            inline=False,
        )

        embed.add_field(
            name="🏆 Rondes suisses",
            value=(
                "`/swiss_start` — Lancer les rondes suisses.\n"
                "`/swiss_result` — Valider un résultat suisse.\n"
                "`/swiss_next` — Générer la ronde suivante.\n"
                "`/swiss_reset` — Réinitialiser les rondes suisses du tournoi actif.\n"
                "`/swiss_standings` — Afficher le classement suisse."
            ),
            inline=False,
        )

        embed.add_field(
            name="👥 Administration des joueurs",
            value=(
                "`/add_admin_player` — Ajouter un joueur au tournoi.\n"
                "`/remove_player` — Retirer un joueur du tournoi.\n"
                "`/profile` — Voir le profil d'un joueur.\n"
                "`/match_history` — Voir l'historique d'un joueur."
            ),
            inline=False,
        )


        return embed

    def _general_help_embed(
        self,
    ) -> discord.Embed:

        embed = self._base_embed(
            title="🐹 Aide Hamtaro — Général",
            description=(
                "Choisis une catégorie pour afficher l'aide adaptée à toi si t'es un joueur, un membre du staff ou un admin."
            ),
        )

        embed.add_field(
            name="👤 Joueur",
            value=(
                "`/help categorie:Joueur`\n"
                "Pour voir les commandes utiles aux participants."
            ),
            inline=False,
        )

        embed.add_field(
            name="🛡️ Staff",
            value=(
                "`/help categorie:Staff`\n"
                "Pour voir les commandes de gestion des matchs et des résultats."
            ),
            inline=False,
        )

        embed.add_field(
            name="👑 Admin",
            value=(
                "`/help categorie:Admin`\n"
                "Pour voir les commandes de création, lancement et administration."
            ),
            inline=False,
        )

        return embed

    # ==========================================================
    # COMMANDE HELP
    # ==========================================================

    @app_commands.command(
        name="help",
        description="Afficher l'aide de Hamtaro selon ton rôle"
    )
    @app_commands.describe(
        categorie="Catégorie d'aide à afficher",
        visible="Afficher le message publiquement"
    )
    @app_commands.choices(
        categorie=[
            app_commands.Choice(
                name="Automatique",
                value="auto",
            ),
            app_commands.Choice(
                name="Joueur",
                value="joueur",
            ),
            app_commands.Choice(
                name="Staff",
                value="staff",
            ),
            app_commands.Choice(
                name="Admin",
                value="admin",
            ),
            app_commands.Choice(
                name="Général",
                value="general",
            ),
        ]
    )
    async def help(
        self,
        interaction: discord.Interaction,
        categorie: app_commands.Choice[str] | None = None,
        visible: bool = False,
    ):

        if interaction.guild is None or not isinstance(
            interaction.user,
            discord.Member,
        ):

            await interaction.response.send_message(
                "❌ Cette commande doit être utilisée dans un serveur Discord.",
                ephemeral=True,
            )

            return

        selected_category = "auto"

        if categorie is not None:
            selected_category = categorie.value

        if selected_category == "auto":
            selected_category = self._detect_profile(
                interaction.user
            )

        if selected_category == "admin":
            embed = self._admin_help_embed()

        elif selected_category == "staff":
            embed = self._staff_help_embed()

        elif selected_category == "joueur":
            embed = self._player_help_embed()

        elif selected_category == "general":
            embed = self._general_help_embed()

        else:
            embed = self._player_help_embed()

        await interaction.response.send_message(
            embed=embed,
            ephemeral=not visible,
        )


async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        HelpCog(bot)
    )
