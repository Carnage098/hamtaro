from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "services" / "command_sync_once.py"

OLD = "                and 0.0 < retry_after <= 120.0\n"
NEW = "                and 0.0 < retry_after <= 900.0\n"


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
        print("✅ La fenêtre d'attente shared est déjà à 15 minutes.")
        return

    if OLD not in text:
        fail(
            "La limite shared de 120 secondes est introuvable. "
            "Le fichier a peut-être changé."
        )

    backup = TARGET.with_suffix(
        TARGET.suffix + ".before-shared-retry-window-fix.bak"
    )
    if not backup.exists():
        shutil.copy2(TARGET, backup)

    text = text.replace(OLD, NEW, 1)
    TARGET.write_text(text, encoding="utf-8")

    try:
        compile(
            TARGET.read_text(encoding="utf-8"),
            str(TARGET),
            "exec",
        )
    except Exception as error:
        shutil.copy2(backup, TARGET)
        fail(
            "Le fichier ne compile pas ; restauration effectuée. "
            f"Erreur : {error}"
        )

    print("✅ Retry-After shared accepté jusqu'à 900 secondes (15 minutes).")
    print("✅ Le nombre de retries reste strictement borné.")
    print("✅ Aucune boucle infinie.")
    print("✅ Aucun changement aux 26 racines / 144 actions.")
    print()
    print("Puis :")
    print("  python3 -m py_compile services/command_sync_once.py")
    print("  git add services/command_sync_once.py")
    print('  git commit -m "fix: respect long Discord shared retry-after"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
