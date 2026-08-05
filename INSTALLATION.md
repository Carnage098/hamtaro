# Installation des correctifs Hamtaro

## 1. Décompresser l'archive

Garde le dossier de correctifs à côté de ton dépôt GitHub local.

Exemple :

```text
Projets/
├── hamtaro/
└── hamtaro_correctifs_2026-08-05/
```

## 2. Appliquer les modifications

Depuis un terminal :

```bash
python3 hamtaro_correctifs_2026-08-05/apply_fixes.py hamtaro
```

Sur Windows, la commande peut être :

```powershell
py hamtaro_correctifs_2026-08-05\apply_fixes.py hamtaro
```

Le script :

- sauvegarde chaque fichier remplacé dans `audit_backup_DATE-HEURE/` ;
- modifie uniquement les motifs audités ;
- refuse de continuer si le dépôt a trop changé ;
- ne supprime pas ton `.env` local ;
- retire `.env`, les bases et les caches de l'index Git lorsqu'ils étaient suivis.

## 3. Contrôler le résultat

Dans le dépôt Hamtaro :

```bash
cd hamtaro
python3 -m pip install -r requirements-dev.txt
python3 -m compileall -q .
python3 scripts/preflight.py
python3 -m pytest -q
git status
git diff
```

## 4. Enregistrer sur GitHub

Après lecture du diff :

```bash
git add -A
git commit -m "Correctifs audit Hamtaro"
git push
```

Railway redéploiera ensuite la branche configurée.

## 5. Variables Railway recommandées

```env
ENABLE_MEMBERS_INTENT=true
ENABLE_MESSAGE_CONTENT=false
SYNC_GUILD_COMMANDS=true
SYNC_GLOBAL_COMMANDS=false
FAIL_ON_COG_ERROR=true
WEBSITE_ENABLED=true
SQLITE_BUSY_TIMEOUT_MS=30000
PROFESSIONAL_TOOLS_ENABLED=true
STAFF_DASHBOARD_ENABLED=false
```

Il faut aussi conserver `DISCORD_TOKEN`, `GUILD_ID`, `WEBSITE_BASE_URL` et les variables de volume déjà utilisées par le projet.

## 6. Vérification Discord après déploiement

1. Vérifie que le bot démarre sans erreur SQLite.
2. Lance `/hamtaro_doctor`.
3. Lance `/hamtaro_test`.
4. Crée un tournoi de test.
5. Vérifie une inscription, un signalement, un rejet puis une validation de résultat.
6. Vérifie `/tournaments` et `/health` sur le site.
7. Vérifie que `/staff_dashboard` n'apparaît plus après synchronisation.

## Restauration

Chaque fichier d'origine modifié est copié dans le dossier `audit_backup_DATE-HEURE/` créé à la racine du dépôt. Pour annuler rapidement avant un commit, Git permet aussi :

```bash
git restore .
git clean -fd
```

Attention : `git clean -fd` supprime les nouveaux fichiers non suivis. Consulte toujours `git status` avant de l'utiliser.
