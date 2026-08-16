from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "services" / "command_sync_once.py"

HELPER = '\ndef _rate_limit_diagnostics(response, body, raw_text: str) -> dict[str, object]:\n    header_names = (\n        "X-RateLimit-Limit",\n        "X-RateLimit-Remaining",\n        "X-RateLimit-Reset",\n        "X-RateLimit-Reset-After",\n        "X-RateLimit-Bucket",\n        "X-RateLimit-Scope",\n        "Retry-After",\n        "Date",\n        "Via",\n        "CF-Ray",\n    )\n\n    headers = {\n        name: response.headers.get(name)\n        for name in header_names\n        if response.headers.get(name) is not None\n    }\n\n    return {\n        "status": response.status,\n        "headers": headers,\n        "body": body if body else raw_text[:2000],\n    }\n\n\ndef _log_rate_limit_diagnostics(response, body, raw_text: str) -> None:\n    import json as _json\n\n    diagnostics = _rate_limit_diagnostics(\n        response,\n        body,\n        raw_text,\n    )\n\n    LOGGER.error("━━━━━━━━ DISCORD RATE LIMIT DIAGNOSTIC ━━━━━━━━")\n    LOGGER.error("HTTP status              : %s", diagnostics["status"])\n\n    headers = diagnostics["headers"]\n\n    for key in (\n        "X-RateLimit-Scope",\n        "X-RateLimit-Bucket",\n        "X-RateLimit-Limit",\n        "X-RateLimit-Remaining",\n        "X-RateLimit-Reset",\n        "X-RateLimit-Reset-After",\n        "Retry-After",\n        "Date",\n        "Via",\n        "CF-Ray",\n    ):\n        LOGGER.error(\n            "%-24s : %s",\n            key,\n            headers.get(key, "<absent>"),\n        )\n\n    try:\n        body_text = _json.dumps(\n            diagnostics["body"],\n            ensure_ascii=False,\n            sort_keys=True,\n        )\n    except Exception:\n        body_text = repr(diagnostics["body"])\n\n    LOGGER.error(\n        "Discord response body    : %s",\n        body_text[:3000],\n    )\n    LOGGER.error("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")\n'
CALL_BLOCK = '                    _log_rate_limit_diagnostics(\n                        response,\n                        body,\n                        raw_text,\n                    )\n\n'


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def main() -> None:
    if not TARGET.exists():
        fail(
            "services/command_sync_once.py est introuvable. "
            "Place ce script à la racine du dépôt Hamtaro."
        )

    text = TARGET.read_text(encoding="utf-8")

    already_has_helper = "def _log_rate_limit_diagnostics(" in text
    already_has_call = (
        "_log_rate_limit_diagnostics(\n"
        "                        response,\n"
        "                        body,\n"
        "                        raw_text,"
    ) in text

    if already_has_helper and already_has_call:
        print("✅ Le diagnostic détaillé des 429 est déjà installé.")
        return

    backup = TARGET.with_suffix(
        TARGET.suffix + ".before-ratelimit-diagnostics.bak"
    )
    if not backup.exists():
        shutil.copy2(TARGET, backup)

    if not already_has_helper:
        publish_marker = "async def publish_application_commands_once(\n"
        idx = text.find(publish_marker)

        if idx == -1:
            fail(
                "publish_application_commands_once() est introuvable."
            )

        text = (
            text[:idx]
            + HELPER.strip()
            + "\n\n\n"
            + text[idx:]
        )

    if not already_has_call:
        marker = "                if response.status == 429:\n"

        if marker not in text:
            fail("La branche HTTP 429 est introuvable.")

        text = text.replace(
            marker,
            marker + CALL_BLOCK,
            1,
        )

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
            "Le fichier modifié ne compile pas ; restauration effectuée. "
            f"Erreur : {error}"
        )

    print("✅ Diagnostic Discord 429 installé.")
    print("✅ Le comportement ONE-SHOT n'est pas modifié.")
    print("✅ Aucun retry supplémentaire n'est ajouté.")
    print("✅ Aucun token ni header Authorization n'est affiché.")
    print()
    print("Le prochain 429 affichera :")
    print("  X-RateLimit-Scope")
    print("  X-RateLimit-Bucket")
    print("  X-RateLimit-Limit")
    print("  X-RateLimit-Remaining")
    print("  X-RateLimit-Reset")
    print("  X-RateLimit-Reset-After")
    print("  Retry-After")
    print("  Date / Via / CF-Ray")
    print("  + le corps JSON de la réponse Discord")
    print()
    print("Puis :")
    print("  python3 -m py_compile services/command_sync_once.py")
    print("  git add services/command_sync_once.py")
    print('  git commit -m "debug: log Discord command rate-limit headers"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
