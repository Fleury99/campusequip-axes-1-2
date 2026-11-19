# Synthèse des analyses SQL — CampusEquip

## Périmètre

- Lots analysés : `lot_000001` et `lot_000002`.
- Période : du 1er au 21 novembre 2026.
- Statuts retenus : `paid` et `closed`.
- Calcul du montant : quantité × durée × tarif unitaire.

## Indicateurs généraux

- Nombre de lignes de location : **44**.
- Nombre de contrats retenus : **21**.
- Chiffre d'affaires total : **48 098.00 MAD**.

## Chiffre d'affaires par campus

| Campus | Chiffre d'affaires |
|---|---:|
| Campus Rabat | 10 805.00 MAD |
| Campus Agadir | 10 705.00 MAD |
| Campus Tanger | 9 748.00 MAD |
| Campus Marrakech | 8 043.00 MAD |
| Campus Casablanca | 6 941.00 MAD |
| Campus Fès | 1 856.00 MAD |

## Équipement le mieux classé par campus

| Campus | Équipement | Montant |
|---|---|---:|
| Campus Casablanca | Équipement 117 | 1 740.00 MAD |
| Campus Rabat | Équipement 077 | 5 760.00 MAD |
| Campus Fès | Équipement 105 | 1 856.00 MAD |
| Campus Marrakech | Équipement 049 | 5 900.00 MAD |
| Campus Tanger | Équipement 106 | 2 680.00 MAD |
| Campus Agadir | Équipement 055 | 4 528.00 MAD |

## Comparaison des unités de location

| Unité | Nombre de lignes | Montant total |
|---|---:|---:|
| day | 22 | 40 300.00 MAD |
| hour | 22 | 7 798.00 MAD |

## Contrôle de cohérence

Les indicateurs généraux sont calculés directement depuis PostgreSQL sur les contrats retenus. Les trois fichiers CSV reprennent les résultats des requêtes de `analyses.sql`.
