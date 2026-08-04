# Installation de la mise à niveau

## Méthode automatique

1. Télécharge et décompresse le pack.
2. Copie le dossier décompressé dans un emplacement séparé du dépôt.
3. Ouvre un terminal à la racine de ton dépôt Hamtaro.
4. Exécute l'installateur en indiquant son chemin :

```bash
python /chemin/vers/hamtaro_production_upgrade/apply_hamtaro_upgrade.py
```

L'installateur :

- sauvegarde les anciens fichiers dans `upgrade_backup/` ;
- remplace les fichiers principaux ;
- ajoute les modules de maintenance et de santé ;
- corrige la capacité de 128 participants ;
- corrige le démarrage du tournoi à la ronde 1 ;
- ajoute un timeout SQLite ;
- déplace les anciens fichiers dans `legacy/` ;
- déplace `.env` hors du nom suivi par Git.

## Après l'installation

```bash
python -m compileall .
pip install -r requirements.txt
python scripts/preflight.py
git add .
git commit -m "Production hardening Hamtaro"
git push
```

Sur Railway, vérifie :

- un seul service Hamtaro ;
- un seul réplica ;
- un volume monté sur `/data` ;
- `GUILD_ID` configuré ;
- `SYNC_GUILD_COMMANDS=true` ;
- `SYNC_GLOBAL_COMMANDS=false` hors publication globale.

## Premier démarrage

Un volume neuf crée une base vide. Après le déploiement :

1. utilise `/hamtaro_health` ;
2. crée un tournoi `Test Persistance` ;
3. redéploie ;
4. vérifie `/tournament_list` ;
5. crée une sauvegarde avec `/hamtaro_backup`.
