# CampusEquip v2 — Axes 1 et 2

Projet étudiant de Data Engineering : analyse SQL et pipeline Python
de validation et de chargement des locations d'équipements.

**Date de remise : 21 novembre 2026**

## 1. Objectifs

Le projet répond à quatre questions métier :

- Quel montant chaque campus réalise-t-il chaque jour ?
- Quels équipements contribuent le plus au chiffre d'affaires de chaque campus ?
- Quelle est la contribution des locations à l'heure et à la journée ?
- Comment isoler les contrats incohérents et éviter les doubles chargements ?

Le travail porte uniquement sur les axes 1 et 2. ShopFlow est un laboratoire
distinct et n'est pas utilisé par cette base CampusEquip.

## 2. Architecture

- **PostgreSQL 18** : référentiels, contrats, lignes de location et journal
  d'ingestion.
- **Python 3.12** : contrôle des fichiers, normalisation, validation,
  dédoublonnage, quarantaine et chargement transactionnel.
- **Psycopg 3** : connexion à PostgreSQL.
- **Pandas et Matplotlib** : export des analyses et graphique.
- **Docker Compose** : exécution locale de PostgreSQL.

Les lots sont fournis par `generer.py`. `surveiller.py` détecte les lots
publiés et appelle `etudiant/traitement.py`.

## 3. Arborescence principale

```text
CampusEquip_etudiant/
├── analyses.sql
├── compose.yaml
├── .env.example
├── generer.py
├── surveiller.py
├── journal_IA.md
├── etudiant/
│   ├── schema.sql
│   ├── charger_referentiels.py
│   ├── traitement.py
│   └── exporter_analyses.py
├── exemples/
│   ├── generator-state.json
│   ├── lot_000001/
│   └── lot_000002/
└── rapports/
    ├── analyse_1_montants_quotidiens.csv
    ├── analyse_2_classement_equipements.csv
    ├── analyse_3_locations_par_unite.csv
    ├── graphique_ca_par_campus.png
    ├── synthese_sql.md
    └── lot_*/...
````

## **4. Installation**

Prérequis :

- Docker Engine et Docker Compose ;
- Python 3.12 ;
- un environnement virtuel Python ;
- les bibliothèques Psycopg, Pandas et Matplotlib.

Activer l'environnement virtuel :

```
source ~/data-engineering/.venv/bin/activate
```

Installer les dépendances si nécessaire :

```
python -m pip install "psycopg[binary]" pandas matplotlib
```

Créer la configuration locale :

```
cp .env.example .env
chmod 600 .env
```

Modifier `.env` et remplacer le mot de passe d'exemple par un mot de passe\
local. Ne jamais publier ce fichier ni inscrire le mot de passe dans le dépôt.

## **5. Préparer une base neuve**

Démarrer PostgreSQL :

```
docker compose up -d --wait
docker compose ps
```

Créer les huit tables :

```
docker exec -i campusequip-postgres psql \
  -U campusequip -d campusequip \
  -v ON_ERROR_STOP=1 < etudiant/schema.sql
