from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.community_service import CommunityService
from services.expansion_database import init_expansion_schema
from utils.expansion_permissions import staff_only


class PollView(discord.ui.View):
    def __init__(self, cog: "CommunityToolsCog", poll_id: int, options: list[str]) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.poll_id = poll_id
        for index, option in enumerate(options):
            button = discord.ui.Button(
                label=option[:80],
                style=discord.ButtonStyle.primary if index == 0 else discord.ButtonStyle.secondary,
                custom_id=f"hamtaro:poll:{poll_id}:{index}",
                row=index // 3,
            )
            button.callback = self._callback(index)
            self.add_item(button)

    def _callback(self, index: int):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                result = await self.cog.service.vote(
                    self.poll_id, str(interaction.user.id), index
                )
            except ValueError as error:
                await interaction.response.send_message(f"❌ {error}", ephemeral=True)
                return
            verb = "ajouté" if result["selected"] else "retiré"
            await interaction.response.send_message(
                f"✅ Vote {verb} pour **{result['option']}**.", ephemeral=True
            )
        return callback


class CommunityToolsCog(commands.Cog):
    poll_group = app_commands.Group(
        name="community_poll",
        description="Sondages communautaires Hamtaro",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = CommunityService()

    async def cog_load(self) -> None:
        await init_expansion_schema()
        for poll in await self.service.open_polls():
            self.bot.add_view(PollView(self, int(poll["id"]), list(poll["options"])))

    @poll_group.command(name="create", description="Créer un sondage avec des boutons")
    @staff_only()
    async def create(
        self,
        interaction: discord.Interaction,
        question: str,
        choix: str,
        choix_multiples: bool = False,
        fermeture_iso: str | None = None,
    ) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        options = [part.strip() for part in choix.split("|")]
        try:
            poll_id = await self.service.create_poll(
                guild_id=str(interaction.guild.id),
                channel_id=str(interaction.channel.id),
                question=question,
                options=options,
                multiple_choice=choix_multiples,
                closes_at=fermeture_iso,
                created_by=str(interaction.user.id),
            )
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        poll = await self.service.poll(poll_id)
        assert poll is not None
        embed = self.build_embed(poll, None)
        view = PollView(self, poll_id, poll["options"])
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()
        await self.service.attach_message(poll_id, str(message.id))
        self.bot.add_view(view)

    @poll_group.command(name="results", description="Afficher les résultats d'un sondage")
    async def results(
        self,
        interaction: discord.Interaction,
        sondage_id: int,
        visible: bool = False,
    ) -> None:
        try:
            poll = await self.service.results(sondage_id)
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=self.build_embed(poll, poll["counts"]), ephemeral=not visible
        )

    @poll_group.command(name="close", description="Fermer un sondage")
    @staff_only()
    async def close(self, interaction: discord.Interaction, sondage_id: int) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Commande réservée aux serveurs.", ephemeral=True)
            return
        try:
            poll = await self.service.close_poll(sondage_id, str(interaction.guild.id))
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=self.build_embed(poll, poll["counts"]), ephemeral=True
        )

    @staticmethod
    def build_embed(poll: dict, counts: list[int] | None) -> discord.Embed:
        embed = discord.Embed(
            title=f"📊 {poll['question']}",
            color=discord.Color.blurple(),
        )
        if counts is None:
            embed.description = "Clique sur un bouton pour voter."
        else:
            total = sum(counts)
            lines = []
            for option, count in zip(poll["options"], counts):
                percent = count / total * 100 if total else 0.0
                blocks = "█" * round(percent / 10)
                lines.append(f"**{option}** — {count} vote(s) ({percent:.1f} %) `{blocks}`")
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"{poll.get('voters', 0)} votant(s) distinct(s) • Statut : {poll['status']}")
        if poll.get("closes_at"):
            embed.add_field(name="Fermeture prévue", value=str(poll["closes_at"]), inline=False)
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommunityToolsCog(bot))
