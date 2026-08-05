# Hamtaro — gestion de tournois Yu-Gi-Oh!

Hamtaro est un bot Discord de gestion de tournois individuels avec :

- inscriptions et profils joueurs ;
- élimination directe et rondes suisses ;
- signalement puis validation des résultats ;
- brackets, classements, statistiques et historique ;
- sélection de plusieurs tournois par code et par salon ;
- site public synchronisé avec la base SQLite ;
- stockage persistant, sauvegardes automatiques et contrôle d'intégrité.

## Installation rapide

1. Monte un volume Railway sur le service Hamtaro avec le chemin `/data`.
2. Configure les variables à partir de `.env.example`.
3. Conserve un seul service et un seul réplica utilisant le token Discord.
4. Installe les dépendances :

```bash
pip install -r requirements.txt
```

5. Vérifie le projet :

```bash
python scripts/preflight.py
python -m compileall .
```

6. Lance Hamtaro :

```bash
python bot.py
```

## Variables essentielles

| Variable | Rôle |
|---|---|
| `DISCORD_TOKEN` | Token du bot Discord |
| `GUILD_ID` | Serveur utilisé pour la synchronisation rapide |
| `PUBLIC_GUILD_ID` | Serveur affiché sur le site public |
| `WEBSITE_BASE_URL` | Adresse publique du site |
| `SYNC_GUILD_COMMANDS` | Synchronisation immédiate sur le serveur |
| `SYNC_GLOBAL_COMMANDS` | Synchronisation mondiale, à activer seulement lors d'une publication |
| `DATABASE_BACKUPS_ENABLED` | Active les sauvegardes SQLite |

Railway fournit automatiquement `RAILWAY_VOLUME_MOUNT_PATH` lorsqu'un volume est attaché. Avec un montage `/data`, la base est stockée dans `/data/database.db`.

## Synchronisation des commandes

En développement :

```env
SYNC_GUILD_COMMANDS=true
SYNC_GLOBAL_COMMANDS=false
```

Pour publier les commandes globalement, active temporairement :

```env
SYNC_GLOBAL_COMMANDS=true
```

Après un déploiement réussi, remets la valeur à `false` afin d'éviter une synchronisation globale à chaque redémarrage.

## Sauvegardes

Hamtaro crée :

- une sauvegarde avant le démarrage et les migrations ;
- une sauvegarde périodique ;
- une sauvegarde à l'arrêt propre ;
- une sauvegarde manuelle avec `/hamtaro_backup`.

La commande `/hamtaro_health` contrôle la connexion Discord, les cogs, le site, la base et la persistance.

## Test fonctionnel minimum

1. Créer un tournoi de 4 joueurs.
2. Inscrire quatre comptes.
3. Lancer le tournoi.
4. Envoyer, rejeter puis renvoyer un résultat.
5. Valider les demi-finales et la finale.
6. Vérifier le bracket, les profils, l'historique et le site.
7. Redéployer Railway et vérifier que le tournoi est toujours présent.
8. Refaire le test en rondes suisses avec un double loss.

## Sécurité

Ne versionne jamais `.env`, `database.db`, les sauvegardes ou le token Discord. Si un secret a été publié, retire le fichier du dépôt puis régénère immédiatement le secret concerné.
