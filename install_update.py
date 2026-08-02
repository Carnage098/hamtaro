from __future__ import annotations

import datetime as dt
import py_compile
import re
import shutil
import sys
from pathlib import Path


TARGETS = (
    Path("services/database_service.py"),
    Path("services/tournament_service.py"),
)


def patch_database_service(source: str) -> tuple[str, bool]:
    changed = False

    replacements = (
        (
            "if max_players not in (4, 8, 16, 32, 64):",
            "if max_players not in (4, 8, 16, 32, 64, 128):",
        ),
        (
            (
                '"Le tournoi doit contenir 4, 8, 16, 32 '
                'ou 64 joueurs."'
            ),
            (
                '"Le tournoi doit contenir 4, 8, 16, 32, '
                '64 ou 128 joueurs."'
            ),
        ),
    )

    result = source

    for old, new in replacements:
        if old in result:
            result = result.replace(old, new)
            changed = True

    return result, changed


def patch_tournament_service(source: str) -> tuple[str, bool]:
    changed = False
    result = source

    replacements = (
        (
            "VALID_PLAYER_COUNTS = {4, 8, 16, 32, 64}",
            (
                "VALID_PLAYER_COUNTS = "
                "{4, 8, 16, 32, 64, 128}"
            ),
        ),
        (
            (
                '"Valeurs autorisées : 4, 8, 16, '
                '32 ou 64."'
            ),
            (
                '"Valeurs autorisées : 4, 8, 16, '
                '32, 64 ou 128."'
            ),
        ),
    )

    for old, new in replacements:
        if old in result:
            result = result.replace(old, new)
            changed = True

    return result, changed


def already_supports_128(path: Path, source: str) -> bool:
    if path.name == "database_service.py":
        return (
            "if max_players not in "
            "(4, 8, 16, 32, 64, 128):"
            in source
        )

    if path.name == "tournament_service.py":
        return (
            "VALID_PLAYER_COUNTS = "
            "{4, 8, 16, 32, 64, 128}"
            in source
        )

    return False


def validate(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    if not already_supports_128(path, source):
        raise RuntimeError(
            f"Le support 128 joueurs est absent de {path}."
        )

    py_compile.compile(
        str(path),
        doraise=True,
    )


def main() -> int:
    project_root = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) >= 2
        else Path.cwd().resolve()
    )

    if not (project_root / "bot.py").exists():
        print(
            "❌ Le dossier choisi ne ressemble pas "
            "au projet Hamtaro."
        )
        return 1

    existing_targets = [
        project_root / relative
        for relative in TARGETS
        if (project_root / relative).exists()
    ]

    if not existing_targets:
        print(
            "❌ Aucun service de tournoi compatible trouvé."
        )
        print(
            "Fichiers recherchés :"
        )
        for relative in TARGETS:
            print(f"  - {relative}")
        return 1

    timestamp = dt.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    backup_root = (
        project_root
        / "_hamtaro_update_backups"
        / f"capacity_128_{timestamp}"
    )
    backup_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    changed_files: list[Path] = []
    already_updated: list[Path] = []

    for target in existing_targets:
        source = target.read_text(encoding="utf-8")

        if already_supports_128(target, source):
            already_updated.append(target)
            continue

        relative = target.relative_to(project_root)
        backup = backup_root / relative
        backup.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(target, backup)

        if target.name == "database_service.py":
            updated, changed = patch_database_service(
                source
            )
        else:
            updated, changed = patch_tournament_service(
                source
            )

        if not changed:
            print(
                "❌ La structure attendue est introuvable "
                f"dans {relative}."
            )

            for changed_target in changed_files:
                changed_relative = (
                    changed_target.relative_to(project_root)
                )
                changed_backup = (
                    backup_root / changed_relative
                )
                shutil.copy2(
                    changed_backup,
                    changed_target,
                )

            return 1

        target.write_text(
            updated,
            encoding="utf-8",
        )
        changed_files.append(target)

    try:
        for target in existing_targets:
            validate(target)
    except Exception as error:
        for target in changed_files:
            relative = target.relative_to(project_root)
            backup = backup_root / relative

            if backup.exists():
                shutil.copy2(backup, target)

        print(
            "❌ La mise à jour n'a pas passé "
            "les vérifications."
        )
        print(
            "Les anciens fichiers ont été restaurés."
        )
        print(
            f"{type(error).__name__}: {error}"
        )
        return 1

    report = (
        project_root
        / "HAMTARO_128_PLAYERS_INSTALLATION.txt"
    )

    lines = [
        "Capacité 128 joueurs ajoutée à Hamtaro.",
        f"Sauvegarde : {backup_root}",
        "",
        "Capacités autorisées en élimination directe :",
        "4, 8, 16, 32, 64 et 128 joueurs.",
        "",
        "Fichiers modifiés :",
    ]

    if changed_files:
        lines.extend(
            f"- {path.relative_to(project_root)}"
            for path in changed_files
        )
    else:
        lines.append(
            "- Aucun : le support était déjà présent."
        )

    if already_updated:
        lines.extend(
            [
                "",
                "Fichiers déjà compatibles :",
                *[
                    f"- {path.relative_to(project_root)}"
                    for path in already_updated
                ],
            ]
        )

    lines.extend(
        [
            "",
            "Aucune migration SQLite nécessaire.",
            "Redéploie ensuite Railway.",
        ]
    )

    report.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("✅ Capacité de 128 joueurs activée.")
    print(
        "🎮 Capacités : 4, 8, 16, 32, 64 et 128."
    )
    print(f"📦 Sauvegarde : {backup_root}")
    print(f"📄 Rapport : {report}")
    print("🚀 Redéploie maintenant Railway.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
