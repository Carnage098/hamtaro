from __future__ import annotations

import datetime as dt
import py_compile
import shutil
import sys
from pathlib import Path


FILES = (
    Path("cogs/public_website.py"),
    Path("web/templates/base.html"),
    Path("web/static/style.css"),
)


def main() -> int:
    script_root = Path(__file__).resolve().parent
    payload = script_root / "payload"

    project_root = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) >= 2
        else Path.cwd().resolve()
    )

    required = (
        project_root / "bot.py",
        project_root / "cogs" / "public_website.py",
        project_root / "web" / "templates" / "base.html",
        project_root / "web" / "static" / "style.css",
    )

    missing = [path for path in required if not path.exists()]
    if missing:
        print("❌ Installation impossible. Fichiers manquants :")
        for path in missing:
            print(f"  - {path}")
        return 1

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = (
        project_root
        / "_hamtaro_update_backups"
        / f"bot_avatar_{timestamp}"
    )
    backup_root.mkdir(parents=True, exist_ok=True)

    for relative in FILES:
        source = payload / relative
        destination = project_root / relative

        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, backup)

        shutil.copy2(source, destination)

    try:
        py_compile.compile(
            str(project_root / "cogs" / "public_website.py"),
            doraise=True,
        )
    except py_compile.PyCompileError as error:
        print("❌ Erreur de syntaxe. Restauration automatique.")

        for relative in FILES:
            source = backup_root / relative
            destination = project_root / relative
            shutil.copy2(source, destination)

        print(error)
        return 1

    report = (
        project_root
        / "HAMTARO_BOT_AVATAR_HOTFIX.txt"
    )
    report.write_text(
        "\n".join(
            [
                "Correctif avatar Hamtaro installé.",
                f"Sauvegarde : {backup_root}",
                "",
                "Modification :",
                "- l'avatar Discord actuel du bot remplace le carré H",
                "- aucun fichier image n'est généré",
                "- l'avatar se met à jour avec celui du bot Discord",
                "",
                "Redéploie maintenant Railway.",
            ]
        ) + "\n",
        encoding="utf-8",
    )

    print("✅ Avatar Discord de Hamtaro ajouté au site.")
    print(f"📦 Sauvegarde : {backup_root}")
    print(f"📄 Rapport : {report}")
    print("🚀 Redéploie maintenant Railway.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
