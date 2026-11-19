
-- ============================================================
-- CAMPUS EQUIP V2
-- AXE 1 : TROIS ANALYSES SQL
-- Lots analysés : lot_000001 et lot_000002
-- Période : du 01/11/2026 au 21/11/2026
-- CA retenu : contrats paid et closed uniquement
-- Montant d'une ligne = quantity * duration * unit_rate
-- ============================================================


-- ============================================================
-- ANALYSE 1
-- Montant quotidien par campus et cumul des montants
-- Les jours sans vente doivent afficher 0.
-- ============================================================

WITH calendrier AS (
    SELECT generate_series(
        DATE '2026-11-01',
        DATE '2026-11-21',
        INTERVAL '1 day'
    )::date AS jour
),

ventes_journalieres AS (
    SELECT
        ca.campus_id,
        ca.name AS campus,
        ct.start_date AS jour,
        SUM(
            cl.quantity * cl.duration * cl.unit_rate
        ) AS montant_journalier

    FROM contracts ct
    JOIN sites s
        ON s.site_id = ct.site_id
    JOIN campuses ca
        ON ca.campus_id = s.campus_id
    JOIN contract_lines cl
        ON cl.contract_id = ct.contract_id

    WHERE ct.status IN ('paid', 'closed')
      AND ct.start_date BETWEEN DATE '2026-11-01'
                            AND DATE '2026-11-21'

    GROUP BY ca.campus_id, ca.name, ct.start_date
),

grille_complete AS (
    SELECT
        ca.campus_id,
        ca.name AS campus,
        cal.jour,
        COALESCE(v.montant_journalier, 0) AS montant_journalier

    FROM campuses ca
    CROSS JOIN calendrier cal

    LEFT JOIN ventes_journalieres v
        ON v.campus_id = ca.campus_id
       AND v.jour = cal.jour
)

SELECT
    campus_id,
    campus,
    jour,
    montant_journalier,
    SUM(montant_journalier) OVER (
        PARTITION BY campus_id
        ORDER BY jour
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumul_campus

FROM grille_complete
ORDER BY campus_id, jour;


-- ============================================================
-- ANALYSE 2
-- Classement des équipements par campus
-- DENSE_RANK permet de conserver les ex aequo.
-- ============================================================

WITH chiffre_affaires_equipement AS (
    SELECT
        ca.campus_id,
        ca.name AS campus,
        e.equipment_id,
        e.name AS equipement,

        SUM(
            cl.quantity * cl.duration * cl.unit_rate
        ) AS montant_total

    FROM contracts ct
    JOIN sites s
        ON s.site_id = ct.site_id
    JOIN campuses ca
        ON ca.campus_id = s.campus_id
    JOIN contract_lines cl
        ON cl.contract_id = ct.contract_id
    JOIN equipments e
        ON e.equipment_id = cl.equipment_id

    WHERE ct.status IN ('paid', 'closed')
      AND ct.start_date BETWEEN DATE '2026-11-01'
                            AND DATE '2026-11-21'

    GROUP BY
        ca.campus_id,
        ca.name,
        e.equipment_id,
        e.name
),

classement AS (
    SELECT
        campus_id,
        campus,
        equipment_id,
        equipement,
        montant_total,

        DENSE_RANK() OVER (
            PARTITION BY campus_id
            ORDER BY montant_total DESC
        ) AS rang

    FROM chiffre_affaires_equipement
)

SELECT
    campus_id,
    campus,
    equipment_id,
    equipement,
    montant_total,
    rang

FROM classement
ORDER BY campus_id, rang, equipement;


-- ============================================================
-- ANALYSE 3
-- Comparaison des locations à l'heure et à la journée
-- Nombre de lignes retenues et montant par campus et unité.
-- ============================================================

SELECT
    ca.campus_id,
    ca.name AS campus,
    cl.unit AS unite,

    COUNT(*) AS nombre_lignes_retenues,

    SUM(
        cl.quantity * cl.duration * cl.unit_rate
    ) AS montant_total

FROM contracts ct
JOIN sites s
    ON s.site_id = ct.site_id
JOIN campuses ca
    ON ca.campus_id = s.campus_id
JOIN contract_lines cl
    ON cl.contract_id = ct.contract_id

WHERE ct.status IN ('paid', 'closed')
  AND ct.start_date BETWEEN DATE '2026-11-01'
                        AND DATE '2026-11-21'

GROUP BY
    ca.campus_id,
    ca.name,
    cl.unit

ORDER BY ca.campus_id, cl.unit;

