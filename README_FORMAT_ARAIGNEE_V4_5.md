# Hamtaro — Format Araignée v4.5 (pool 120 cartes)

La v4.3 conserve le système d'alias d'images et retire **Ombre Spectrale** et **Dragon de Lave** du format et de la galerie. Le pool officiel contient désormais **120 cartes**.

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

Le script `tools/araignee_images.py` utilise l'API YGOPRODeck v7 pour résoudre les noms français, puis les alias manuels si nécessaire, avant de télécharger les miniatures **une seule fois** dans :

`web/static/araignee/cards/`

Le site sert ensuite les fichiers locaux. Il ne hotlinke pas continuellement le serveur d'images.

Le manifest est stocké dans :

`data/formats/araignee_images.json`


## Alias images

La galerie supporte maintenant un fichier :

`data/formats/araignee_image_aliases.json`

Il contient des correspondances manuelles entre le nom du pool et un nom mieux reconnu par l'API d'images.

Exemples :

- `Bébé Araignée` → `Baby Spider`
- `Traptrix Trappelutea` → `Traptrix Holeutea`
- `Numéro S37 : Araignée Requin` → `Number S37: Spider Shark`

Le script `python3 tools/araignee_images.py sync` tente désormais :

1. le nom du pool ;
2. l'alias manuel ;
3. sinon il laisse un placeholder.

L'objectif de cette v4.2 est de faire monter fortement la couverture de la galerie.


## Pool mis à jour

La v4.4 retire également **Araignée de Verre** du format.
Le pool officiel contient maintenant **134 cartes**.

Cartes retirées par les dernières mises à jour :

- Ombre Spectrale
- Dragon de Lave
- Araignée de Verre


## Nouveaux ajouts v4.5

Le pool passe de **119 à 134 cartes** avec ces 15 ajouts :

1. Toile d'Araignée
2. Larves d'Araignées
3. Insecte des Ténèbres
4. Épine Krawler
5. Qualiarche X-Krawler
6. Neurogos X-Krawler
7. Krawler Croisédia
8. Dendrite Krawler
9. Deus X-Krawler
10. Soma Krawler
11. Récepteur Krawler
12. Gliale Krawler
13. Axone Krawler
14. Ranvier Krawler
15. Tragoedia

La galerie tentera automatiquement de résoudre leurs images lors du prochain `sync`.

## Installation

Depuis la racine du dépôt Hamtaro :

```bash
python3 install_araignee_format.py --check
python3 install_araignee_format.py
python3 tools/araignee_images.py status
python3 -m pytest tests/test_araignee_format.py -q
git status
git add -A
git commit -m "Ajout de 15 cartes au Format Araignée v4.5"
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


## Retrait v4.3

Les cartes suivantes ont été retirées du pool officiel et ne doivent plus apparaître dans la galerie :

- Ombre Spectrale
- Dragon de Lave

Après `python3 tools/araignee_images.py sync`, le script nettoie aussi les anciennes images locales devenues inutilisées.
