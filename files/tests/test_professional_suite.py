from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_professional_discord_modules_exist() -> None:
    required = [
        "cogs/professional_tools.py",
        "services/integrity_service.py",
        "services/self_test_service.py",
        "services/audit_service.py",
        "services/audit_compatibility.py",
        ".github/workflows/tests.yml",
    ]
    assert all((ROOT / path).exists() for path in required)


def test_database_has_result_guards() -> None:
    source = (ROOT / "database.py").read_text(encoding="utf-8")
    assert "trg_match_winner_is_participant" in source
    assert "trg_match_players_distinct_insert" in source
    assert "trg_result_request_status_update" in source
    assert "4, 8, 16, 32, 64, 128" in source
    assert '"players", "updated_at"' in source


def test_bot_loads_public_site_and_diagnostic_tools() -> None:
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert '"cogs.public_website"' in source
    assert '"cogs.professional_tools"' in source
    assert '"cogs.professional_web"' not in source


def test_staff_dashboard_was_removed() -> None:
    source = (ROOT / "cogs" / "professional_tools.py").read_text(encoding="utf-8")
    assert 'name="staff_dashboard"' not in source
    assert not (ROOT / "web" / "templates" / "staff_dashboard.html").exists()
    assert not (ROOT / "web" / "templates" / "staff_login.html").exists()
    assert not (ROOT / "web" / "static" / "staff_dashboard.js").exists()


def test_secret_files_are_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "__pycache__/" in gitignore
    assert (ROOT / ".env.example").exists()
