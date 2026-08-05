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
        ROOT / "services" / "database_service.py",
        ROOT / "utils" / "runtime_lock.py",
        ROOT / "cogs" / "system_health.py",
        ROOT / "cogs" / "professional_tools.py",
    )
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_local_secrets_are_not_versioned_by_default() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert (ROOT / ".env.example").exists()


def test_capacity_128_is_present_in_runtime_service() -> None:
    source = (ROOT / "services" / "database_service.py").read_text(encoding="utf-8")
    assert "(4, 8, 16, 32, 64, 128)" in source
    assert "32, 64 ou 128 joueurs" in source


def test_player_profile_timestamp_is_migrated() -> None:
    schema = (ROOT / "database.py").read_text(encoding="utf-8")
    service = (ROOT / "services" / "database_service.py").read_text(encoding="utf-8")
    assert '"players", "updated_at"' in schema
    assert "updated_at = CURRENT_TIMESTAMP" in service


def test_auto_refresh_is_present() -> None:
    app_js = (ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "refreshTournamentLists" in app_js
    assert 'data-tournament-list="open"' in app_js
