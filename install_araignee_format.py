#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import re
import shutil
import sys
import subprocess
from datetime import datetime
from pathlib import Path


PACK_VERSION = "4.1"
HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()

NEW_FILES = {
    "araignee.json": Path("data/formats/araignee.json"),
    "araignee_format_service.py": Path("services/araignee_format_service.py"),
    "format_routes.py": Path("services/format_routes.py"),
    "araignee_format.py": Path("cogs/araignee_format.py"),
    "formats.html": Path("web/templates/formats.html"),
    "format_araignee.html": Path("web/templates/format_araignee.html"),
    "test_araignee_format.py": Path("tests/test_araignee_format.py"),
    "araignee_pool_tool.py": Path("tools/araignee_pool.py"),
    "araignee_image_sync.py": Path("tools/araignee_images.py"),
}

CSS_START = "/* ===== HAMTARO FORMAT ARAIGNEE START ===== */"
CSS_END = "/* ===== HAMTARO FORMAT ARAIGNEE END ===== */"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Installer le Format Araignée Hamtaro v{PACK_VERSION}."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Vérifier la compatibilité sans modifier le dépôt.",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Installer la v4.1 sans télécharger la galerie d'images.",
    )
    return parser.parse_args()


def require_repo() -> None:
    required = [
        ROOT / "bot.py",
        ROOT / "cogs" / "tournament.py",
        ROOT / "cogs" / "public_website.py",
        ROOT / "web" / "templates" / "base.html",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        print("❌ Lance ce script depuis la racine du dépôt Hamtaro.")
        for path in missing:
            print(" -", path)
        raise SystemExit(1)


def add_format(text: str) -> str:
    if re.search(r'["\']Araignée["\']', text):
        return text

    match = re.search(
        r"(?ms)^FORMATS\s*=\s*\[(?P<body>.*?)^\]",
        text,
    )
    if not match:
        raise RuntimeError("Liste FORMATS introuvable dans cogs/tournament.py")

    body = match.group("body")
    indent_match = re.search(r"(?m)^(\s+)[\"']", body)
    indent = indent_match.group(1) if indent_match else "    "

    insertion = body.rstrip() + f'\n{indent}"Araignée",\n'
    return text[:match.start("body")] + insertion + text[match.end("body"):]


def add_required_cog(text: str) -> str:
    if '"cogs.araignee_format"' in text or "'cogs.araignee_format'" in text:
        return text

    match = re.search(
        r"(?ms)^REQUIRED_COGS\s*=\s*\((?P<body>.*?)^\)",
        text,
    )
    if not match:
        raise RuntimeError("REQUIRED_COGS introuvable dans bot.py")

    body = match.group("body")
    anchor = re.search(
        r'(?m)^(?P<indent>\s*)["\']cogs\.tournament["\'],\s*$',
        body,
    )
    if not anchor:
        raise RuntimeError("cogs.tournament introuvable dans REQUIRED_COGS")

    insertion_point = anchor.end()
    line = f'\n{anchor.group("indent")}"cogs.araignee_format",'
    new_body = body[:insertion_point] + line + body[insertion_point:]
    return text[:match.start("body")] + new_body + text[match.end("body"):]


def add_site_routes(text: str) -> str:
    import_line = "from services.format_routes import register_format_routes\n"
    if import_line not in text:
        import_anchors = [
            "from services.banlist_routes import register_banlist_routes\n",
            "from services.web_extension_routes import register_expansion_routes\n",
            "from services.analytics_service import AnalyticsService\n",
        ]
        for anchor in import_anchors:
            if anchor in text:
                text = text.replace(anchor, anchor + import_line, 1)
                break
        else:
            # Dernier recours : avant LOGGER.
            marker = "\n\nLOGGER = logging.getLogger(__name__)"
            if marker not in text:
                raise RuntimeError("Zone d'imports introuvable dans public_website.py")
            text = text.replace(marker, "\n" + import_line + marker, 1)

    if "register_format_routes(" in text:
        return text

    # Structure actuelle : les routes principales sont ajoutées directement
    # dans _start_server. On monte les routes du format avant les fichiers statiques.
    anchors = [
        '        application.router.add_get("/favicon.ico", self.favicon)\n',
        '        application.router.add_get("/health", self.health_page)\n',
        '        application.router.add_get("/archives", self.archives_page)\n',
    ]
    for anchor in anchors:
        if anchor in text:
            addition = (
                anchor
                + "        # HAMTARO FORMAT ARAIGNEE: routes publiques et API.\n"
                + "        register_format_routes(application, self)\n"
            )
            return text.replace(anchor, addition, 1)

    raise RuntimeError(
        "Impossible de trouver la zone d'enregistrement des routes "
        "dans cogs/public_website.py"
    )


def add_navigation(text: str) -> str:
    if 'href="/formats"' in text:
        return text

    anchors = [
        '                <a href="/decks">Decks</a>\n',
        '                <a href="/archives">Archives</a>\n',
    ]
    for anchor in anchors:
        if anchor in text:
            return text.replace(
                anchor,
                '                <a href="/formats">Formats</a>\n' + anchor,
                1,
            )
    raise RuntimeError("Navigation principale introuvable dans base.html")


def replace_css_block(existing: str, block: str) -> str:
    if CSS_START in existing and CSS_END in existing:
        pattern = re.compile(
            re.escape(CSS_START) + r".*?" + re.escape(CSS_END),
            re.S,
        )
        return pattern.sub(block.strip(), existing, count=1)

    return existing.rstrip() + "\n\n" + block.strip() + "\n"


def syntax_check_python(path: Path) -> None:
    py_compile.compile(
        str(path),
        doraise=True,
    )


def main() -> int:
    args = parse_args()
    require_repo()

    originals = {
        "tournament": (ROOT / "cogs/tournament.py").read_text(encoding="utf-8"),
        "bot": (ROOT / "bot.py").read_text(encoding="utf-8"),
        "website": (ROOT / "cogs/public_website.py").read_text(encoding="utf-8"),
        "base": (ROOT / "web/templates/base.html").read_text(encoding="utf-8"),
    }

    patched = {
        "tournament": add_format(originals["tournament"]),
        "bot": add_required_cog(originals["bot"]),
        "website": add_site_routes(originals["website"]),
        "base": add_navigation(originals["base"]),
    }

    print(f"🕷️ Format Araignée v{PACK_VERSION}")
    print("✅ Structure Hamtaro compatible")
    print("✅ Patch /create_tournament prêt")
    print("✅ Chargement du cog prêt")
    print("✅ Routes du site prêtes")
    print("✅ Navigation Formats prête")

    if args.check:
        print("\nMode --check : aucune modification effectuée.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / f".araignee_backup_{stamp}"
    backup.mkdir(parents=True, exist_ok=True)

    touched: list[Path] = []

    def backup_path(path: Path) -> None:
        if not path.exists():
            return
        relative = path.relative_to(ROOT)
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    try:
        # Copie des fichiers du pack.
        for source_name, relative_target in NEW_FILES.items():
            source = HERE / source_name
            target = ROOT / relative_target
            target.parent.mkdir(parents=True, exist_ok=True)
            backup_path(target)
            shutil.copy2(source, target)
            touched.append(target)
            print("✅ écrit:", relative_target)

        # Fichiers patchés.
        patch_map = {
            ROOT / "cogs/tournament.py": patched["tournament"],
            ROOT / "bot.py": patched["bot"],
            ROOT / "cogs/public_website.py": patched["website"],
            ROOT / "web/templates/base.html": patched["base"],
        }
        for path, content in patch_map.items():
            if path.read_text(encoding="utf-8") != content:
                backup_path(path)
                path.write_text(content, encoding="utf-8")
                touched.append(path)
                print("✅ patch:", path.relative_to(ROOT))
            else:
                print("↪ déjà à jour:", path.relative_to(ROOT))

        # CSS mis à jour de façon idempotente.
        style_path = ROOT / "web/static/style.css"
        style_path.parent.mkdir(parents=True, exist_ok=True)
        existing_css = (
            style_path.read_text(encoding="utf-8")
            if style_path.exists()
            else ""
        )
        css_block = (HERE / "araignee_style.css").read_text(encoding="utf-8")
        new_css = replace_css_block(existing_css, css_block)
        if existing_css != new_css:
            backup_path(style_path)
            style_path.write_text(new_css, encoding="utf-8")
            touched.append(style_path)
            print("✅ styles Araignée installés/mis à jour")
        else:
            print("↪ styles Araignée déjà à jour")

        # Vérification syntaxique avant de déclarer l'installation réussie.
        python_targets = [
            ROOT / "cogs/araignee_format.py",
            ROOT / "services/araignee_format_service.py",
            ROOT / "services/format_routes.py",
            ROOT / "tools/araignee_pool.py",
            ROOT / "tools/araignee_images.py",
            ROOT / "cogs/tournament.py",
            ROOT / "cogs/public_website.py",
            ROOT / "bot.py",
        ]
        for path in python_targets:
            syntax_check_python(path)

        # Validation du JSON.
        import json
        data = json.loads(
            (ROOT / "data/formats/araignee.json").read_text(encoding="utf-8")
        )
        pool = data.get("spider_card_pool") or []
        if len(pool) != 122:
            raise RuntimeError(
                f"Le pack attendu contient 122 cartes, détecté : {len(pool)}"
            )

        if not args.skip_images:
            print("\n🖼️ Synchronisation de la galerie d'images…")
            image_process = subprocess.run(
                [sys.executable, str(ROOT / "tools/araignee_images.py"), "sync"],
                cwd=ROOT,
                check=False,
            )
            if image_process.returncode != 0:
                print(
                    "⚠️ La synchronisation des images a échoué, mais le Format "
                    "Araignée reste installé. Tu peux relancer plus tard : "
                    "python3 tools/araignee_images.py sync"
                )

    except Exception as error:
        print(f"\n❌ Installation interrompue : {error}")
        print("♻️ Restauration automatique des fichiers sauvegardés…")

        # Restaurer ce qui existait.
        for backup_file in sorted(backup.rglob("*")):
            if not backup_file.is_file():
                continue
            relative = backup_file.relative_to(backup)
            destination = ROOT / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_file, destination)

        # Retirer les nouveaux fichiers qui n'existaient pas dans la sauvegarde.
        for path in touched:
            relative = path.relative_to(ROOT)
            if not (backup / relative).exists() and path.exists():
                path.unlink()

        print("✅ Dépôt restauré.")
        return 1

    print("\n✅ Installation terminée.")
    print("Pool officiel : 122 cartes")
    print("Discord : /araignee rules · pool · check · card")
    print("Site : /formats · /formats/araignee")
    print("API : /api/formats/araignee")
    print("Validation API : POST /api/formats/araignee/validate")
    print("Pool texte : /api/formats/araignee/pool.txt")
    print("Gestion du pool : python3 tools/araignee_pool.py --help")
    print("Galerie images : python3 tools/araignee_images.py status")
    print("Sauvegarde :", backup.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
