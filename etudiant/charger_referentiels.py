"""Import contrôlé des référentiels CampusEquip v2."""

import csv
import hashlib
import json
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[1]
LOT = ROOT / "exemples" / "lot_000001"
ENV_FILE = ROOT / ".env"

EXPECTED_COLUMNS = [
    "contract_id", "client_id", "site_id", "start_date",
    "status", "line_no", "equipment_id", "quantity",
    "unit", "duration", "unit_rate"
]

EXPECTED_COUNTS = {
    "campuses": 6,
    "sites": 12,
    "clients": 2000,
    "categories": 6,
    "equipment": 120,
}


def read_env(path):
    """Lire les variables du fichier .env sans afficher les secrets."""
    values = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_lot():
    """Contrôler l'intégrité et la structure du premier lot."""

    if not (LOT / "READY").is_file():
        raise ValueError("Marqueur READY absent.")

    if (LOT / "READY").read_text(encoding="utf-8").strip() != "campusequip-v2":
        raise ValueError("Contenu incorrect du marqueur READY.")

    manifest = json.loads(
        (LOT / "manifest.json").read_text(encoding="utf-8")
    )

    if manifest["schema_version"] != "campusequip-v2":
        raise ValueError("Version de schéma inconnue.")

    locations = LOT / "locations.csv"
    references_file = LOT / "referentiels.json"

    for filename, filepath in [
        ("locations.csv", locations),
        ("referentiels.json", references_file),
    ]:
        expected_hash = manifest["files"].get(filename)

        if expected_hash is None or sha256(filepath) != expected_hash:
            raise ValueError(f"Empreinte SHA-256 incorrecte : {filename}")

    with locations.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        rows = list(reader)

    if header != EXPECTED_COLUMNS:
        raise ValueError("Colonnes du CSV absentes, supplémentaires ou désordonnées.")

    if len(rows) != manifest["rows"]:
        raise ValueError("Nombre de lignes CSV différent du manifeste.")

    references = json.loads(
        references_file.read_text(encoding="utf-8")
    )

    if references["schema_version"] != manifest["schema_version"]:
        raise ValueError("Versions du manifeste et des référentiels différentes.")

    for name, expected in EXPECTED_COUNTS.items():
        actual = len(references[name])

        if actual != expected:
            raise ValueError(
                f"Nombre incorrect pour {name} : {actual}, attendu {expected}"
            )

    return references, manifest


def main():
    if not ENV_FILE.is_file():
        raise FileNotFoundError("Fichier .env absent.")

    config = read_env(ENV_FILE)
    references, manifest = validate_lot()

    connection = psycopg.connect(
        host="127.0.0.1",
        port=5434,
        dbname=config["POSTGRES_DB"],
        user=config["POSTGRES_USER"],
        password=config["POSTGRES_PASSWORD"],
    )

    with connection:
        with connection.cursor() as cur:

            # Protection : ne pas mélanger avec des données préexistantes.
            tables = [
                "campuses", "sites", "clients", "categories",
                "equipments", "contracts", "contract_lines",
                "ingestion_batches"
            ]

            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]

                if count != 0:
                    raise RuntimeError(
                        f"La table {table} contient déjà {count} lignes. "
                        "Import annulé pour protéger les données."
                    )

            # Insertion dans l'ordre des dépendances des clés étrangères.
            cur.executemany(
                "INSERT INTO campuses (campus_id, name) VALUES (%s, %s)",
                [
                    (r["campus_id"], r["name"])
                    for r in references["campuses"]
                ],
            )

            cur.executemany(
                "INSERT INTO sites (site_id, campus_id, name) VALUES (%s, %s, %s)",
                [
                    (r["site_id"], r["campus_id"], r["name"])
                    for r in references["sites"]
                ],
            )

            cur.executemany(
                "INSERT INTO clients (client_id, name) VALUES (%s, %s)",
                [
                    (r["client_id"], r["name"])
                    for r in references["clients"]
                ],
            )

            cur.executemany(
                """
                INSERT INTO categories (category_id, name, parent_id)
                VALUES (%s, %s, %s)
                """,
                [
                    (r["category_id"], r["name"], r["parent_id"])
                    for r in references["categories"]
                ],
            )

            cur.executemany(
                """
                INSERT INTO equipments (equipment_id, name, category_id)
                VALUES (%s, %s, %s)
                """,
                [
                    (r["equipment_id"], r["name"], r["category_id"])
                    for r in references["equipment"]
                ],
            )

            # Contrôle des nombres réellement enregistrés.
            for table, expected in [
                ("campuses", 6),
                ("sites", 12),
                ("clients", 2000),
                ("categories", 6),
                ("equipments", 120),
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                actual = cur.fetchone()[0]

                if actual != expected:
                    raise RuntimeError(
                        f"Contrôle échoué pour {table}: {actual}/{expected}"
                    )

    connection.close()

    print("PASS : référentiels importés dans PostgreSQL.")
    print("Campagne :", manifest["campaign_id"])
    print("Lot de référence :", manifest["batch_number"])
    print("Total des référentiels :", sum(EXPECTED_COUNTS.values()))
    print("Les autres tables métier restent vides.")


if __name__ == "__main__":
    main()
