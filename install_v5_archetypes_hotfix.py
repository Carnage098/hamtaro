from __future__ import annotations

from pathlib import Path
import shutil
import time
import py_compile
import re

IMPORT_LINE = "from services.archetype_web_routes import register_archetype_routes"
SITE_IMPORT = "from services.site_experience_routes import register_site_experience_routes"

def find_repo_root(start: Path) -> Path:
    script_dir = Path(__file__).resolve().parent
    candidates = [start, *start.parents, script_dir, *script_dir.parents]
    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "bot.py").exists() and (candidate / "cogs" / "public_website.py").exists():
            return candidate
    raise SystemExit("❌ Racine Hamtaro introuvable. Lance ce script depuis le dossier contenant bot.py.")

def backup(path: Path, backup_root: Path, repo: Path) -> None:
    target = backup_root / path.relative_to(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)

def patch_import(lines: list[str]) -> bool:
    if any(line.strip() == IMPORT_LINE for line in lines):
        return False
    for i, line in enumerate(lines):
        if line.strip() == SITE_IMPORT:
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines.insert(i + 1, IMPORT_LINE + newline)
            return True
    raise SystemExit("❌ Import register_site_experience_routes introuvable dans public_website.py.")

def find_call_end(lines: list[str], start_index: int) -> int:
    depth = 0
    started = False
    for i in range(start_index, len(lines)):
        line = lines[i]
        for ch in line:
            if ch == '(':
                depth += 1
                started = True
            elif ch == ')' and started:
                depth -= 1
                if depth == 0:
                    return i
    raise SystemExit("❌ Impossible de déterminer la fin de register_site_experience_routes(...).")

def patch_route_call(lines: list[str]) -> bool:
    if any(re.match(r"^\s*register_archetype_routes\s*\(", line) for line in lines):
        return False
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*register_site_experience_routes\s*\(", line):
            start = i
            break
    if start is None:
        raise SystemExit("❌ Appel register_site_experience_routes(...) introuvable.")
    end = find_call_end(lines, start)
    indent = re.match(r"^(\s*)", lines[start]).group(1)
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    block = [
        f"{indent}register_archetype_routes({newline}",
        f"{indent}    application,{newline}",
        f"{indent}    self,{newline}",
        f"{indent}){newline}",
    ]
    lines[end + 1:end + 1] = block
    return True

def patch_public_website(path: Path) -> bool:
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    changed = patch_import(lines)
    changed = patch_route_call(lines) or changed
    text = ''.join(lines)
    call_pos = text.find('register_archetype_routes(')
    runner_pos = text.find('web.AppRunner(')
    if call_pos < 0:
        raise SystemExit("❌ L'appel register_archetype_routes n'a pas été ajouté.")
    if runner_pos >= 0 and call_pos > runner_pos:
        raise SystemExit("❌ register_archetype_routes est placé après web.AppRunner(...).")
    if changed:
        path.write_text(text, encoding='utf-8')
    return changed

def patch_base(path: Path) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    if any('href="/archetypes"' in line for line in lines):
        return False
    for i, line in enumerate(lines):
        if 'href="/decks"' in line:
            indent = re.match(r"^(\s*)", line).group(1)
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines.insert(i+1, f'{indent}<a href="/archetypes">Archétypes</a>{newline}')
            path.write_text(''.join(lines), encoding='utf-8')
            return True
    return False

def verify(repo: Path) -> list[str]:
    errors=[]
    public=repo/'cogs'/'public_website.py'
    text=public.read_text(encoding='utf-8')
    if IMPORT_LINE not in text: errors.append('import register_archetype_routes absent')
    if not re.search(r"(?m)^\s*register_archetype_routes\s*\(", text): errors.append('appel register_archetype_routes absent')
    if text.find('register_archetype_routes(') > text.find('web.AppRunner(') >= 0: errors.append('route enregistrée après AppRunner')
    required=[
        'services/archetype_web_routes.py','services/archetype_meta_service.py','cogs/archetype_artworks.py',
        'web/templates/archetypes.html','web/templates/archetype_detail.html','web/static/archetypes.css',
        'web/data/archetype_artworks.json'
    ]
    for rel in required:
        if not (repo/rel).exists(): errors.append(f'fichier manquant : {rel}')
    try: py_compile.compile(str(public), doraise=True)
    except Exception as exc: errors.append(f'public_website.py ne compile pas : {exc}')
    routes=repo/'services'/'archetype_web_routes.py'
    if routes.exists():
        rt=routes.read_text(encoding='utf-8')
        for route in ['/archetypes','/api/archetypes']:
            if route not in rt: errors.append(f'route attendue absente : {route}')
    return errors

def main() -> int:
    repo=find_repo_root(Path.cwd())
    print(f'🐹 Dépôt Hamtaro détecté : {repo}')
    public=repo/'cogs'/'public_website.py'
    base=repo/'web'/'templates'/'base.html'
    stamp=time.strftime('%Y%m%d_%H%M%S')
    backup_root=repo/'.hamtaro_v5_backup'/stamp
    backup(public, backup_root, repo)
    if base.exists(): backup(base, backup_root, repo)
    public_changed=patch_public_website(public)
    nav_changed=patch_base(base)
    errors=verify(repo)
    if errors:
        print('\n❌ Vérification V5 échouée :')
        for e in errors: print('  -',e)
        print('\nSauvegarde :',backup_root)
        return 1
    print('\n✅ HOTFIX V5 installé correctement.')
    print('  public_website.py :', 'modifié' if public_changed else 'déjà correct')
    print('  base.html          :', 'modifié' if nav_changed else 'déjà correct / inchangé')
    print('  sauvegarde         :', backup_root)
    print('\nAprès redéploiement Railway, cherche :')
    print('Routes Méta/Archétypes enregistrées : /archetypes, /archetypes/<slug>, /api/archetypes')
    print('\nPuis ouvre : https://hamtaro-production.up.railway.app/archetypes')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
