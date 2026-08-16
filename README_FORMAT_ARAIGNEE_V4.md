# Hamtaro — Format Araignée v4 (galerie images)

La v4 ajoute une vraie **galerie visuelle** des 130 cartes sur `/formats/araignee`.

## Règles conservées

- Main Deck : **40 à 60 cartes** ;
- **10 à 15 cartes Araignée** dans le Main Deck ;
- un seul archétype secondaire, **5 à 15 cartes** ;
- Extra Deck : **0 à 15 cartes, libre**, sous la **banlist TCG actuelle** ;
- Side Deck : **libre** ;
- jusqu'à **3 cartes de l'archétype secondaire déclaré** peuvent être ajoutées au Side ;
- archétype secondaire verrouillé pendant le tournoi.

## Galerie images

La page propose maintenant :

- un affichage **Galerie** par défaut ;
- un affichage **Liste** ;
- la même recherche dans les deux vues ;
- images chargées en `lazy loading` ;
- nom cliquable vers la recherche officielle Yu-Gi-Oh! Neuron ;
- placeholder propre si une image n'est pas résolue ;
- mémorisation locale du choix Galerie/Liste.

### Source et stockage

Le script `tools/araignee_images.py` utilise l'API YGOPRODeck v7 pour résoudre les noms français puis télécharge les miniatures **une seule fois** dans :

`web/static/araignee/cards/`

Le site sert ensuite les fichiers locaux. Il ne hotlinke pas continuellement le serveur d'images.

Le manifest est stocké dans :

`data/formats/araignee_images.json`

## Installation

Depuis la racine du dépôt Hamtaro :

```bash
python3 install_araignee_format.py --check
python3 install_araignee_format.py
python3 tools/araignee_images.py status
python3 -m pytest tests/test_araignee_format.py -q
git status
git add -A
git commit -m "Ajout galerie images Format Araignée v4"
git push origin main
```

L'installateur tente automatiquement de synchroniser les images. Si le réseau échoue, le reste du format reste installé et tu peux relancer :

```bash
python3 tools/araignee_images.py sync
```

Pour forcer un rafraîchissement :

```bash
python3 tools/araignee_images.py sync --force
```

Pour installer sans images :

```bash
python3 install_araignee_format.py --skip-images
```

## Ce qui est installé

- `data/formats/araignee.json`
- `data/formats/araignee_images.json` après synchronisation
- `services/araignee_format_service.py`
- `services/format_routes.py`
- `cogs/araignee_format.py`
- `web/templates/formats.html`
- `web/templates/format_araignee.html`
- styles de galerie dans `web/static/style.css`
- `tools/araignee_pool.py`
- `tools/araignee_images.py`
- tests du format
