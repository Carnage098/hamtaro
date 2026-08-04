from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_professional_modules_exist() -> None:
    required = [
        "cogs/professional_web.py",
        "cogs/professional_tools.py",
        "services/integrity_service.py",
        "services/self_test_service.py",
        "services/audit_service.py",
        "services/audit_compatibility.py",
        "services/staff_dashboard_service.py",
        "web/templates/staff_dashboard.html",
        ".github/workflows/quality.yml",
    ]
    assert all((ROOT / path).exists() for path in required)


def test_database_has_result_guards() -> None:
    source = (ROOT / "database.py").read_text(encoding="utf-8")
    assert "trg_match_winner_is_participant" in source
    assert "trg_match_players_distinct_insert" in source
    assert "trg_result_request_status_update" in source
    assert "4, 8, 16, 32, 64, 128" in source


def test_bot_loads_professional_extensions_in_safe_order() -> None:
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    web_patch = source.index('"cogs.professional_web"')
    public_site = source.index('"cogs.public_website"')
    tools = source.index('"cogs.professional_tools"')
    assert web_patch < public_site < tools


def test_no_real_env_file_in_pack() -> None:
    assert not (ROOT / ".env").exists()
    assert (ROOT / ".env.example").exists()


def test_dashboard_cookie_is_http_only_and_strict() -> None:
    source = (ROOT / "cogs/professional_web.py").read_text(encoding="utf-8")
    assert "httponly=True" in source
    assert 'samesite="Strict"' in source
    assert "hmac.compare_digest" in source
    assert "_LOGIN_MAX_ATTEMPTS" in source
