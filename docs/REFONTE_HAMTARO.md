# Refonte Hamtaro — novembre 2026

Cette branche prépare le planning, les affiches hebdomadaires et la nouvelle navigation du site. Elle n’est pas déployée. Le bot et le site partagent le même service Railway : déployer le site implique aussi de redémarrer le bot et de synchroniser ses commandes Discord. L’accord du propriétaire est nécessaire avant cette étape.

## Comportement prévu

- Conservation des créneaux existants jusqu’au 29 novembre 2026.
- À partir de décembre : deux tournois par week-end, un Classique et un format alternatif, avec alternance samedi/dimanche. Seize semaines glissantes, prolongées automatiquement.
- Rotation proposée : GOAT, Suisse, Pure, Edison, Genesys, Boss. Halloween remplace le format alternatif en octobre. Plateforme par défaut des nouveaux créneaux : YGO Omega. Les plateformes encore « À confirmer » dans le planning existant restent visibles comme telles.
- Création des tournois à J−7. Inscriptions fermées 30 minutes avant le départ. Pas de check-in. Capacité habituelle : 8 joueurs ; seuil par défaut : 4, ajustable avec `HAMTARO_AUTO_START_MIN_PLAYERS` ou `min_players` dans le créneau.
- Un seul moteur de démarrage. Un départ manqué de plus de cinq minutes est annulé : pas de lancement plusieurs heures après une panne. Les tournois déjà réclamés par le moteur ne sont pas rejoués automatiquement.
- Les anciens tournois restent dans la base. Le calendrier public privilégie les dates à venir et indique les annulations. Aucun historique supprimé.

Les modifications ponctuelles sont possibles dans `data/tournament_schedule.json`, rubrique `exceptions`, indexées par date. Exemple :

```json
{
  "2026-12-26": {"cancelled": true},
  "2027-01-03": {"format": "Suisse", "start": "17:00", "end": "20:30", "min_players": 4, "max_players": 16}
}
```

Ce sont des exemples, aucune pause de Noël n’est actuellement imposée. La capacité et le format d’un tournoi déjà créé doivent aussi être modifiés par les commandes de gestion existantes : le planning ne réécrit pas les choix du staff dans la base.

## Affiche et commandes staff

L’affiche PNG est composée par Hamtaro avec ses données réelles : semaine, dates, horaires, formats, plateforme, structure, code, clôture, minimum de joueurs et parcours d’inscription. Une version textuelle accompagne le fichier pour la lisibilité et l’accessibilité. Aucun fournisseur d’IA ni abonnement n’est nécessaire.

Commandes après regroupement de l’interface :

| Commande | Effet |
|---|---|
| `/staff planning affiche` | Aperçu privé, semaine courante ou suivante |
| `/staff planning publier_affiche` | Publie dans le salon configuré ; actualise le message existant de la semaine |
| `/staff planning configurer_annonce` | Salon, jour, heure, minute et activation de la récurrence |
| `/staff planning etat_annonce` | Salon exact, horaire, activation et état du dernier envoi |

Le répartiteur de commandes peut placer ce groupe dans une page `staff_suite` si la page staff atteint la limite de taille de Discord. Les contrôles de rôle restent appliqués côté bot. Le rôle `Staff Tournoi` rejoint les noms staff déjà reconnus.

Configuration proposée : mercredi à 18 h, heure de Paris. Le jour et l’heure sont enregistrés en SQLite, avec prise en compte des changements d’heure. Si Hamtaro redémarre après l’heure prévue, il rattrape l’annonce jusqu’au vendredi soir. Il ne publie pas tardivement un ancien programme le week-end.

Protection contre les doublons : une seule publication par serveur et par semaine, enregistrée dans SQLite avant l’envoi. En cas de réponse réseau incertaine, Hamtaro recherche le message portant son marqueur dans les 100 derniers messages du salon. Si l’état reste ambigu, il réclame une vérification du staff plutôt que de republier. Une panne au mauvais moment peut donc nécessiter une intervention manuelle. Une modification de salon n’entraîne pas de copie automatique d’un programme déjà publié.

## Activation après accord

