# Rapport d'audit Hamtaro

## Corrections appliquées

### Fiabilité du démarrage

- séparation entre cogs essentiels et facultatifs ;
- arrêt du déploiement lorsqu'un cog essentiel est cassé ;
- fermeture propre des tâches, de SQLite et du WAL ;
- logs d'interactions détaillés désactivés par défaut ;
- watchdog configurable.

### Discord

- synchronisation globale désactivée par défaut ;
- synchronisation rapide du serveur conservée ;
- mentions accidentelles bloquées par défaut ;
- gestion centralisée des interactions expirées et doubles réponses ;
- intention `message_content` désactivée par défaut.

### SQLite et Railway

- chemin unique partagé par `config.py`, `database.py` et `DatabaseService` ;
- utilisation automatique du volume Railway ;
- timeout SQLite de 30 secondes ;
- WAL, clés étrangères, `temp_store` et optimisation ;
- contrôle d'intégrité avant migration ;
- sauvegardes pré-démarrage, périodiques, manuelles et d'arrêt ;
- rétention automatique des sauvegardes ;
- verrou empêchant deux instances d'utiliser le même volume ;
- journal d'audit système préparé dans le schéma.

### Tournois

- capacité maximale portée à 128 partout où le motif historique est trouvé ;
- correction de `start_tournament` : `current_round` commence à 1 ;
- conservation du multi-tournoi et du contexte par salon ;
- actualisation automatique de la liste du site.

### Dépôt

- dépendances bornées et doublon `matplotlib` supprimé ;
- `.gitignore` complet ;
- `.env.example` ;
- anciens installateurs et ancien `bot(10).py` déplacés dans `legacy/` ;
- préflight, tests statiques et documentation de déploiement.

## Limite importante

Le verrou local empêche les doublons partageant le même volume. Il ne peut pas détecter un second service Railway utilisant le même token avec une base différente. Il faut donc toujours conserver un seul service et un seul réplica Hamtaro.
