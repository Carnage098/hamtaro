#!/usr/bin/env python3
from __future__ import annotations

import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path

COG_ENTRY = '    "cogs.team_2v2",\n'
ANCHORS = (
    '    "cogs.swiss",\n',
    '    "cogs.match_center",\n',
)
MARK = "HAMTARO_2V2_V2"


def _function_span(text: str, name: str) -> tuple[int, int]:
    match = re.search(rf"(?m)^    async def {re.escape(name)}\s*\(", text)
    if not match:
        raise RuntimeError(f"Fonction {name} introuvable")
    start = match.start()
    next_match = re.search(r"(?m)^    (?:@app_commands\.command\(|async def |def )", text[match.end():])
    end = len(text) if not next_match else match.end() + next_match.start()
    return start, end


def _replace_function_section(text: str, name: str, transform) -> str:
    start, end = _function_span(text, name)
    section = text[start:end]
    new_section = transform(section)
    if new_section == section:
        raise RuntimeError(f"Aucune modification appliquée à {name}")
    return text[:start] + new_section + text[end:]


def _insert_after_required_tournament(section: str, code: str) -> str:
    pattern = re.compile(
        r"(?P<indent>[ \t]*)tournament\s*=\s*await self\._get_required_tournament\(\s*interaction\s*\)"
    )
    match = pattern.search(section)
    if not match:
        raise RuntimeError("Résolution du tournoi introuvable")
    indent = match.group("indent")
    block = "\n" + "\n".join(indent + line if line else "" for line in code.strip("\n").splitlines())
    return section[:match.end()] + block + section[match.end():]


