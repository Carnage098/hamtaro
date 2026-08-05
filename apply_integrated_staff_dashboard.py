from __future__ import annotations

import argparse
import py_compile
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent


class InstallError(RuntimeError):
    pass


def backup_file(
    source: Path,
    backup_root: Path,
    project_root: Path,
) -> None:
    if not source.exists():
        return

    relative = source.relative_to(project_root)
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_file(
    relative_path: str,
    project_root: Path,
    backup_root: Path,
) -> None:
    source = PACKAGE_ROOT / relative_path
    destination = project_root / relative_path

    if not source.exists():
        raise InstallError(
            f"Fichier absent du correctif : {relative_path}"
        )

    backup_file(destination, backup_root, project_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def patch_public_website(path: Path) -> None:
    if not path.exists():
        raise InstallError(
            "cogs/public_website.py est introuvable."
        )

    text = path.read_text(encoding="utf-8")

    import_line = (
        "from services.staff_dashboard_routes import "
        "register_staff_dashboard_routes"
    )

    if import_line not in text:
        marker = "LOGGER = logging.getLogger(__name__)"
        if marker not in text:
            raise InstallError(
                "Point d'insertion des imports introuvable "
                "dans public_website.py."
            )

        text = text.replace(
            marker,
            f"{import_line}\n\n{marker}",
            1,
        )

    route_call = (
        "        register_staff_dashboard_routes(\n"
        "            application,\n"
        "            self,\n"
        "        )\n"
    )

    if "register_staff_dashboard_routes(" not in text.replace(
        import_line,
        "",
        1,
    ):
        marker = (
            '        application.router.add_get('
            '"/health", self.health_page)\n'
        )

        if marker not in text:
            raise InstallError(
                "Route /health introuvable dans "
                "PublicWebsiteCog._start_server()."
            )

        text = text.replace(
            marker,
            marker + route_call,
            1,
        )

    text = text.replace(
        'HAMTARO_SITE_BUILD = "interaction-fix-2026-08-04-2133"',
        'HAMTARO_SITE_BUILD = "staff-integrated-2026-08-05"',
    )

    text = text.replace(
        "Elle n'ajoute aucune administration web.",
        (
            "Le tableau de bord staff est enregistré directement "
            "dans ce serveur."
        ),
    )

    text = text.replace(
        "Site public Hamtaro lancé sur %s:%s.",
        "Site Hamtaro public + staff lancé sur %s:%s.",
    )

    path.write_text(text, encoding="utf-8")


def patch_bot(path: Path) -> None:
    if not path.exists():
        raise InstallError("bot.py est introuvable.")

    lines = path.read_text(encoding="utf-8").splitlines()
    result: list[str] = []
    seen_cogs: set[str] = set()

    for line in lines:
        match = re.match(
            r'^(\s*)"(?P<cog>cogs\.[^"]+)",\s*$',
            line,
        )

        if match:
            cog = match.group("cog")

            if cog == "cogs.professional_web":
                continue

            if cog in seen_cogs:
                continue

            seen_cogs.add(cog)

        result.append(line)

    path.write_text(
        "\n".join(result) + "\n",
        encoding="utf-8",
    )


def ensure_stylesheet(project_root: Path) -> None:
    base_template = (
        project_root
        / "web"
        / "templates"
        / "base.html"
    )

    if not base_template.exists():
        return

    text = base_template.read_text(encoding="utf-8")
    stylesheet = (
        '<link rel="stylesheet" '
        'href="/static/professional.css">'
    )

    if stylesheet in text:
        return

    if "</head>" not in text:
        print(
            "AVERTISSEMENT : </head> introuvable dans base.html. "
            "Ajoute professional.css manuellement."
        )
        return

    text = text.replace(
        "</head>",
        f"    {stylesheet}\n</head>",
        1,
    )
    base_template.write_text(text, encoding="utf-8")


def validate(project_root: Path) -> None:
    files = [
        project_root / "bot.py",
        project_root / "cogs" / "public_website.py",
        project_root / "cogs" / "professional_web.py",
        project_root
        / "services"
        / "staff_dashboard_routes.py",
        project_root
        / "services"
        / "staff_dashboard_service.py",
    ]

    for path in files:
        py_compile.compile(
            str(path),
            doraise=True,
        )

    public_text = (
        project_root
        / "cogs"
        / "public_website.py"
    ).read_text(encoding="utf-8")

    bot_text = (
        project_root / "bot.py"
    ).read_text(encoding="utf-8")

    if "register_staff_dashboard_routes(" not in public_text:
        raise InstallError(
            "Les routes staff n'ont pas été intégrées."
        )

    if '"cogs.professional_web",' in bot_text:
        raise InstallError(
            "professional_web est encore chargé dans bot.py."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Intègre définitivement le tableau staff "
            "dans le site Hamtaro."
        )
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Racine du dépôt Hamtaro.",
    )
    arguments = parser.parse_args()

    project_root = Path(
        arguments.project_root
    ).expanduser().resolve()

    if not (project_root / "bot.py").exists():
        raise InstallError(
            "Lance ce script depuis la racine du dépôt Hamtaro "
            "ou utilise --project-root."
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = (
        project_root
        / "upgrade_backup"
        / f"staff_integrated_{timestamp}"
    )

    backup_file(
        project_root / "bot.py",
        backup_root,
        project_root,
    )
    backup_file(
        project_root / "cogs" / "public_website.py",
        backup_root,
        project_root,
    )
    backup_file(
        project_root / "cogs" / "professional_web.py",
        backup_root,
        project_root,
    )

    for relative_path in (
        "services/staff_dashboard_routes.py",
        "services/staff_dashboard_service.py",
        "cogs/professional_web.py",
        "web/templates/staff_login.html",
        "web/templates/staff_dashboard.html",
        "web/static/staff_dashboard.js",
        "web/static/professional.css",
    ):
        copy_file(
            relative_path,
            project_root,
            backup_root,
        )

    patch_public_website(
        project_root / "cogs" / "public_website.py"
    )
    patch_bot(project_root / "bot.py")
    ensure_stylesheet(project_root)
    validate(project_root)

    print()
    print("Installation réussie.")
    print(
        "Les routes /staff sont maintenant enregistrées "
        "directement par public_website.py."
    )
    print(
        "cogs.professional_web n'est plus chargé "
        "et l'ordre des cogs n'a plus d'importance."
    )
    print(f"Sauvegarde : {backup_root}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as error:
        print(f"ERREUR : {error}", file=sys.stderr)
        raise SystemExit(1)
