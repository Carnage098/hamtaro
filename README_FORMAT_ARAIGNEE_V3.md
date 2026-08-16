# Hamtaro — Format Araignée v3

Version corrigée du pack Format Araignée pour le bot Discord et le site Hamtaro.

## Règles intégrées

- Main Deck : **40 à 60 cartes** ;
- **10 à 15 cartes Araignée** du pool officiel dans le Main Deck ;
- un seul archétype secondaire ;
- **5 à 15 cartes** de l'archétype secondaire ;
- maximum 2 archétypes : Araignée + secondaire ;
- cartes génériques via whitelist ;
- Extra Deck : **0 à 15 cartes**, libre ;
- les restrictions de l'Extra suivent les **banlists annoncées pour le format ou le tournoi**, pas forcément la banlist TCG du moment ;
- Side Deck : **libre** ;
- jusqu'à **3 cartes de l'archétype secondaire déclaré** peuvent être ajoutées au Side Deck ;
- archétype secondaire verrouillé pendant le tournoi.

## Liens des cartes

Les 130 cartes du pool sont cliquables sur `/formats/araignee`.
Chaque nom ouvre une recherche en français sur la base officielle **Yu-Gi-Oh! Neuron**.

Aucun identifiant `cid` n'est maintenu à la main : le lien est généré automatiquement depuis le nom de la carte.

## Validation automatique

Le moteur contrôle :
- Main Deck entre 40 et 60 ;
- quota Araignée entre 10 et 15 ;
- Extra Deck maximum 15 lorsqu'il est fourni ;
- maximum générique de 3 exemplaires sur Main + Extra + Side ;
- normalisation des noms ;
- suggestions de noms proches.

Le Side Deck est volontairement libre : sa taille n'est pas un critère d'invalidité.

Le validateur ne peut pas encore confirmer automatiquement :
- l'identité de l'archétype secondaire ;
- si les 3 cartes autorisées dans le Side appartiennent bien à cet archétype ;
- la whitelist générique ;
- les limites propres aux banlists annoncées.

## Installation / mise à jour depuis une ancienne version

Place ce pack dans ton dépôt Hamtaro puis :

```bash
python3 install_araignee_format.py --check
python3 install_araignee_format.py
python3 -m pytest tests/test_araignee_format.py -q
git status
git add -A
git commit -m "Mise à jour Format Araignée v3"
git push origin main
```

L'installateur est idempotent : il remplace les fichiers du module Araignée et met à jour le bloc CSS sans créer de doublons.

## Pages et commandes

Site :
- `/formats`
- `/formats/araignee`
- `/api/formats/araignee`
- `/api/formats/araignee/pool.txt`
- `POST /api/formats/araignee/validate`

Discord :
- `/araignee rules`
- `/araignee pool`
- `/araignee check`
- `/araignee card`
