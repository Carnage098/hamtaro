from __future__ import annotations

import argparse
import py_compile
import shutil
from datetime import datetime
from pathlib import Path


class FixError(RuntimeError):
    pass


def apply_fix(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    original = text

    # La base Hamtaro actuelle ne possède pas la colonne
    # tournaments.tournament_type. On conserve néanmoins la clé dans
    # les résultats publics avec une valeur NULL pour ne rien casser.
    text = text.replace(
        "                            t.tournament_type,\n",
        "                            NULL AS tournament_type,\n",
    )
    text = text.replace(
        "SELECT id, code, name, format, tournament_type, status,",
        "SELECT id, code, name, format, NULL AS tournament_type, status,",
    )

    if text == original:
        if (
            "NULL AS tournament_type" in text
            and "t.tournament_type" not in text
            and "format, tournament_type, status" not in text
        ):
            return 0

        raise FixError(
            "Les lignes attendues n'ont pas été trouvées dans "
            "services/site_experience_service.py. "
            "Le fichier utilise peut-être une autre version."
        )

    path.write_text(text, encoding="utf-8")
    return 1


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    if "t.tournament_type" in text:
        raise FixError(
            "Une référence invalide à t.tournament_type subsiste."
        )

    if "format, tournament_type, status" in text:
        raise FixError(
            "La requête de recherche globale utilise encore "
            "la colonne tournament_type."
        )

    if text.count("NULL AS tournament_type") < 3:
        raise FixError(
            "Le correctif n'a pas été appliqué aux trois requêtes attendues."
        )

    py_compile.compile(str(path), doraise=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Corrige l'erreur 500 des pages /matches et /search "
            "sans remplacer les autres améliorations du site."
        )
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="Racine du dépôt Hamtaro contenant bot.py.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    target = project_root / "services" / "site_experience_service.py"

    if not (project_root / "bot.py").exists():
        raise FixError(
            "Le dossier indiqué ne contient pas bot.py."
        )

    if not target.exists():
        raise FixError(
            "services/site_experience_service.py est introuvable. "
            "Installe d'abord le pack d'amélioration du site."
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = (
        project_root
        / "upgrade_backup"
        / f"matches_500_fix_{timestamp}"
        / "services"
        / "site_experience_service.py"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)

    changed = apply_fix(target)
    validate(target)

    print("✅ Erreur 500 de /matches corrigée.")
    print("✅ La page /search est également protégée du même problème.")
    print("✅ Les améliorations Decks existantes ont été conservées.")
    print(
        "✅ Sauvegarde : "
        + str(backup.relative_to(project_root))
    )
    if changed:
        print("➡️ Fais maintenant git add -A, git commit, puis git push.")
    else:
        print("ℹ️ Le correctif était déjà installé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
