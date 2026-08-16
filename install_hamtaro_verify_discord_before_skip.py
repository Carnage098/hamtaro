from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "services" / "command_sync_once.py"
NEEDLE = "Arbre Discord inchangé et déjà synchronisé"


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def contains_needle(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if NEEDLE in child.value:
                return True
    return False


def main() -> None:
    if not TARGET.exists():
        fail(
            "services/command_sync_once.py est introuvable. "
            "Place ce script à la racine du dépôt Hamtaro."
        )

    original = TARGET.read_text(encoding="utf-8")

    marker = "STATE-CACHE EARLY RETURN DISABLED"
    if marker in original:
        print("✅ Le correctif de vérification Discord est déjà installé.")
        return

    try:
        tree = ast.parse(original)
    except SyntaxError as exc:
        fail(f"Le fichier source ne compile déjà pas : {exc}")

    target_if = None
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and contains_needle(node):
            target_if = node
            break

    if target_if is None:
        fail(
            "Impossible de trouver le bloc de cache qui affiche "
            "'Arbre Discord inchangé et déjà synchronisé'. "
            "Aucune modification effectuée."
        )

    if not getattr(target_if, "end_lineno", None):
        fail("Python n'a pas fourni end_lineno pour le bloc à retirer.")

    lines = original.splitlines(keepends=True)
    start = target_if.lineno - 1
    end = target_if.end_lineno

    first_line = lines[start]
    indent = first_line[: len(first_line) - len(first_line.lstrip())]

    replacement = [
        f"{indent}# STATE-CACHE EARLY RETURN DISABLED\n",
        f"{indent}# Toujours vérifier l'état réel des commandes sur Discord avant de décider de ne rien faire.\n",
    ]

    patched = "".join(lines[:start] + replacement + lines[end:])

    backup = TARGET.with_suffix(
        TARGET.suffix + ".before-discord-verification-fix.bak"
    )
    if not backup.exists():
        shutil.copy2(TARGET, backup)

    try:
        compile(patched, str(TARGET), "exec")
    except Exception as exc:
        fail(
            "Le correctif généré ne compile pas. "
            f"Aucune modification écrite. Erreur : {exc}"
        )

    TARGET.write_text(patched, encoding="utf-8")

    print("✅ Faux 'déjà synchronisé' supprimé.")
    print("✅ Hamtaro fera désormais un GET Discord avant de sauter la restauration.")
    print("✅ Si Discord a moins de 26 racines, le mode restauration reprend.")
    print("✅ Si Discord a déjà 26 racines, aucune création manquante ne sera envoyée.")
    print("✅ Aucun changement aux 26 racines / 144 actions.")
    print()
    print("Puis :")
    print("  python3 -m py_compile services/command_sync_once.py")
    print("  git add services/command_sync_once.py")
    print('  git commit -m "fix: verify Discord state before skipping command recovery"')
    print("  git pull --rebase origin main")
    print("  git push origin main")


if __name__ == "__main__":
    main()
