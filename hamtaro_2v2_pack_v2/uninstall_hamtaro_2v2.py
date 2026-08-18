#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


def main() -> None:
    root = Path.cwd().resolve()
    backup_root = root / "upgrade_backup"
    candidates = sorted(
        [p for p in backup_root.glob("team_2v2_native_*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(
            "❌ Aucune sauvegarde team_2v2_native_* trouvée. "
            "Restauration automatique impossible."
        )

    backup = candidates[0]
    mapping = {
        "bot.py": root / "bot.py",
        "tournament.py": root / "cogs" / "tournament.py",
        "registration.py": root / "cogs" / "registration.py",
        "swiss.py": root / "cogs" / "swiss.py",
    }
    for name, target in mapping.items():
        source = backup / name
        if not source.exists():
            raise SystemExit(f"❌ Sauvegarde incomplète : {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for relative in (
        "cogs/team_2v2.py",
        "services/team_2v2_service.py",
        "tests/test_team_2v2_service.py",
    ):
        path = root / relative
        if path.exists():
            path.unlink()

    print(f"✅ Hamtaro restauré depuis : {backup}")
    print("✅ Intégration native 2v2 retirée du code.")
    print("ℹ️ Les tables SQLite duo_* sont conservées pour éviter une perte de données.")


if __name__ == "__main__":
    main()