def patch_tournament(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if f"# {MARK}:TOURNAMENT" in text:
        return

    # 1) Paramètre /create_tournament
    create_start = text.find('name="create_tournament"')
    if create_start < 0:
        raise RuntimeError("/create_tournament introuvable")
    create_end = text.find("# ==========================================================", create_start + 50)
    if create_end < 0:
        create_end = len(text)
    block = text[create_start:create_end]

    block = block.replace(
        'max_players="Nombre maximum de joueurs",',
        'max_players="Nombre maximum de joueurs / équipes",\n        participants="Type de participants",',
        1,
    )
    if 'participants="Type de participants"' not in block:
        # Variante sans virgule finale.
        block = block.replace(
            'max_players="Nombre maximum de joueurs"',
            'max_players="Nombre maximum de joueurs / équipes",\n        participants="Type de participants"',
            1,
        )

    marker = "@app_commands.default_permissions("
    if marker not in block:
        raise RuntimeError("Décorateur default_permissions de /create_tournament introuvable")
    participant_choices = '''@app_commands.choices(
        participants=[
            app_commands.Choice(name="👤 Solo 1v1", value="solo"),
            app_commands.Choice(name="👥 Équipes 2v2", value="duo"),
        ]
    )
    '''
    block = block.replace(marker, participant_choices + marker, 1)

    signature_pattern = re.compile(
        r"(async def create_tournament\(.*?max_players:\s*int,)(\s*\)\s*->\s*None:)",
        re.S,
    )
    block, count = signature_pattern.subn(
        r"\1\n        participants: app_commands.Choice[str],\2",
        block,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Signature de /create_tournament non reconnue")

    # Après la création DB, avant la sélection du salon. L'indentation varie
    # selon que la commande est déjà dans un bloc try.
    channel_match = re.search(
        r'(?m)^(?P<indent>[ \t]*)if interaction\.channel_id is not None:',
        block,
    )
    if not channel_match:
        raise RuntimeError("Ancre channel_id de /create_tournament introuvable")
    indent = channel_match.group("indent")
    native_lines = [
        f'{indent}# HAMTARO_2V2_V2:TOURNAMENT',
        f'{indent}duo_cog = self.bot.get_cog("Team2v2Cog")',
        f'{indent}if duo_cog is None:',
        f'{indent}    raise RuntimeError("Le module 2v2 Hamtaro n\'est pas chargé.")',
        f'{indent}participant_mode = await duo_cog.set_participant_mode(',
        f'{indent}    int(tournament.id),',
        f'{indent}    participants.value,',
        f'{indent})',
        '',
    ]
    native_setup = "\n".join(native_lines)
    block = block[:channel_match.start()] + native_setup + block[channel_match.start():]

    # Affichage du type de participants.
    format_field_end = re.search(
        r'(?ms)(^[ \t]*embed\.add_field\([ \t]*\n[ \t]*name="Format",.*?^[ \t]*\)[ \t]*\n)',
        block,
    )
    if format_field_end:
        insert_at = format_field_end.end()
        field = '''\n        embed.add_field(
            name="Participants",
            value=("👥 Équipes 2v2" if participant_mode == "duo" else "👤 Solo 1v1"),
            inline=True,
        )\n'''
        block = block[:insert_at] + field + block[insert_at:]

    block = block.replace(
        'name="Joueurs",\n            value=f"0/{tournament.max_players}"',
        'name=("Équipes" if participant_mode == "duo" else "Joueurs"),\n            value=f"0/{tournament.max_players}"',
        1,
    )
    text = text[:create_start] + block + text[create_end:]

    # 2) /start_tournament => élimination 2v2 automatique
    def patch_start(section: str) -> str:
        anchor = re.search(r"(?m)^([ \t]*)await self\.brackets\.generate\(", section)
        if not anchor:
            raise RuntimeError("brackets.generate introuvable dans /start_tournament")
        indent = anchor.group(1)
        code = f'''{indent}# {MARK}:START_ELIMINATION
{indent}duo_cog = self.bot.get_cog("Team2v2Cog")
{indent}if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
{indent}    text = await duo_cog.start_from_native(int(tournament.id), "elimination")
{indent}    await interaction.followup.send(
{indent}        "✅ **Tournoi 2v2 lancé en élimination directe !**\\n\\n" + text,
{indent}        ephemeral=True,
{indent}    )
{indent}    return
'''
        return section[:anchor.start()] + code + section[anchor.start():]

    text = _replace_function_section(text, "start_tournament", patch_start)
    path.write_text(text, encoding="utf-8")


def patch_registration(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if f"# {MARK}:REGISTER" in text:
        return

    # /register : ajoute team_id sans créer une nouvelle commande racine.
    reg_start = text.find('name="register"')
    if reg_start < 0:
        raise RuntimeError("/register introuvable")
    reg_end = text.find("# ==========================================================", reg_start + 20)
    block = text[reg_start:reg_end]
    block = block.replace(
        'code="Code facultatif du tournoi",',
        'code="Code facultatif du tournoi",\n        team_id="ID de ton équipe 2v2 si tu en as plusieurs",',
        1,
    )
    if 'team_id="ID de ton équipe 2v2' not in block:
        block = block.replace(
            'code="Code facultatif du tournoi"',
            'code="Code facultatif du tournoi",\n        team_id="ID de ton équipe 2v2 si tu en as plusieurs"',
            1,
        )
    sig = re.compile(r"(async def register\(.*?code:\s*str\s*\|\s*None\s*=\s*None)(,?)(\s*\))", re.S)
    block, count = sig.subn(r"\1,\n        team_id: int | None = None,\3", block, count=1)
    if count != 1:
        raise RuntimeError("Signature /register non reconnue")

    insertion_anchor = re.search(r"(?m)^([ \t]*)user\s*=\s*interaction\.user", block)
    if not insertion_anchor:
        raise RuntimeError("Ancre user de /register introuvable")
    indent = insertion_anchor.group(1)
    code = f'''{indent}# {MARK}:REGISTER
{indent}duo_cog = self.bot.get_cog("Team2v2Cog")
{indent}if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
{indent}    await duo_cog.register_from_native(interaction, tournament, team_id=team_id, deck=deck)
{indent}    return
'''
    block = block[:insertion_anchor.start()] + code + block[insertion_anchor.start():]
    text = text[:reg_start] + block + text[reg_end:]

    # /unregister
    def patch_unregister(section: str) -> str:
        anchor = re.search(r"(?m)^([ \t]*)await self\.db\.unregister_player\(", section)
        if not anchor:
            raise RuntimeError("unregister_player introuvable")
        indent = anchor.group(1)
        code = f'''{indent}# {MARK}:UNREGISTER
{indent}duo_cog = self.bot.get_cog("Team2v2Cog")
{indent}if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
{indent}    await duo_cog.unregister_from_native(interaction, tournament)
{indent}    return
'''
        return section[:anchor.start()] + code + section[anchor.start():]
    text = _replace_function_section(text, "unregister", patch_unregister)

    # /deck
    def patch_deck(section: str) -> str:
        anchor = re.search(r"(?m)^([ \t]*)registration\s*=\s*await self\.db\.get_registration_by_user\(", section)
        if not anchor:
            raise RuntimeError("get_registration_by_user introuvable dans /deck")
        indent = anchor.group(1)
        code = f'''{indent}# {MARK}:DECK
{indent}duo_cog = self.bot.get_cog("Team2v2Cog")
{indent}if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
{indent}    await duo_cog.update_deck_from_native(interaction, tournament, deck)
{indent}    return
'''
        return section[:anchor.start()] + code + section[anchor.start():]
    text = _replace_function_section(text, "deck", patch_deck)

    # /players
    def patch_players(section: str) -> str:
        anchor = re.search(r"(?m)^([ \t]*)registrations\s*=\s*await self\.db\.list_registrations\(", section)
        if not anchor:
            raise RuntimeError("list_registrations introuvable dans /players")
        indent = anchor.group(1)
        code = f'''{indent}# {MARK}:PLAYERS
{indent}duo_cog = self.bot.get_cog("Team2v2Cog")
{indent}if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
{indent}    await duo_cog.players_from_native(interaction, tournament)
{indent}    return
'''
        return section[:anchor.start()] + code + section[anchor.start():]
    text = _replace_function_section(text, "players", patch_players)

    path.write_text(text, encoding="utf-8")


def patch_swiss(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if f"# {MARK}:SWISS_START" in text:
        return

    routes = {
        "swiss_start": f'''# {MARK}:SWISS_START
duo_cog = self.bot.get_cog("Team2v2Cog")
if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
    text = await duo_cog.start_from_native(int(tournament.id), "swiss", total_rounds=rondes)
    await interaction.followup.send(
        "✅ **Rondes suisses 2v2 lancées !**\\n\\n" + text,
        ephemeral=not visible,
    )
    return''',
        "swiss_pairings": f'''# {MARK}:SWISS_PAIRINGS
duo_cog = self.bot.get_cog("Team2v2Cog")
if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
    text = await duo_cog.format_swiss_pairings(int(tournament.id), ronde)
    await interaction.followup.send(text, ephemeral=False)
    return''',
        "swiss_next": f'''# {MARK}:SWISS_NEXT
duo_cog = self.bot.get_cog("Team2v2Cog")
if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
    text = await duo_cog.swiss_next_from_native(int(tournament.id))
    await interaction.followup.send(text, ephemeral=not visible)
    return''',
        "swiss_standings": f'''# {MARK}:SWISS_STANDINGS
duo_cog = self.bot.get_cog("Team2v2Cog")
if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
    text = await duo_cog.format_swiss_standings(int(tournament.id))
    await interaction.followup.send(text, ephemeral=False)
    return''',
        "swiss_status": f'''# {MARK}:SWISS_STATUS
duo_cog = self.bot.get_cog("Team2v2Cog")
if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
    text = await duo_cog.format_swiss_status(int(tournament.id))
    await interaction.followup.send(text, ephemeral=True)
    return''',
        "swiss_reset": f'''# {MARK}:SWISS_RESET
duo_cog = self.bot.get_cog("Team2v2Cog")
if duo_cog is not None and await duo_cog.is_duo_tournament(int(tournament.id)):
    await duo_cog.reset_swiss_from_native(int(tournament.id))
    await interaction.followup.send(
        "✅ Les rondes suisses 2v2 ont été réinitialisées.",
        ephemeral=True,
    )
    return''',
    }

    for func, code in routes.items():
        text = _replace_function_section(
            text,
            func,
            lambda section, code=code: _insert_after_required_tournament(section, code),
        )
    path.write_text(text, encoding="utf-8")


def patch_bot(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if COG_ENTRY in text:
        return
    for anchor in ANCHORS:
        if anchor in text:
            path.write_text(text.replace(anchor, anchor + COG_ENTRY, 1), encoding="utf-8")
            return
    raise RuntimeError("REQUIRED_COGS introuvable dans bot.py")


def main() -> None:
    pack_dir = Path(__file__).resolve().parent
    root = Path.cwd().resolve()
    required = [
        root / "bot.py",
        root / "cogs" / "tournament.py",
        root / "cogs" / "registration.py",
        root / "cogs" / "swiss.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("❌ Fichiers Hamtaro manquants : " + ", ".join(missing))

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = root / "upgrade_backup" / f"team_2v2_native_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for source in required:
        shutil.copy2(source, backup_dir / source.name)

    payload_files = {
        pack_dir / "payload" / "cogs" / "team_2v2.py": root / "cogs" / "team_2v2.py",
        pack_dir / "payload" / "services" / "team_2v2_service.py": root / "services" / "team_2v2_service.py",
        pack_dir / "payload" / "tests" / "test_team_2v2_service.py": root / "tests" / "test_team_2v2_service.py",
    }
    for src, dst in payload_files.items():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.copy2(dst, backup_dir / dst.name)
        shutil.copy2(src, dst)

    try:
        patch_bot(root / "bot.py")
        patch_tournament(root / "cogs" / "tournament.py")
        patch_registration(root / "cogs" / "registration.py")
        patch_swiss(root / "cogs" / "swiss.py")

        for target in [
            root / "bot.py",
            root / "cogs" / "tournament.py",
            root / "cogs" / "registration.py",
            root / "cogs" / "swiss.py",
            root / "cogs" / "team_2v2.py",
            root / "services" / "team_2v2_service.py",
        ]:
            py_compile.compile(str(target), doraise=True)
    except Exception as error:
        print(f"❌ Installation interrompue : {error}")
        print(f"↩️ Restauration automatique depuis {backup_dir}")
        for name in ("bot.py", "tournament.py", "registration.py", "swiss.py"):
            backup = backup_dir / name
            if backup.exists():
                if name == "bot.py":
                    target = root / name
                else:
                    target = root / "cogs" / name
                shutil.copy2(backup, target)
        raise SystemExit(1)

    print("✅ Hamtaro 2v2 Native v2 installé.")
    print(f"✅ Sauvegarde : {backup_dir}")
    print("✅ /create_tournament propose maintenant Solo 1v1 ou Équipes 2v2.")
    print("✅ /register détecte automatiquement le mode du tournoi.")
    print("✅ /start_tournament lance automatiquement l'élimination 2v2.")
    print("✅ /swiss_start, pairings, next, standings, status et reset détectent le 2v2.")
    print("✅ Les anciens tournois restent Solo 1v1 par défaut.")
    print("✅ Règle DL suisse conservée : victoire + DL = 0 point ; défaite + DL = 0 point et mauvais départage.")
    print("")
    print("Résultats individuels des boards 2v2 : /duo report puis /duo confirm.")


if __name__ == "__main__":
    main()
