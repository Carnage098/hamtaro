from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.halloween_format_service import HALLOWEEN_CANDIES, HALLOWEEN_SPELLS
from utils.tournament_resolver import active_tournament_code_autocomplete, resolve_tournament


def _is_halloween(tournament) -> bool:
    return str(getattr(tournament, "format", "")).strip().casefold() == "halloween"


class HalloweenOfferView(discord.ui.View):
    def __init__(self, *, chooser_id:int, requester_name:str, candy:str, spell:str, tournament_code:str) -> None:
        super().__init__(timeout=900)
        self.chooser_id=chooser_id; self.requester_name=requester_name; self.candy=candy; self.spell=spell; self.tournament_code=tournament_code; self.resolved=False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.chooser_id:
            await interaction.response.send_message("❌ Seul l'adversaire désigné peut choisir.", ephemeral=True); return False
        return True

    async def _resolve(self, interaction: discord.Interaction, kind:str) -> None:
        if self.resolved:
            await interaction.response.send_message("Cette offre est déjà résolue.",ephemeral=True); return
        self.resolved=True
        card=self.candy if kind=="candy" else self.spell; label="BONBON" if kind=="candy" else "SORT"; emoji="🍬" if kind=="candy" else "🪄"
        for item in self.children: item.disabled=True
        embed=discord.Embed(title=f"🎃 Halloween Slot — {label}",description=f"{interaction.user.mention} a choisi **{label}** pour **{self.requester_name}**.\n\n{emoji} Carte révélée : **{card}**\n\nElle devient la **15e carte de Side Deck** de ce joueur pour ce BO3. Elle se side seulement entre les games et doit respecter la banlist Halloween.",color=discord.Color.orange())
        embed.set_footer(text=f"Tournoi {self.tournament_code} · valable pour ce BO3")
        await interaction.response.edit_message(embed=embed,view=self); self.stop()

    @discord.ui.button(label="Bonbon",emoji="🍬",style=discord.ButtonStyle.success)
    async def candy_button(self,interaction:discord.Interaction,button:discord.ui.Button)->None: await self._resolve(interaction,"candy")
    @discord.ui.button(label="Sort",emoji="🪄",style=discord.ButtonStyle.danger)
    async def spell_button(self,interaction:discord.Interaction,button:discord.ui.Button)->None: await self._resolve(interaction,"spell")