1. Inventaire relevé le 10 novembre 2026 sur les deux captures du propriétaire : 17 salons textuels et 4 vocaux, détaillés ci-dessous. L’identifiant fourni pour le salon de publication est `1256190735787753575`. Les captures ne permettent pas d’associer cet identifiant à un nom ; le bot résout le salon dans le serveur configuré et inscrit son nom dans les logs. Le salon `🏸・matchs`, ID `1537598665181495307`, a également été confirmé par les logs Railway du 8 novembre.
2. Valider le salon d’annonce, les permissions nécessaires et les changements de commandes avec le propriétaire. Aucune création/suppression de salon, aucun changement de rôle ou message public n’a été effectué pendant la préparation.
3. Fusionner puis déployer après accord. Vérifier le succès du déploiement, le chargement de `WeeklyProgramCog`, l’absence d’erreur de synchronisation et `/health`.
4. Choisir le salon dans la commande de configuration, ou préparer depuis Railway `HAMTARO_WEEKLY_CHANNEL_ID=1256190735787753575`, `HAMTARO_WEEKLY_AUTOMATIC=true` et `HAMTARO_WEEKLY_ENABLED=false` avant le premier déploiement autorisé. L’initialisation n’envoie rien, vérifie le type de salon et son appartenance au serveur `GUILD_ID` (ou `PUBLIC_GUILD_ID`), puis enregistre mercredi 18 h Paris. Elle ne remplace jamais un réglage existant du staff. Vérifier le nom résolu dans les logs. Hamtaro doit déjà pouvoir voir le salon, lire l’historique, envoyer des messages, intégrer des liens et joindre des fichiers ; toute modification de permissions réclame un accord distinct.
5. Configurer `HAMTARO_WEEKLY_ENABLED=true` sur le service Railway et activer la récurrence dans les réglages du programme. Sans ce double réglage, aucune publication hebdomadaire automatique n’est possible. L’aperçu staff reste disponible.
6. Tester l’aperçu privé, puis un envoi public seulement après accord. Vérifier le lien du message et le salon dans les logs.

Le moteur de départ utilise le salon d’annonce explicitement configuré ou le salon des matchs déjà enregistré par `progression_setup`. Il ne choisit plus un premier salon accessible au hasard et refuse un salon situé dans un autre serveur.

## Inventaire Fun Row transmis par le propriétaire

Catégorie visible : `🐹 ~HAMTARO CUP~`. Noms transcrits sans leurs préfixes décoratifs. Cet inventaire ne modifie ni les salons ni leurs permissions ; les cadenas visibles ne suffisent pas à déterminer les rôles autorisés.

| Type | Salon |
|---|---|
| Texte | annonces-spéciales |
| Texte | règlement-tournois |
| Texte | guide-hamtaro |
| Texte | planning-tournois |
| Texte | tips-hamtaro |
| Texte | annonces-tournois |
| Texte | suggestions-hamtaro |
| Texte | discussion-tournois |
| Texte | inscriptions |
| Texte | commandes-hamtaro |
| Texte | matchs |
| Texte | rondes-suisses |
| Texte | classement-rondes-suisses |
| Texte | tournois-à-éliminations-directe |
| Texte | staff-logs-hamtaro |
| Texte | matchs-casuels |
| Texte | matchs-vedettes |
| Vocal | Duel 1 |
| Vocal | Duel 2 |
| Vocal | Staff Only |
| Vocal | Salon Streaming |

Répartition proposée sans réorganisation du serveur : l’affiche dans le salon explicitement désigné par le propriétaire, `planning-tournois` pour le calendrier, `inscriptions` pour le parcours d’inscription, `commandes-hamtaro` pour les interactions, les salons de matchs et de classement pour le suivi, `staff-logs-hamtaro` pour la supervision. Aucun nouveau salon nécessaire pour cette refonte.

## Aperçus et validation

- [Affiche de démonstration](previews/affiche-semaine.png)
- [Accueil autonome](previews/hamtaro-accueil.html) et [planning autonome](previews/hamtaro-planning.html) : télécharger les deux fichiers dans le même dossier pour naviguer entre les deux. Les autres liens pointent vers les routes habituelles du site et ne sont pas simulés.
- `python scripts/preview_reform.py` lance un aperçu local sur le port 8765, sans connexion Discord et sans base de production.
- Les pages ont été rendues avec Jinja et une base SQLite temporaire initialisée avec le vrai schéma. La vérification interactive dans le navigateur distant est bloquée pour les fichiers locaux ; le rendu mobile reste à vérifier avant fusion.
- Les nouveaux tests couvrent la rotation, les dates limites et changements d’heure, les exceptions, la création idempotente, la publication unique après redémarrage, une réponse réseau incertaine, les commandes staff, le manque de joueurs, le départ manqué et le refus d’un salon hors serveur. L’initialisation Railway est également vérifiée : aucune publication sans activation, aucun remplacement d’un réglage staff, refus des salons absents ou hors serveur et des identifiants invalides.
- Cinq tests de `tests/test_professional_suite.py` échouent déjà sur la base `085a32f` : modules et configuration d’un ancien pack absents. Ils ont été reproduits dans une copie intacte avant comparaison. Ils ne sont ni supprimés ni masqués.

Retour arrière : redéployer le commit précédent conserve les tables ajoutées et les données. Il faudra synchroniser les commandes de la version restaurée. La désactivation immédiate des seules affiches est possible avec `HAMTARO_WEEKLY_ENABLED=false`.