```

Charger les référentiels du premier lot :

```
python etudiant/charger_referentiels.py
```

Le script vérifie le marqueur `READY`, le manifeste, les empreintes SHA-256,\
les colonnes du CSV et les nombres attendus dans les référentiels. Il refuse\
l'import si les tables cibles ne sont pas vides.

Référentiels attendus :

- 6 campus ;
- 12 sites ;
- 2 000 clients ;
- 6 catégories ;
- 120 équipements.

## **6. Charger les deux lots propres**

Exécuter le traitement une première fois :

```
python surveiller.py --entree exemples --une-fois
```

Relancer la même commande pour vérifier l'idempotence.

Une signature déjà enregistrée doit renvoyer `DEJA_CHARGE` sans ajouter\
de contrats ni de lignes supplémentaires.

Le journal des lots est enregistré dans `ingestion_batches` dans la même\
transaction que les données métier.

## **7. Règles de qualité appliquées**

Le traitement respecte les règles suivantes :

- Le CSV doit comporter exactement les onze colonnes attendues, dans l'ordre.
- Les identifiants et les quantités sont des entiers strictement positifs.
- Les références client, site et équipement doivent exister.
- La date doit être valide au format `YYYY-MM-DD`.
- Les statuts autorisés sont `paid`, `closed`, `draft` et `cancelled`.
- Les unités autorisées sont `hour` et `day`.
- La durée est limitée à 720 heures ou 365 jours.
- Le tarif est vérifié avec `Decimal`, avec au plus deux décimales.
- Les répétitions exactes après normalisation sont dédoublonnées.
- Un conflit de clé de ligne, une ligne invalide ou un en-tête contradictoire\
  entraîne la mise en quarantaine de tout le contrat.
- Une quantité supérieure à 20 est acceptée si les autres règles sont valides,\
  mais signalée comme anomalie.
- Le taux de rejet est calculé après dédoublonnage.
- Une alerte `HIGH_REJECT_RATE` est produite au-delà de 20 %.

La signature du lot utilise les empreintes SHA-256 des deux fichiers et\
la version des règles `campusequip-v2.0`.

Un nouveau lot réutilisant un identifiant de contrat déjà chargé doit\
échouer intégralement : aucune insertion partielle ne doit subsister.

## **8. Analyses SQL et exports**

Les trois requêtes sont conservées dans `analyses.sql`.

1. Montants quotidiens par campus, du 1er au 21 novembre 2026,\
   avec les jours sans vente à zéro et le cumul par campus.
2. Classement des équipements par montant décroissant dans chaque campus,\
   avec conservation des ex æquo.
3. Comparaison des locations à l'heure et à la journée par campus,\
   avec nombre de lignes et montant total.

Générer les exports :

```
python etudiant/exporter_analyses.py
```

Les résultats sont enregistrés dans `rapports/` sous forme de trois CSV,\
d'un graphique PNG et d'une synthèse Markdown.

Convention métier :

- les contrats `paid` et `closed` contribuent au chiffre d'affaires ;
- les contrats `draft` et `cancelled` restent stockés mais sont exclus\
  des indicateurs ;
- le montant d'une ligne est `quantity * duration * unit_rate` ;
- le montant est rattaché à `start_date` ;
- aucune conversion entre heures et jours n'est appliquée.

## **9. Résultats vérifiés**

Sur les lots propres `lot_000001` et `lot_000002` :

- 41 lignes brutes pour le premier lot ;
- 39 lignes brutes pour le deuxième lot ;
- 40 contrats chargés ;
- 80 lignes de location chargées ;
- deux lots enregistrés dans le journal ;
- seconde exécution reconnue `DEJA_CHARGE`.

Résultats des analyses SQL :

- 44 lignes de location retenues ;
- 21 contrats retenus ;
- chiffre d'affaires total : **48 098 MAD** ;
- locations à la journée : 40 300 MAD ;
- locations à l'heure : 7 798 MAD.

Le chiffre d'affaires par campus est :

- Campus Rabat : 10 805 MAD ;
- Campus Agadir : 10 705 MAD ;
- Campus Tanger : 9 748 MAD ;
- Campus Marrakech : 8 043 MAD ;
- Campus Casablanca : 6 941 MAD ;
- Campus Fès : 1 856 MAD.

## **10. Test de qualité isolé**

Un lot mixte `lot_000003` a été généré dans `flux_test` avec la même\
campagne et les identifiants de contrats suivants : 41 à 60.

Pour ne pas modifier les résultats de référence, le test a été exécuté\
sur une copie PostgreSQL nommée `campusequip_test`.

Résultat observé :

- 38 lignes brutes ;
- 1 doublon exact supprimé ;
- 29 lignes acceptées ;
- 8 lignes mises en quarantaine ;
- 16 contrats acceptés ;
- 1 anomalie signalée (quantité 25) ;
- taux de rejet : 21,62 % ;
- alerte `HIGH_REJECT_RATE`.

La base principale est restée inchangée : 40 contrats, 80 lignes\
et 2 lots. La base de test contient 56 contrats, 109 lignes et 3 lots.

Les rapports détaillés se trouvent sous `rapports/lot_000003/`.

## **11. Tests complémentaires exécutés — 19 novembre 2026**

Les tests suivants ont été exécutés et leurs résultats vérifiés dans PostgreSQL.

| Scénario | Résultat vérifié |
|---|---|
| Structure CSV incorrecte | `REJETE_STRUCTURE`, aucune écriture dans la base principale |
| Identifiant de contrat déjà utilisé | `ORDER_ID_CONFLICT`, base de test inchangée |
| Rejeu sous un autre nom de dossier | `DEJA_CHARGE`, signature SHA-256 identique |
| Trois lots successifs | Lots 4, 5 et 6 traités par une seule instance du surveillant |
| Reprise après redémarrage | Les trois lots reconnus `DEJA_CHARGE` |
| Calcul manuel du contrat 2 | 5 686,00 MAD, confirmé par SQL |
| Erreur SQL après insertion des contrats | `FAILED`, rollback confirmé dans une base isolée |

### Surveillance de trois lots

Les lots 4, 5 et 6 ont été traités successivement par un seul processus de surveillance.

**Limite à préciser :** les trois lots étaient déjà publiés lors du démarrage du surveillant. Le traitement séquentiel dans une seule exécution est validé, mais ce test ne démontre pas leur détection en temps réel pendant leur publication.

Après leur chargement, la base de test contenait 104 contrats, 199 lignes et 6 lots journalisés. Les mêmes compteurs ont été observés après le redémarrage du surveillant.

### Calcul manuel

Le contrat 2 comporte trois lignes :

- 3 × 1 × 134,00 = 402,00 MAD
- 2 × 3 × 126,00 = 756,00 MAD
- 4 × 4 × 283,00 = 4 528,00 MAD

Total : **5 686,00 MAD**, confirmé par `SUM(quantity * duration * unit_rate)`.

### Preuve du rollback transactionnel

Dans la base isolée `campusequip_rollback_test`, un déclencheur SQL temporaire a provoqué une exception pendant l'insertion de `contract_lines`, après l'insertion des contrats.

Le lot contenait 20 nouveaux contrats (121 à 140). Après l'erreur `ROLLBACK_TEST_INJECTED`, les compteurs sont restés à 104 contrats, 199 lignes et 6 lots journalisés. Aucun des 20 contrats n'a été conservé.

Le rapport du lot 7 porte le statut `FAILED`. Le déclencheur et sa fonction temporaires ont ensuite été supprimés et leur absence vérifiée.

Le dossier source spécifique à cette injection n'est pas inclus dans la publication publique : il ne doit pas être traité comme un lot ordinaire en l'absence du déclencheur de test. Le rapport d'échec est conservé dans `rapports/lot_000007/`.

## **12. Arrêt des services**

Arrêter PostgreSQL sans supprimer les données :

```
docker compose stop
```

Redémarrer ultérieurement :

```
docker compose start
```

Ne pas utiliser `docker compose down -v` pour un simple arrêt :\
cette commande supprimerait également le volume de données.

## **13. Sécurité et remise**

Ne pas ajouter au dépôt :

- `.env` ;
- mots de passe ou jetons ;
- environnement virtuel `.venv` ;
- fichiers temporaires ou caches Python.

Conserver les scripts SQL et Python, les lots d'exemple reproductibles,\
les résultats d'analyse, les rapports de qualité, le graphique et\
`journal_IA.md`.

Le rapport de présentation final doit rester limité à quatre pages,\
hors annexes, conformément au sujet étudiant.\





### Étape 12 — Vérifier les fichiers avant GitHub

Exécute maintenant :

```bash
echo "===== README ====="
sed -n '1,260p' README.md

