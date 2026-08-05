# Audit ciblé du dépôt Hamtaro

Dépôt analysé : `Carnage098/hamtaro`, branche `main`  
Date de l'audit : 5 août 2026

## Résultat général

Le cœur du projet est déjà bien plus solide qu'un simple prototype : séparation en cogs et services, migrations SQLite, sauvegardes, verrou d'instance, watchdog, commandes de diagnostic et site public. Je n'ai donc pas remplacé l'architecture existante.

Le correctif se concentre sur des incohérences réelles qui peuvent provoquer des erreurs en production ou faire échouer les tests.

## Problèmes corrigés

### 1. La capacité de 128 joueurs était annoncée mais refusée à l'exécution

- Le README annonce 128 joueurs.
- Le schéma SQLite et le moteur de bracket acceptent 128.
- `DatabaseService.create_tournament()` refusait pourtant toute valeur supérieure à 64.

**Correction :** ajout de 128 dans la validation du service et dans son message d'erreur.

### 2. `players.updated_at` était utilisée sans exister dans le schéma

`update_player_profile()` exécute :

```sql
updated_at = CURRENT_TIMESTAMP
```

Mais la table `players` et les migrations ne créaient pas cette colonne. Toute utilisation de cette méthode pouvait produire une erreur SQLite du type `no such column: updated_at`.

**Correction :**

- version de base passée de 9 à 10 ;
- migration de `players.updated_at` pour les bases Railway existantes ;
- colonne ajoutée aux nouvelles bases ;
- actualisation également faite lors d'un `upsert` du profil.

### 3. Le délai SQLite configuré n'était pas appliqué à la connexion principale

`SQLITE_BUSY_TIMEOUT_MS` existe dans `config.py`, mais `DatabaseService` ouvrait sa connexion sans le transmettre et sans définir `PRAGMA busy_timeout`.

**Correction :** timeout appliqué à `aiosqlite.connect()` et à SQLite. Cela réduit les erreurs `database is locked` lors d'accès rapprochés.

### 4. La page staff était incohérente et déjà abandonnée

- `/staff_dashboard` envoyait un bouton vers `/staff`.
- Le serveur actuel de `public_website.py` n'enregistre aucune route `/staff` et précise qu'il n'ajoute aucune administration web.
- Des templates, services et installateurs de l'ancien tableau restaient pourtant dans le dépôt.

**Correction :** suppression de la commande morte et des fichiers exclusivement liés à cette page, tout en conservant les outils Discord utiles :

- `/hamtaro_doctor` ;
- `/hamtaro_test` ;
- `/audit_history` ;
- `/hamtaro_cleanup`.

### 5. Le fichier d'exclusion Git portait le mauvais nom

Le dépôt contient `gitignore` au lieu de `.gitignore`. Git n'applique donc pas ses règles, ce qui explique la présence de `.env` et de fichiers `__pycache__` dans le dépôt.

**Correction :** création du vrai `.gitignore`, ajout d'un `.env.example`, retrait de l'index Git des secrets et fichiers générés sans les supprimer du disque local.

Le `.env` visible sur GitHub contient seulement le placeholder `TON_TOKEN_ICI`. Aucun vrai jeton n'a été repéré dans ce fichier. Il reste néanmoins préférable de ne jamais versionner un `.env`.

### 6. Les tests ne correspondaient plus au code actuel

Les tests exigeaient notamment :

- `cogs/professional_web.py`, absent du dépôt actif ;
- une route et des templates `/staff` abandonnés ;
- l'absence physique de `.env`, même lorsqu'il est simplement local et ignoré ;
- un ordre de cogs qui ne correspond pas à `bot.py`.

Ils pouvaient donc échouer même sans panne du bot.

**Correction :** remplacement des deux tests statiques par des contrôles correspondant au projet actuel et ajout d'un workflow GitHub Actions exécutable.

### 7. Deux variables décimales Railway pouvaient bloquer tout le démarrage

`EVENT_LOOP_WATCHDOG_INTERVAL` et `EVENT_LOOP_WARNING_SECONDS` utilisaient directement `float(os.getenv(...))`. Une faute de saisie dans Railway provoquait une exception pendant l'import de `config.py`.

**Correction :** fonction `env_float()` avec valeur de repli et bornes.

### 8. L'intent Discord Members était forcé

`bot.py` imposait `intents.members = True`, tandis que l'intent Message Content était déjà configurable.

**Correction :** ajout de `ENABLE_MEMBERS_INTENT`. La valeur par défaut reste `true` pour ne pas modifier le comportement actuel, mais elle peut être désactivée si nécessaire.

## Ancien installateur retiré

`apply_hamtaro_upgrade.py` était un ancien paquet d'installation déjà appliqué. Le relancer pouvait :

- réintroduire le tableau staff abandonné ;
- réécrire de nombreux fichiers actifs ;
- modifier `current_round` d'une manière incompatible avec le système de rounds inversés du bracket.

Il est sauvegardé puis retiré par le correctif.

## Points vérifiés et volontairement non modifiés

### Numérotation des rounds d'élimination directe

Le moteur utilise volontairement :

- round 1 = finale ;
- numéro le plus élevé = premier tour.

Par conséquent, initialiser `current_round` avec `total_rounds` est correct. Le correctif ne change pas ce comportement.

### Mise à jour de la version SQLite

La version enregistrée dans `metadata` est bien mise à jour à la fin de `init_db()`. Une première suspicion sur ce point a été écartée après lecture complète du fichier.

### Synchronisation des commandes Discord

La version actuelle de `bot.py` respecte déjà `SYNC_GUILD_COMMANDS` et `SYNC_GLOBAL_COMMANDS`. Aucun remplacement simplifié du bot n'a été effectué.

## Fichiers modifiés par l'installateur

- `bot.py`
- `config.py`
- `database.py`
- `services/database_service.py`
- `cogs/professional_tools.py`
- `README.md`
- `tests/test_professional_suite.py`
- `tests/test_upgrade_static.py`

## Fichiers ajoutés

- `.gitignore`
- `.env.example`
- `requirements-dev.txt`
- `.github/workflows/tests.yml`

## Fichiers obsolètes retirés

- `gitignore`
- `apply_hamtaro_upgrade.py`
- `apply_integrated_staff_dashboard.py`
- `install_staff_dashboard_fix.py`
- `installer_staff_hamtaro.py`
- `cogs/professional_web.py`, s'il existe encore localement
- `services/staff_dashboard_routes.py`, s'il existe encore localement
- `services/staff_dashboard_service.py`
- `web/templates/staff_dashboard.html`
- `web/templates/staff_login.html`
- `web/static/staff_dashboard.js`

## Limites de l'audit

L'environnement d'analyse n'a pas permis de cloner directement l'intégralité du dépôt ni de lancer le bot connecté à Discord/Railway. L'analyse a été faite à partir des fichiers publics GitHub et des incohérences croisées entre code, schéma, tests et documentation.

L'installateur a cependant été testé localement sur un dépôt simulé :

- syntaxe Python vérifiée ;
- application complète vérifiée ;
- seconde exécution idempotente ;
- sauvegardes vérifiées ;
- suppression des anciens fichiers vérifiée.
