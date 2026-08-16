# Hamtaro — Format Araignée v2

Pack complet pour intégrer le **Format Araignée** au bot Discord et au site Hamtaro.

## Améliorations de la v2

- installateur adapté à la structure actuelle de Hamtaro ;
- installation **idempotente** : le pack peut être relancé pour mettre à jour les fichiers ;
- `--check` pour tester la compatibilité avant modification ;
- sauvegarde des fichiers modifiés ;
- **rollback automatique** si une erreur survient pendant l'installation ;
- vérification syntaxique Python avant validation finale ;
- une seule source de vérité : `data/formats/araignee.json` ;
- révision SHA du pool affichée sur Discord et le site ;
- validateur partagé entre Discord et le site ;
- endpoint POST de validation côté serveur ;
- téléchargement du pool en `.txt` ;
- outil CLI pour ajouter/retirer une future carte ;
- tests supplémentaires.

## Règles du format intégrées

- Main Deck : exactement **40 cartes** ;
- **10 à 15 cartes Araignée** du pool officiel dans le Main Deck ;
- un seul archétype secondaire ;
- **5 à 15 cartes** de l'archétype secondaire ;
- maximum 2 archétypes : Araignée + secondaire ;
- cartes génériques via whitelist ;
- Extra Deck : **0 à 15**, libre ;
- Side Deck : **exactement 3 cartes**, uniquement de l'archétype secondaire ;
- archétype secondaire verrouillé pendant le tournoi ;
- Banlist TCG + banlist spéciale Araignée.

## Contrôles automatiques v2

Le moteur vérifie réellement :

- Main Deck = 40 ;
- quota Araignée = 10–15 ;
- Extra Deck ≤ 15 lorsqu'une section Extra est fournie ;
- Side Deck = 3 lorsqu'une section Side est fournie ;
- maximum générique de 3 exemplaires d'une même carte sur Main + Extra + Side ;
- normalisation accents/apostrophes/tirets ;
- suggestions si le nom saisi ressemble fortement à une carte du pool ;
- détection des exports `.ydk` numériques non résolus.

Il **n'affirme pas** contrôler ce qu'il ne connaît pas encore :

- identité de l'archétype secondaire ;
- appartenance des génériques à la whitelist ;
- limites propres aux banlists.

## Installation

Décompresse le ZIP à la racine du dépôt Hamtaro.

### 1. Vérifier sans modifier

```bash
python3 install_araignee_format.py --check
```

### 2. Installer

```bash
python3 install_araignee_format.py
```

### 3. Tester

```bash
python3 -m pytest tests/test_araignee_format.py -q
git status
```

### 4. Envoyer sur GitHub

```bash
git add .
git commit -m "Ajout du Format Araignée v2"
git push origin main
```

Railway redéploiera ensuite le dépôt.

## Discord

- `/araignee rules`
- `/araignee pool`
- `/araignee check`
- `/araignee card`

`Araignée` est aussi ajouté à `/create_tournament` et à `/change_tournament_format` car ces commandes utilisent la même liste `FORMATS`.

## Site

- `/formats`
- `/formats/araignee`
- `/api/formats/araignee`
- `/api/formats/araignee/pool.txt`
- `POST /api/formats/araignee/validate`

La page du format contient :

- les règles ;
- les 130 cartes ;
- une recherche instantanée ;
- téléchargement du pool ;
- validation serveur de decklist ;
- affichage des erreurs et avertissements ;
- révision du pool.

## Ajouter une nouvelle carte plus tard

```bash
python3 tools/araignee_pool.py add "Nom de la carte"
```

Retirer une carte :

```bash
python3 tools/araignee_pool.py remove "Nom de la carte"
```

Vérifier le pool :

```bash
python3 tools/araignee_pool.py check
```

Puis commit/push normalement. Aucun fichier Python ou template n'a besoin d'être modifié.

## Important

Le fichier `data/formats/araignee.json` est la **source unique** du pool et des paramètres du format. Le site et Discord lisent tous les deux ce fichier.