class HalloweenTournamentCog(commands.Cog):
    halloween=app_commands.Group(name="halloween",description="Système Bonbon / Sort du Format Halloween")
    def __init__(self,bot:commands.Bot)->None: self.bot=bot; self.db=bot.db

    async def _resolve(self,interaction:discord.Interaction,code:str|None):
        tournament=await resolve_tournament(interaction,self.db,code=code,require_active=True)
        if tournament is None: raise ValueError("Aucun tournoi actif trouvé.")
        if not _is_halloween(tournament): raise ValueError(f"Le tournoi `{tournament.code}` n'utilise pas Halloween.")
        return tournament

    async def _choice_row(self,tournament_id:int,discord_id:str):
        return await self.db.fetchone("SELECT halloween_candy, halloween_spell, username FROM halloween_choices WHERE tournament_id = ? AND discord_id = ?",(tournament_id,discord_id))

    async def _save(self,tournament_id:int,user:discord.abc.User,candy:str,spell:str)->None:
        await self.db.update("""INSERT INTO halloween_choices (tournament_id,discord_id,username,halloween_candy,halloween_spell,updated_at) VALUES (?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(tournament_id,discord_id) DO UPDATE SET username=excluded.username,halloween_candy=excluded.halloween_candy,halloween_spell=excluded.halloween_spell,updated_at=CURRENT_TIMESTAMP""",(tournament_id,str(user.id),getattr(user,"display_name",user.name),candy,spell))

    @halloween.command(name="rules",description="Comprendre Bonbon / Sort")
    async def rules(self,interaction:discord.Interaction)->None:
        embed=discord.Embed(title="🎃 Bonbon ou Sort — règle simple",description="**1.** Déclare 1 Bonbon + 1 Sort.\n**2.** Side Deck normal : maximum 14 cartes.\n**3.** Avant chaque BO3, chacun fait `/halloween offer`.\n**4.** L'adversaire choisit Bonbon ou Sort sans voir la carte.\n**5.** La carte révélée devient ta 15e carte de Side pour ce BO3.\n**6.** Elle se side entre G1→G2 et G2→G3.\n\nLa banlist Halloween reste obligatoire.",color=discord.Color.orange())
        await interaction.response.send_message(embed=embed,ephemeral=True)

    @halloween.command(name="choices",description="Voir tes choix")
    @app_commands.describe(code="Code facultatif du tournoi")
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    async def choices(self,interaction:discord.Interaction,code:str|None=None)->None:
        await interaction.response.defer(ephemeral=True)
        try: tournament=await self._resolve(interaction,code); row=await self._choice_row(int(tournament.id),str(interaction.user.id))
        except ValueError as e: await interaction.followup.send(f"❌ {e}",ephemeral=True); return
        if row is None: await interaction.followup.send("❌ Aucun choix enregistré. Utilise `/halloween set_choices`.",ephemeral=True); return
        await interaction.followup.send(f"🍬 **{row['halloween_candy']}**\n🪄 **{row['halloween_spell']}**",ephemeral=True)

    @halloween.command(name="set_choices",description="Définir ou modifier ton Bonbon et ton Sort")
    @app_commands.describe(bonbon="Bonbon déclaré",sortilege="Sort déclaré",code="Code facultatif")
    @app_commands.choices(bonbon=[
            app_commands.Choice(name='Pot of Duality', value='Pot of Duality'),
            app_commands.Choice(name='One Day of Peace', value='One Day of Peace'),
            app_commands.Choice(name='Book of Moon', value='Book of Moon'),
            app_commands.Choice(name='Allure of Darkness', value='Allure of Darkness'),
            app_commands.Choice(name='Monster Reborn', value='Monster Reborn'),
            app_commands.Choice(name='Upstart Goblin', value='Upstart Goblin'),
            app_commands.Choice(name='Creature Swap', value='Creature Swap'),
            app_commands.Choice(name='Forbidden Chalice', value='Forbidden Chalice'),
        ],sortilege=[
            app_commands.Choice(name='Card Destruction', value='Card Destruction'),
            app_commands.Choice(name='Mind Control', value='Mind Control'),
            app_commands.Choice(name='Enemy Controller', value='Enemy Controller'),
            app_commands.Choice(name='Eradicator Epidemic Virus', value='Eradicator Epidemic Virus'),
            app_commands.Choice(name='Offerings to the Doomed', value='Offerings to the Doomed'),
            app_commands.Choice(name='Dark Hole', value='Dark Hole'),
            app_commands.Choice(name='Terraforming', value='Terraforming'),
            app_commands.Choice(name='Mystical Space Typhoon', value='Mystical Space Typhoon'),
        ])
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    async def set_choices(self,interaction:discord.Interaction,bonbon:app_commands.Choice[str],sortilege:app_commands.Choice[str],code:str|None=None)->None:
        await interaction.response.defer(ephemeral=True)
        try:
            tournament=await self._resolve(interaction,code); status=str(getattr(tournament.status,"value",tournament.status)).lower().strip()
            if status!="registration": raise ValueError("Les choix ne peuvent être modifiés que pendant les inscriptions.")
            await self._save(int(tournament.id),interaction.user,bonbon.value,sortilege.value)
        except ValueError as e: await interaction.followup.send(f"❌ {e}",ephemeral=True); return
        await interaction.followup.send(f"✅ 🍬 **{bonbon.value}** · 🪄 **{sortilege.value}**",ephemeral=True)

    @halloween.command(name="offer",description="Faire choisir Bonbon ou Sort à ton adversaire")
    @app_commands.describe(adversaire="Adversaire qui choisit",code="Code facultatif")
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    async def offer(self,interaction:discord.Interaction,adversaire:discord.Member,code:str|None=None)->None:
        await interaction.response.defer(ephemeral=False)
        if adversaire.id==interaction.user.id: await interaction.followup.send("❌ Tu ne peux pas te choisir toi-même.",ephemeral=True); return
        try:
            tournament=await self._resolve(interaction,code)
            row=await self._choice_row(int(tournament.id),str(interaction.user.id))
            opponent_row=await self._choice_row(int(tournament.id),str(adversaire.id))
        except ValueError as e: await interaction.followup.send(f"❌ {e}",ephemeral=True); return
        if row is None: await interaction.followup.send("❌ Enregistre d'abord tes choix avec `/halloween set_choices`.",ephemeral=True); return
        if opponent_row is None: await interaction.followup.send("❌ Cet adversaire n'a pas encore de choix Halloween enregistré pour ce tournoi.",ephemeral=True); return
        view=HalloweenOfferView(chooser_id=int(adversaire.id),requester_name=getattr(interaction.user,"display_name",interaction.user.name),candy=str(row["halloween_candy"]),spell=str(row["halloween_spell"]),tournament_code=str(tournament.code))
        embed=discord.Embed(title="🎃 Bonbon ou Sort ?",description=f"{adversaire.mention}, choisis le Halloween Slot de {interaction.user.mention}. Tu ne vois pas la carte avant de choisir.",color=discord.Color.orange())
        await interaction.followup.send(embed=embed,view=view,ephemeral=False)

    @halloween.command(name="roster",description="Staff : voir les choix déclarés")
    @app_commands.describe(code="Code facultatif")
    @app_commands.autocomplete(code=active_tournament_code_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def roster(self,interaction:discord.Interaction,code:str|None=None)->None:
        await interaction.response.defer(ephemeral=True)
        try: tournament=await self._resolve(interaction,code); rows=await self.db.fetchall("SELECT username,halloween_candy,halloween_spell FROM halloween_choices WHERE tournament_id=? ORDER BY LOWER(username)",(int(tournament.id),))
        except ValueError as e: await interaction.followup.send(f"❌ {e}",ephemeral=True); return
        if not rows: await interaction.followup.send("Aucun choix enregistré.",ephemeral=True); return
        text="\n".join(f"• **{r['username']}** — 🍬 {r['halloween_candy']} · 🪄 {r['halloween_spell']}" for r in rows)
        await interaction.followup.send(embed=discord.Embed(title=f"🎃 Choix Halloween · {tournament.code}",description=text[:3900],color=discord.Color.orange()),ephemeral=True)

async def setup(bot:commands.Bot)->None:
    await bot.add_cog(HalloweenTournamentCog(bot))
