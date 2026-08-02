from __future__ import annotations

import ast
import datetime as dt
import py_compile
import shutil
import sys
from pathlib import Path


REQUIRED_METHODS = {
    "index_page",
    "tournament_page",
    "profiles_page",
    "guide_page",
    "results_page",
    "decks_page",
    "archives_page",
    "player_page",
    "bracket_image",
    "bracket_version",
    "health_page",
    "hamtaro_site",
    "_build_command_catalog",
}


def validate_file(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "PublicWebsiteCog"
        ),
        None,
    )

    if class_node is None:
        raise RuntimeError(
            "PublicWebsiteCog est introuvable."
        )

    methods = {
        node.name
        for node in class_node.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    missing = sorted(REQUIRED_METHODS - methods)
    if missing:
        raise RuntimeError(
            "Méthodes absentes de PublicWebsiteCog : "
            + ", ".join(missing)
        )

    py_compile.compile(
        str(path),
        doraise=True,
    )


def main() -> int:
    script_root = Path(__file__).resolve().parent
    source = (
        script_root
        / "payload"
        / "cogs"
        / "public_website.py"
    )

    project_root = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) >= 2
        else Path.cwd().resolve()
    )

    target = (
        project_root
        / "cogs"
        / "public_website.py"
    )

    if not (project_root / "bot.py").exists():
        print(
            "❌ Le dossier choisi ne ressemble pas "
            "au projet Hamtaro."
        )
        return 1

    if not target.exists():
        print(
            "❌ cogs/public_website.py est introuvable."
        )
        return 1

    timestamp = dt.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    backup_root = (
        project_root
        / "_hamtaro_update_backups"
        / f"guide_indentation_{timestamp}"
    )
    backup_file = (
        backup_root
        / "cogs"
        / "public_website.py"
    )
    backup_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(target, backup_file)
    shutil.copy2(source, target)

    try:
        validate_file(target)
    except Exception as error:
        shutil.copy2(backup_file, target)
        print(
            "❌ Le correctif n'a pas passé "
            "les vérifications."
        )
        print(
            "L'ancien fichier a été restauré."
        )
        print(
            f"{type(error).__name__}: {error}"
        )
        return 1

    report = (
        project_root
        / "HAMTARO_GUIDE_INDENTATION_HOTFIX.txt"
    )
    report.write_text(
        "\n".join(
            [
                (
                    "Correctif d'indentation du guide "
                    "Hamtaro installé."
                ),
                f"Sauvegarde : {backup_file}",
                "",
                "Corrections :",
                (
                    "- index_page est de nouveau une "
                    "méthode de PublicWebsiteCog"
                ),
                (
                    "- guide_page est de nouveau une "
                    "méthode de PublicWebsiteCog"
                ),
                (
                    "- le catalogue automatique reste "
                    "dans PublicWebsiteCog"
                ),
                (
                    "- les autres pages du site sont "
                    "de nouveau accessibles"
                ),
                (
                    "- TikTok, les profils et l'avatar "
                    "du bot sont conservés"
                ),
                "",
                "Redéploie maintenant Railway.",
            ]
        ) + "\n",
        encoding="utf-8",
    )

    print("✅ Correctif d'indentation installé.")
    print(f"📦 Sauvegarde : {backup_file}")
    print(f"📄 Rapport : {report}")
    print("🚀 Redéploie maintenant Railway.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