echo
echo "===== CONFIGURATION EXEMPLE ====="
cat .env.example

echo
echo "===== IGNORE GIT ====="
cat .gitignore

echo
echo "===== VÉRIFICATION DES SECRETS ====="
git status --short --ignored | head -n 80

```

## Vérifications complémentaires — 19/11/2026

Les tests complémentaires suivants ont été exécutés.

| Test | Résultat observé |
|---|---|
| Structure CSV incorrecte | `REJETE_STRUCTURE` |
| Base principale après rejet structurel | 40 contrats, 80 lignes, 2 lots |
| Conflit d'identifiant existant | `ORDER_ID_CONFLICT`, code retour 1 |
| Base de test après conflit | 56 contrats, 109 lignes, 3 lots, inchangés |
| Rejeu du lot sous un autre nom | `DEJA_CHARGE`, signature identique |
| Base de test après rejeu | 56 contrats, 109 lignes, 3 lots, inchangés |

### Traitement de trois lots successifs

Une seule instance de `surveiller.py` a traité les lots 4, 5 et 6 :

| Indicateur | Lot 4 | Lot 5 | Lot 6 |
|---|---:|---:|---:|
| Lignes brutes | 37 | 45 | 43 |
| Doublons supprimés | 1 | 1 | 1 |
| Lignes acceptées | 23 | 33 | 34 |
| Lignes rejetées | 13 | 11 | 8 |
| Contrats acceptés | 16 | 16 | 16 |
| Anomalies | 1 | 1 | 1 |
| Taux de rejet | 36,11 % | 25 % | 19,05 % |
| Statut | CHARGE | CHARGE | CHARGE |

Après ces trois chargements, la base de test contient 104 contrats, 199 lignes et 6 lots journalisés.

**Précision sur la surveillance :** les trois lots étaient déjà publiés au démarrage du surveillant. Le test valide leur traitement successif par une seule instance, mais pas encore leur détection en temps réel pendant leur génération.

### Vérification manuelle du montant d'un contrat

Le contrat 2 comporte trois lignes :

- 3 × 1 × 134,00 = 402,00 MAD
- 2 × 3 × 126,00 = 756,00 MAD
- 4 × 4 × 283,00 = 4 528,00 MAD

Montant total : 402 + 756 + 4 528 = **5 686,00 MAD**.

Le total a été confirmé par une requête SQL utilisant `SUM(quantity * duration * unit_rate)`.

### Limites des tests à compléter

Le test de conflit d'identifiant a été bloqué avant les insertions et a laissé la base inchangée. Un test complémentaire a ensuite provoqué une erreur SQL après le début des écritures et confirmé le rollback transactionnel. Voir la section « Validation du rollback transactionnel — 19/11/2026 ».

La reprise après arrêt et redémarrage de la surveillance est validée. Voir la section « Reprise après arrêt et redémarrage ».

### Reprise après arrêt et redémarrage

Après le chargement des lots 4, 5 et 6, le processus de surveillance a été arrêté puis relancé avec `--une-fois`.

Le nouveau processus a reconnu les trois lots avec le statut `DEJA_CHARGE`. Le code de retour était `0`.

Les compteurs de la base de test sont restés inchangés après cette reprise :
- 104 contrats
- 199 lignes de contrat
- 6 lots journalisés

Ce test confirme la reprise après redémarrage sans réinsertion des lots déjà traités.

## Validation du rollback transactionnel — 19/11/2026

Un test spécifique a été réalisé dans la base isolée `campusequip_rollback_test`, initialement copiée depuis la base de test (104 contrats, 199 lignes, 6 lots journalisés).

Un déclencheur SQL temporaire `BEFORE INSERT` sur `contract_lines` a provoqué volontairement une exception pendant le chargement du lot 7, après l'insertion des contrats dans la transaction.

Résultats :
- Le lot contenait 41 lignes acceptables et 20 nouveaux contrats (identifiants 121 à 140).
- Le rapport a reçu le statut `FAILED`.
- L'erreur enregistrée était `ROLLBACK_TEST_INJECTED`.
- Après l'échec : 104 contrats, 199 lignes et 6 lots journalisés.
- Aucun contrat portant un identifiant compris entre 121 et 140 n'a été conservé.

La transaction a donc annulé les insertions de contrats précédant l'erreur sur les lignes. Le rapport d'échec a été conservé séparément.

Après le test, le déclencheur temporaire et sa fonction SQL ont été supprimés et leur absence vérifiée.

Cette preuve complète le test de conflit d'identifiant, qui était bloqué avant les insertions.
