# Hamtaro — Professional Tournament Suite

Hamtaro est le système de tournois Yu-Gi-Oh! du serveur Fun Row. Cette version renforce le projet existant sans supprimer ses commandes, ses brackets, ses rondes suisses ni son site public.

## Fonctions principales

- tournois à élimination directe et rondes suisses ;
- inscriptions jusqu'à **128 joueurs** ;
- résultats envoyés par les joueurs puis validés par le staff ;
- garde-fous SQLite contre les gagnants invalides, scores négatifs et doubles joueurs ;
- annulation sécurisée déjà intégrée au projet, avec journal unifié ;
- menu `/hamtaro` adapté à l'état réel du joueur ;
- diagnostic `/hamtaro_doctor` ;
- test complet non persistant `/hamtaro_test` ;
- journal `/audit_history` ;
- nettoyage prudent `/hamtaro_cleanup` ;
- tableau de bord staff protégé sur `/staff` ;
- site actualisé automatiquement, recherche de tournois et affichage mobile ;
- tests automatiques GitHub Actions ;
- stockage SQLite persistant sur un volume Railway.

## Installation

À la racine du dépôt Hamtaro :

```bash
python /chemin/vers/hamtaro_professional_suite/apply_hamtaro_upgrade.py
python -m compileall .
pip install -r requirements.txt
python scripts/preflight.py
python -m pytest -q
```

Puis :

```bash
git add .
git commit -m "Hamtaro professional suite"
git push
```

L'installateur conserve une copie des fichiers remplacés dans `upgrade_backup/`.

## Railway

Conserve exactement :

- un seul service Hamtaro ;
- un seul réplica ;
- un volume monté sur `/data` ;
- `SYNC_GUILD_COMMANDS=true` ;
- `SYNC_GLOBAL_COMMANDS=false` hors publication globale.

Variables importantes :

```env
WEBSITE_ENABLED=true
WEBSITE_BASE_URL=https://ton-site.up.railway.app
PROFESSIONAL_TOOLS_ENABLED=true
STAFF_DASHBOARD_ENABLED=true
STAFF_DASHBOARD_TOKEN=une-valeur-aleatoire-tres-longue
DATABASE_BACKUPS_ENABLED=true
DATABASE_BACKUP_INTERVAL_HOURS=12
SQLITE_BUSY_TIMEOUT_MS=30000
DEBUG_INTERACTIONS=false
FAIL_ON_COG_ERROR=true
```

Railway fournit `RAILWAY_VOLUME_MOUNT_PATH` lorsque le volume est attaché. Avec `/data`, la base devient `/data/database.db`.

## Commandes professionnelles

### `/hamtaro_doctor`

Contrôle la base, le volume, les permissions, les salons, les cogs, le site, les tournois bloqués et les matchs incohérents.

### `/hamtaro_test`

Crée dans une transaction temporaire un tournoi de quatre joueurs, simule le bracket, les demi-finales, la finale et la clôture, puis annule toutes les données fictives.

### `/audit_history`

Affiche les dernières validations, annulations, opérations web et actions professionnelles enregistrées.

### `/hamtaro_cleanup`

Supprime uniquement les références orphelines après une confirmation explicite. Aucun tournoi valide n'est supprimé.

### `/staff_dashboard`

Donne au staff le lien vers `/staff`. Le tableau de bord est protégé par un jeton Railway, une session `HttpOnly`, un contrôle des tentatives et des en-têtes de sécurité. Les validations sensibles restent volontairement dans Discord afin de conserver l'identité du modérateur et les confirmations existantes.

## Vérification après déploiement

1. Lance `/hamtaro_doctor`.
2. Lance `/hamtaro_test`.
3. Crée un tournoi de quatre joueurs.
4. Teste inscription, lancement, rejet, validation, finale et annulation.
5. Vérifie `/staff`, `/tournaments` et `/health`.
6. Redéploie Railway puis vérifie que le tournoi existe toujours.

## Choix volontairement exclus

Cette version n'ajoute pas :

- la restauration complète de sauvegardes depuis Discord ;
- une gestion complexe des absences, preuves de contact et prolongations.

Les sauvegardes automatiques essentielles et les forfaits manuels existants restent conservés.
