from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path.cwd().resolve()

FILES_TO_COPY = (
    Path("cogs/professional_web.py"),
    Path("services/staff_dashboard_service.py"),
    Path("web/templates/staff_login.html"),
    Path("web/templates/staff_dashboard.html"),
    Path("web/static/professional.css"),
    Path("web/static/staff_dashboard.js"),
)


def backup(path: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    destination = backup_root / path.relative_to(PROJECT_ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)


def patch_bot(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    # Supprime d'abord l'entrée existante pour garantir le bon ordre.
    lines = [
        line
        for line in text.splitlines(keepends=True)
        if '"cogs.professional_web"' not in line
        and "'cogs.professional_web'" not in line
    ]
    text = "".join(lines)

    public_markers = (
        '    "cogs.public_website",\n',
        "    'cogs.public_website',\n",
    )
    inserted = False
    for marker in public_markers:
        if marker in text:
            quote = '"' if '"' in marker else "'"
            text = text.replace(
                marker,
                f"    {quote}cogs.professional_web{quote},\n" + marker,
                1,
            )
            inserted = True
            break

    if not inserted:
        raise RuntimeError(
            "Impossible de trouver cogs.public_website dans bot.py."
        )

    # Ajoute les commandes professionnelles seulement si leur fichier existe.
    professional_tools = PROJECT_ROOT / "cogs" / "professional_tools.py"
    if professional_tools.exists() and "cogs.professional_tools" not in text:
        hub_markers = (
            '    "cogs.hamtaro_hub",\n',
            "    'cogs.hamtaro_hub',\n",
        )
        for marker in hub_markers:
            if marker in text:
                quote = '"' if '"' in marker else "'"
                text = text.replace(
                    marker,
                    marker + f"    {quote}cogs.professional_tools{quote},\n",
                    1,
                )
                break

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def patch_base(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    css_line = '    <link rel="stylesheet" href="/static/professional.css">\n'
    if css_line not in text:
        anchor = '    <link rel="stylesheet" href="/static/style.css">\n'
        if anchor not in text:
            raise RuntimeError("Lien style.css introuvable dans base.html.")
        text = text.replace(anchor, anchor + css_line, 1)

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    required = (
        PROJECT_ROOT / "bot.py",
        PROJECT_ROOT / "cogs" / "public_website.py",
        PROJECT_ROOT / "web" / "templates" / "base.html",
    )
    if not all(path.exists() for path in required):
        print(
            "ERREUR : lance ce script depuis la racine du dépôt Hamtaro.",
            file=sys.stderr,
        )
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = PROJECT_ROOT / "upgrade_backup" / f"staff-dashboard-{stamp}"

    targets = [PROJECT_ROOT / relative for relative in FILES_TO_COPY]
    targets.extend(
        [
            PROJECT_ROOT / "bot.py",
            PROJECT_ROOT / "web" / "templates" / "base.html",
        ]
    )
    for target in targets:
        backup(target, backup_root)

    for relative in FILES_TO_COPY:
        source = PACKAGE_ROOT / relative
        destination = PROJECT_ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    bot_changed = patch_bot(PROJECT_ROOT / "bot.py")
    base_changed = patch_base(
        PROJECT_ROOT / "web" / "templates" / "base.html"
    )

    print("✅ Correctif du tableau de bord staff installé.")
    print(f"📁 Sauvegarde : {backup_root}")
    print(f"🧩 bot.py modifié : {'oui' if bot_changed else 'déjà correct'}")
    print(f"🎨 base.html modifié : {'oui' if base_changed else 'déjà correct'}")
    print("\nÉtapes suivantes :")
    print("  python3 -m compileall cogs services")
    print("  git add .")
    print('  git commit -m "Correction du tableau de bord staff"')
    print("  git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
