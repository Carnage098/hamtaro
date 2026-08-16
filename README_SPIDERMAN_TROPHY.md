# Hamtaro — Trophée Spiderman HT-003

Le pack ajoute le trophée 3D à la page Trophées et à la page Formats. Le petit carré 3D tourne automatiquement, possède un bouton Agrandir et un lien vers la fiche HT-003.

Le trophée est pré-lié aux tournois nommés `Spiderman`, `Spider-Man` ou `Spider Man`. Quand `/end_tournament` termine ce tournoi, le vainqueur, son deck, le format, le code et l'ID réel du tournoi sont enregistrés en SQLite.

## Terminal

```bash
python3 install_spiderman_trophy.py --check
python3 install_spiderman_trophy.py
python3 -m py_compile services/spiderman_trophy_award_service.py services/trophy_service.py cogs/end_tournament.py cogs/public_website.py
git status
git add -A
git commit -m "Ajout trophée HT-003 du tournoi Spiderman"
git push origin main
```

Le modèle original fait environ 86 Mo, donc le premier chargement 3D peut être long.
