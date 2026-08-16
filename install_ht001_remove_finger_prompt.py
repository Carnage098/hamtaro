from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "web" / "templates" / "trophy_detail.html"

NEW = '        interaction-prompt="{% if trophy.id in [\'HT-001\', \'HT-002\'] %}none{% else %}auto{% endif %}"\n'

CANDIDATES = [
    '        interaction-prompt="{% if trophy.id == \'HT-002\' %}none{% else %}auto{% endif %}"\n',
    '        interaction-prompt="auto"\n',
]


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def main() -> None:
    if not TEMPLATE.exists():
        fail(
            "web/templates/trophy_detail.html est introuvable. "
            "Place ce script à la racine du dépôt Hamtaro."
        )

    text = TEMPLATE.read_text(encoding="utf-8")

    if NEW in text:
        print("✅ Le doigt animé est déjà désactivé pour HT-001 et HT-002.")
        return

    matched = None
    for candidate in CANDIDATES:
        if candidate in text:
            matched = candidate
            break

    if matched is None:
        fail(
            "Impossible de trouver une forme connue de interaction-prompt "
            "dans trophy_detail.html."
        )

    backup = TEMPLATE.with_suffix(
        TEMPLATE.suffix + ".before-ht001-no-finger.bak"
    )
    if not backup.exists():
        shutil.copy2(TEMPLATE, backup)

    text = text.replace(matched, NEW, 1)
    TEMPLATE.write_text(text, encoding="utf-8")

    print("✅ Doigt animé supprimé pour HT-001 et HT-002.")
    print("✅ Les autres trophées gardent leur comportement actuel.")
    print("✅ Déplacement manuel, zoom et rotation restent disponibles.")
    print(f"✅ Sauvegarde : {backup.relative_to(ROOT)}")
    print()
    print("Puis lance :")
    print("  git add web/templates/trophy_detail.html")
    print('  git commit -m "fix: remove interaction prompt from HT-001 and HT-002"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
