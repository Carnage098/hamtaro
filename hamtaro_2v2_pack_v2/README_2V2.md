# Hamtaro — 2v2 Native v2

Cette version transforme le 2v2 en **type de participants natif du tournoi**.

Lors de `/create_tournament`, le staff choisit désormais :

- `👤 Solo 1v1`
- `👥 Équipes 2v2`

Les anciens tournois qui n'ont aucune valeur enregistrée restent automatiquement en **Solo 1v1**.

## Parcours 2v2 natif

### 1. Créer les équipes

Capitaine :

`/duo team_create name:<nom> partner:<joueur> deck:<deck>`

Partenaire :

`/duo team_accept team_id:<id> deck:<deck>`

### 2. Créer le tournoi

Exemple :

`/create_tournament name:Coupe Duo format:Actuel max_players:8 participants:👥 Équipes 2v2`

En mode 2v2, `max_players` représente le **nombre maximal d'équipes**, donc 8 = 16 joueurs au maximum.

### 3. Inscription native

Une fois le tournoi 2v2 sélectionné dans le salon, les joueurs utilisent simplement :

`/register`

Hamtaro détecte automatiquement leur équipe complète.

Si un joueur appartient à plusieurs équipes actives :

`/register team_id:<id>`

Le paramètre `deck` de `/register` reste utilisable et met à jour le deck du joueur dans son équipe avant de figer le roster du tournoi.

Les commandes natives suivantes détectent aussi automatiquement le mode 2v2 :

- `/unregister`
- `/deck`
- `/players`

### 4A. Élimination directe

Le staff utilise la commande normale :

`/start_tournament`

Si le tournoi est 2v2, Hamtaro lance automatiquement le moteur d'élimination par équipes. Si le tournoi est Solo, l'ancien moteur de bracket est utilisé.

### 4B. Ronde suisse

Le staff utilise la commande normale :

`/swiss_start rondes:<nombre>`

Puis :

- `/swiss_pairings`
- `/swiss_next`
- `/swiss_standings`
- `/swiss_status`
- `/swiss_reset`

Ces commandes basculent automatiquement sur le moteur 2v2 quand le tournoi sélectionné est un tournoi Duo.

## Déroulement d'une rencontre

Deux duels initiaux :

- Duel 1 : A1 vs B1
- Duel 2 : A2 vs B2

Si le score est **1-1 propre**, Hamtaro crée automatiquement un **duel décisif entre les deux vainqueurs**.

Les résultats individuels restent regroupés sous `/duo` pour ne pas ajouter plusieurs commandes racines Discord :

`/duo report match_id:<id> board:<1|2|3> outcome:<...>`

Puis l'adversaire confirme :

`/duo confirm match_id:<id> board:<n>`

ou refuse :

`/duo reject match_id:<id> board:<n>`

Le staff dispose aussi de `/duo admin_result` et `/duo force_winner`.

## Règle Double Loss — Suisse 2v2

| Situation | Vainqueur de rencontre | Points |
|---|---|---:|
| 2 victoires propres | équipe gagnante | 3 |
| 1-1 + duel décisif gagné proprement | équipe gagnante | 3 |
| 1 victoire + 1 double loss | équipe avec la victoire | **0** |
| 1 défaite + 1 double loss | équipe perdante | **0** |
| 2 double losses | aucun | **0 / 0** |
| double loss sur le duel décisif | aucun | **0 / 0** |

Une seule double loss dans la rencontre suffit à empêcher l'attribution des 3 points.

### Départage punitif des DL

À points égaux :

1. équipe sans aucune DL ;
2. moins de DL ;
3. plus de victoires ;
4. meilleur Buchholz ;
5. meilleure différence de boards ;
6. moins de défaites.

Ainsi, une équipe à 0 point avec une défaite normale passe devant une équipe à 0 point ayant subi une double loss.

## Installation

Extrais le dossier du pack dans le dépôt, puis depuis la racine de Hamtaro :

```bash
cd ~/Downloads/hamtaro
python3 hamtaro_2v2_pack_v2/install_hamtaro_2v2.py
```

Le script :

- sauvegarde `bot.py`, `cogs/tournament.py`, `cogs/registration.py` et `cogs/swiss.py` ;
- ajoute `cogs.team_2v2` à `REQUIRED_COGS` ;
- modifie les commandes existantes au lieu d'ajouter plusieurs commandes racines ;
- vérifie la syntaxe Python avant de terminer ;
- restaure automatiquement les quatre fichiers principaux si l'installation échoue.

Ensuite :

```bash
python3 -m pytest tests/test_team_2v2_service.py -q

git status
git add bot.py cogs/tournament.py cogs/registration.py cogs/swiss.py \
  cogs/team_2v2.py services/team_2v2_service.py tests/test_team_2v2_service.py

git commit -m "Add native 2v2 tournament mode"
git push origin main
```

## Base SQLite

Tables séparées :

- `duo_tournament_modes`
- `duo_teams`
- `duo_team_members`
- `duo_team_invites`
- `duo_tournaments`
- `duo_tournament_entries`
- `duo_entry_members`
- `duo_matches`
- `duo_boards`
- `duo_standings`

Les tables et données 1v1 existantes ne sont pas remplacées.

## Compatibilité v1

La v2 peut être installée au-dessus de la v1 : les fichiers du moteur 2v2 sont remplacés par la version native, tandis que les tables `duo_*` existantes sont conservées.

## Retour arrière

L'installation crée un dossier :

`upgrade_backup/team_2v2_native_<date>/`

Le script de restauration remet les quatre fichiers principaux dans leur état d'avant installation et retire les nouveaux fichiers 2v2. Il conserve volontairement les tables SQLite `duo_*`.

```bash
python3 hamtaro_2v2_pack_v2/uninstall_hamtaro_2v2.py
```

À utiliser avant d'apporter d'autres modifications importantes à ces quatre fichiers, car il restaure leur snapshot pré-installation.
