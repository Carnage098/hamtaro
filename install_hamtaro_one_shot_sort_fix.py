from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "services" / "command_sync_once.py"

OLD = '    commands.sort(key=lambda command: (int(command.type.value), command.name))\n'
NEW = '    commands.sort(key=lambda command: command.name)\n'


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def main() -> None:
    if not TARGET.exists():
        fail(
            "services/command_sync_once.py est introuvable. "
            "Place ce script à la racine du dépôt Hamtaro."
        )

    text = TARGET.read_text(encoding="utf-8")

    if NEW in text and OLD not in text:
        print("✅ Le correctif de tri est déjà installé.")
        return

    if OLD not in text:
        fail(
            "La ligne de tri attendue est introuvable dans "
            "services/command_sync_once.py."
        )

    backup = TARGET.with_suffix(
        TARGET.suffix + ".before-sort-fix.bak"
    )
    if not backup.exists():
        shutil.copy2(TARGET, backup)

    text = text.replace(OLD, NEW, 1)
    TARGET.write_text(text, encoding="utf-8")

    # Validation syntaxique sans créer de __pycache__.
    compile(
        TARGET.read_text(encoding="utf-8"),
        str(TARGET),
        "exec",
    )

    print("✅ Bug command.type.value corrigé.")
    print("✅ Les commandes sont maintenant triées uniquement par nom.")
    print("✅ Aucun changement au système ONE-SHOT / anti-retry.")
    print(f"✅ Sauvegarde : {backup.relative_to(ROOT)}")
    print()
    print("Puis :")
    print("  python3 -m py_compile services/command_sync_once.py")
    print("  git add services/command_sync_once.py")
    print('  git commit -m "fix: handle grouped commands in one-shot sync"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
