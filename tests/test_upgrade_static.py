from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_files_parse() -> None:
    files = (
        ROOT / "bot.py",
        ROOT / "config.py",
        ROOT / "database.py",
        ROOT / "services" / "database_maintenance.py",
        ROOT / "utils" / "runtime_lock.py",
        ROOT / "cogs" / "system_health.py",
    )
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_secret_file() -> None:
    assert not (ROOT / ".env").exists()


def test_capacity_128_is_present() -> None:
    installer = (ROOT / "apply_hamtaro_upgrade.py").read_text(encoding="utf-8")
    assert "64, 128" in installer


def test_auto_refresh_is_present() -> None:
    app_js = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "refreshTournamentLists" in app_js
    assert 'data-tournament-list="open"' in app_js
