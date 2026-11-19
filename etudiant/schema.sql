-- CampusEquip v2 : travail axe 1, dans une base dédiée neuve.
-- Vous devez créer les tables campus, sites, clients, categories, equipments,
-- contracts, contract_lines et ingestion_batches, avec leurs clés et contraintes.
-- Le sujet donne le grain, les relations, les limites et les règles commerciales.
-- Vous devez écrire vos requêtes dans un fichier analyses.sql distinct.

-- ============================================================
-- CAMPUS EQUIP V2
-- Axe 1 : modèle relationnel PostgreSQL
-- Base de données neuve et dédiée à une seule campagne
-- ============================================================

BEGIN;

-- 1. CAMPUS
CREATE TABLE campuses (
    campus_id INTEGER PRIMARY KEY CHECK (campus_id > 0),
    name TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) > 0)
);

-- 2. SITES / GUICHETS
CREATE TABLE sites (
    site_id INTEGER PRIMARY KEY CHECK (site_id > 0),
    campus_id INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (length(btrim(name)) > 0),

    CONSTRAINT fk_sites_campus
        FOREIGN KEY (campus_id)
        REFERENCES campuses(campus_id),

    CONSTRAINT uq_site_name_per_campus
        UNIQUE (campus_id, name)
);

-- 3. CLIENTS / ASSOCIATIONS
CREATE TABLE clients (
    client_id INTEGER PRIMARY KEY CHECK (client_id > 0),
    name TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) > 0)
);

-- 4. CATEGORIES
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY CHECK (category_id > 0),
    name TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) > 0),
    parent_id INTEGER,

    CONSTRAINT fk_categories_parent
        FOREIGN KEY (parent_id)
        REFERENCES categories(category_id),

    CONSTRAINT ck_category_not_own_parent
        CHECK (parent_id IS NULL OR parent_id <> category_id)
);

-- 5. EQUIPMENTS
CREATE TABLE equipments (
    equipment_id INTEGER PRIMARY KEY CHECK (equipment_id > 0),
    name TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) > 0),
    category_id INTEGER NOT NULL,

    CONSTRAINT fk_equipments_category
        FOREIGN KEY (category_id)
        REFERENCES categories(category_id)
);

-- 6. CONTRACTS
CREATE TABLE contracts (
    contract_id INTEGER PRIMARY KEY CHECK (contract_id > 0),
    client_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    start_date DATE NOT NULL,
    status TEXT NOT NULL,

    CONSTRAINT fk_contracts_client
        FOREIGN KEY (client_id)
        REFERENCES clients(client_id),

    CONSTRAINT fk_contracts_site
        FOREIGN KEY (site_id)
        REFERENCES sites(site_id),

    CONSTRAINT ck_contract_status
        CHECK (status IN ('paid', 'closed', 'draft', 'cancelled'))
);

-- 7. CONTRACT LINES
CREATE TABLE contract_lines (
    contract_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    equipment_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 100),
    unit TEXT NOT NULL,
    duration INTEGER NOT NULL,
    unit_rate NUMERIC NOT NULL,

    CONSTRAINT pk_contract_lines
        PRIMARY KEY (contract_id, line_no),

    CONSTRAINT fk_lines_contract
        FOREIGN KEY (contract_id)
        REFERENCES contracts(contract_id),

    CONSTRAINT fk_lines_equipment
        FOREIGN KEY (equipment_id)
        REFERENCES equipments(equipment_id),

    CONSTRAINT ck_line_unit_duration
        CHECK (
            (unit = 'hour' AND duration BETWEEN 1 AND 720)
            OR
            (unit = 'day' AND duration BETWEEN 1 AND 365)
        ),

    CONSTRAINT ck_line_unit_rate
        CHECK (
            unit_rate >= 0
            AND unit_rate = ROUND(unit_rate, 2)
        )
);

-- 8. INGESTION BATCHES : JOURNAL DES LOTS
CREATE TABLE ingestion_batches (
    signature VARCHAR(64) PRIMARY KEY
        CHECK (signature ~ '^[0-9a-f]{64}$'),

    campaign_id UUID NOT NULL,
    batch_number INTEGER NOT NULL CHECK (batch_number > 0),
    rules_version TEXT NOT NULL,

    locations_sha256 VARCHAR(64) NOT NULL
        CHECK (locations_sha256 ~ '^[0-9a-f]{64}$'),

    referentiels_sha256 VARCHAR(64) NOT NULL
        CHECK (referentiels_sha256 ~ '^[0-9a-f]{64}$'),

    raw_rows INTEGER NOT NULL CHECK (raw_rows >= 0),
    duplicates_removed INTEGER NOT NULL CHECK (duplicates_removed >= 0),
    accepted_rows INTEGER NOT NULL CHECK (accepted_rows >= 0),
    rejected_rows INTEGER NOT NULL CHECK (rejected_rows >= 0),
    accepted_contracts INTEGER NOT NULL CHECK (accepted_contracts >= 0),
    anomaly_rows INTEGER NOT NULL CHECK (anomaly_rows >= 0),

    reject_rate NUMERIC(8,6) NOT NULL
        CHECK (reject_rate BETWEEN 0 AND 1),

    report JSONB NOT NULL,

    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_campaign_batch
        UNIQUE (campaign_id, batch_number)
);

COMMIT;
