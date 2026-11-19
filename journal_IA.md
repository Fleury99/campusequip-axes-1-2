# Journal des aides utilisées — CampusEquip v2

Ce journal décrit les principales aides utilisées pendant la réalisation.
Les scripts générés ou proposés avec une assistance IA ont été exécutés
et contrôlés dans l'environnement local. Le binôme doit pouvoir expliquer
les règles métier, les requêtes SQL et le fonctionnement du pipeline.

| Date | Question ou difficulté | Aide utilisée | Modification réalisée | Test effectué et résultat |
|---|---|---|---|---|
| 2026-11-18 | Préparer l'environnement PostgreSQL et le modèle relationnel | Assistance IA et documentation du kit | Création du service PostgreSQL Docker, du fichier de configuration local et des huit tables SQL | Schéma exécuté ; huit tables présentes ; chargement des référentiels : 6 campus, 12 sites, 2 000 clients, 6 catégories et 120 équipements |
| 2026-11-18 | Charger les référentiels fournis | Assistance IA pour le script Python et les contrôles | Création de etudiant/charger_referentiels.py avec contrôles des fichiers, empreintes et transaction | Référentiels chargés et nombres de lignes vérifiés dans PostgreSQL |
| 2026-11-18 | Contrôler et charger les lots de locations | Assistance IA pour la conception et la relecture de etudiant/traitement.py | Implémentation de la normalisation, validation, dédoublonnage, quarantaine, anomalies, signature SHA-256 et chargement transactionnel | Deux lots propres chargés : 41 et 39 lignes ; relance reconnue DEJA_CHARGE ; aucun doublon métier |
| 2026-11-18 | Répondre aux trois questions analytiques | Assistance IA pour la conception et la vérification des requêtes | Création de analyses.sql : montants quotidiens par campus, classement des équipements et comparaison heure/journée | 126 lignes pour l'analyse quotidienne, 42 lignes pour le classement et 11 résultats campus/unité ; contrôle indépendant : 44 lignes, 21 contrats et 48 098 MAD |
| 2026-11-18 | Exporter les résultats et produire un graphique | Assistance IA pour le script Python | Création de etudiant/exporter_analyses.py avec Psycopg, Pandas et Matplotlib | Trois CSV, un graphique PNG et une synthèse Markdown générés ; total vérifié à 48 098 MAD |
| 2026-11-19 | Tester les défauts de qualité sans modifier la base principale | Assistance IA pour isoler la base et préparer un lot mixte | Création de campusequip_test par copie de la base principale, puis génération du lot 3 dans flux_test | 38 lignes brutes, 1 doublon, 29 acceptées, 8 mises en quarantaine, 16 contrats acceptés, 1 anomalie ; alerte HIGH_REJECT_RATE |
| 2026-11-19 | Vérifier l'isolation des essais | Assistance IA pour les requêtes de contrôle PostgreSQL | Comparaison des compteurs de la base principale et de la copie de test | Base principale inchangée : 40 contrats, 80 lignes et 2 lots ; base de test : 56 contrats, 109 lignes et 3 lots |

## Points restant à démontrer

- Rejet d'un lot dont la structure CSV est incorrecte, avant toute écriture métier.
- Refus transactionnel d'un nouveau lot réutilisant un identifiant de contrat déjà chargé.
- Rejeu du même contenu sous un autre nom de dossier.
- Traitement de trois nouveaux lots successifs pendant une même surveillance continue.
- Calcul manuel documenté d'un contrat et rédaction du rapport final.

Les résultats indiqués dans ce journal correspondent aux exécutions observées.
Les scénarios restant à démontrer ne sont pas présentés comme réussis.

## Entrée du 19 novembre 2026 — validations complémentaires

Tests et résultats vérifiés :

1. **Structure invalide :** inversion des colonnes `client_id` et `site_id`. Le lot 4 a été rejeté avec `REJETE_STRUCTURE`. La base principale est restée à 40 contrats, 80 lignes et 2 lots.
2. **Conflit d'identifiant :** le traitement a renvoyé `ORDER_ID_CONFLICT` pour des contrats déjà chargés, dont le contrat 1. Code retour 1. La base de test est restée à 56 contrats, 109 lignes et 3 lots.
3. **Rejeu renommé :** une copie identique du lot 3, placée dans un autre dossier, a renvoyé `DEJA_CHARGE` avec la même signature SHA-256. Aucun compteur n'a augmenté.
4. **Trois lots successifs :** une seule instance de `surveiller.py` a traité les lots 4, 5 et 6 avec le statut `CHARGE`. Les lignes acceptées ont été respectivement 23, 33 et 34. Une anomalie a été détectée dans chaque lot. Les taux de rejet étaient de 36,11 %, 25 % et 19,05 %.
5. **Compteurs finaux de la base de test :** 104 contrats, 199 lignes et 6 lots journalisés.
6. **Calcul manuel :** contrat 2 : (3 × 1 × 134) + (2 × 3 × 126) + (4 × 4 × 283) = 5 686 MAD. Résultat confirmé par SQL.

Réserves à conserver dans la documentation :

- Les trois lots étaient déjà présents lorsque le surveillant a démarré : le traitement successif dans une seule exécution est validé, mais pas l'arrivée en temps réel.
- Le conflit d'identifiant a été détecté avant les insertions : Validation effectuée le 19 novembre 2026 ; voir la section de validation correspondante.
- La reprise après arrêt puis redémarrage du surveillant est validée le 19 novembre 2026. Voir la section « Reprise après redémarrage ».

## Reprise après redémarrage — 19 novembre 2026

Après l'arrêt du surveillant, un nouveau processus a été lancé sur `flux_continu` avec `--une-fois`, en ciblant la base `campusequip_test`.

Résultat : les lots 4, 5 et 6 ont tous reçu le statut `DEJA_CHARGE`. Le code de retour était 0. Les compteurs sont restés à 104 contrats, 199 lignes et 6 lots journalisés.

La reprise après redémarrage sans doublons est validée.

## Test de rollback transactionnel — 19 novembre 2026

Dans la base isolée `campusequip_rollback_test`, un déclencheur SQL temporaire sur `contract_lines` a provoqué une erreur volontaire pendant le chargement du lot 7, après l'insertion des contrats dans la même transaction.

Le lot comportait 41 lignes acceptables et 20 nouveaux contrats (121 à 140). Le rapport a enregistré `FAILED` et l'erreur `ROLLBACK_TEST_INJECTED`.

Les compteurs après échec sont restés à 104 contrats, 199 lignes et 6 lots journalisés. Aucun contrat 121 à 140 n'a été conservé. Cela démontre l'annulation des insertions précédentes par rollback transactionnel.

Le déclencheur et la fonction SQL temporaires ont ensuite été supprimés. Leur absence a été vérifiée dans PostgreSQL.
