from pathlib import Path
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import psycopg


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
SQL_FILE = ROOT / "analyses.sql"
OUTPUT_DIR = ROOT / "rapports"


def load_env(path):
    """Charge les paramètres locaux sans afficher les mots de passe."""
    if not path.exists():
        raise FileNotFoundError(f"Fichier .env introuvable : {path}")

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def read_analysis_queries(path):
    """Récupère les trois requêtes depuis analyses.sql."""
    content = path.read_text(encoding="utf-8")
    markers = ["-- ANALYSE 1", "-- ANALYSE 2", "-- ANALYSE 3"]
    queries = []

    for index, marker in enumerate(markers):
        start = content.find(marker)
        if start == -1:
            raise ValueError(f"Marqueur manquant dans analyses.sql : {marker}")

        next_start = (
            content.find(markers[index + 1], start + len(marker))
            if index + 1 < len(markers)
            else len(content)
        )
        section = content[start:next_start]

        match = re.search(r"(?im)^\s*(WITH|SELECT)\b", section)
        if not match:
            raise ValueError(f"Requête SQL introuvable pour {marker}")

        query_text = section[match.start():]
        semicolon = query_text.find(";")
        if semicolon == -1:
            raise ValueError(f"Point-virgule final absent pour {marker}")

        queries.append(query_text[:semicolon + 1])

    return queries


def execute_query(connection, query):
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [column.name for column in cursor.description]
        rows = cursor.fetchall()

    return pd.DataFrame(rows, columns=columns)


def mad(value):
    return f"{float(value):,.2f} MAD".replace(",", " ")


def main():
    load_env(ENV_FILE)

    required = ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(
            "Paramètres absents du fichier .env : " + ", ".join(missing)
        )

    queries = read_analysis_queries(SQL_FILE)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    connection_parameters = {
        "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "port": int(os.getenv("POSTGRES_PORT", "5434")),
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "connect_timeout": 10,
    }

    print("Connexion à PostgreSQL...")
    with psycopg.connect(**connection_parameters) as connection:
        print("Exécution des trois analyses SQL...")
        analysis_1 = execute_query(connection, queries[0])
        analysis_2 = execute_query(connection, queries[1])
        analysis_3 = execute_query(connection, queries[2])

        verification = execute_query(
            connection,
            """
            SELECT
                COUNT(*) AS nombre_lignes,
                COUNT(DISTINCT ct.contract_id) AS nombre_contrats,
                COALESCE(
                    SUM(cl.quantity * cl.duration * cl.unit_rate), 0
                ) AS chiffre_affaires
            FROM contracts ct
            JOIN contract_lines cl
                ON cl.contract_id = ct.contract_id
            WHERE ct.status IN ('paid', 'closed')
              AND ct.start_date BETWEEN DATE '2026-11-01'
                                    AND DATE '2026-11-21';
            """,
        )

    # Export des trois analyses.
    exports = [
        (analysis_1, "analyse_1_montants_quotidiens.csv"),
        (analysis_2, "analyse_2_classement_equipements.csv"),
        (analysis_3, "analyse_3_locations_par_unite.csv"),
    ]

    for dataframe, filename in exports:
        dataframe.to_csv(
            OUTPUT_DIR / filename,
            index=False,
            encoding="utf-8-sig",
        )

    # Chiffre d'affaires cumulé par campus.
    ca_campus = (
        analysis_1.groupby("campus", as_index=False)["montant_journalier"]
        .sum()
        .sort_values("montant_journalier", ascending=False)
    )

    # Génération du graphique.
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(
        ca_campus["campus"],
        ca_campus["montant_journalier"].astype(float),
    )
    ax.set_title("Chiffre d'affaires par campus")
    ax.set_xlabel("Campus")
    ax.set_ylabel("Chiffre d'affaires (MAD)")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(
        OUTPUT_DIR / "graphique_ca_par_campus.png",
        dpi=160,
        bbox_inches="tight",
    )
    plt.close(fig)

    # Préparation de la synthèse.
    stats = verification.iloc[0]
    top_equipements = analysis_2.loc[
        analysis_2["rang"] == 1,
        ["campus", "equipement", "montant_total"],
    ]

    unite_totals = (
        analysis_3.groupby("unite", as_index=False)
        .agg(
            nombre_lignes=("nombre_lignes_retenues", "sum"),
            montant_total=("montant_total", "sum"),
        )
    )

    lignes = [
        "# Synthèse des analyses SQL — CampusEquip",
        "",
        "## Périmètre",
        "",
        "- Lots analysés : `lot_000001` et `lot_000002`.",
        "- Période : du 1er au 21 novembre 2026.",
        "- Statuts retenus : `paid` et `closed`.",
        "- Calcul du montant : quantité × durée × tarif unitaire.",
        "",
        "## Indicateurs généraux",
        "",
        f"- Nombre de lignes de location : **{int(stats['nombre_lignes'])}**.",
        f"- Nombre de contrats retenus : **{int(stats['nombre_contrats'])}**.",
        f"- Chiffre d'affaires total : **{mad(stats['chiffre_affaires'])}**.",
        "",
        "## Chiffre d'affaires par campus",
        "",
        "| Campus | Chiffre d'affaires |",
        "|---|---:|",
    ]

    for _, row in ca_campus.iterrows():
        lignes.append(
            f"| {row['campus']} | {mad(row['montant_journalier'])} |"
        )

    lignes += [
        "",
        "## Équipement le mieux classé par campus",
        "",
        "| Campus | Équipement | Montant |",
        "|---|---|---:|",
    ]

    for _, row in top_equipements.iterrows():
        lignes.append(
            f"| {row['campus']} | {row['equipement']} "
            f"| {mad(row['montant_total'])} |"
        )

    lignes += [
        "",
        "## Comparaison des unités de location",
        "",
        "| Unité | Nombre de lignes | Montant total |",
        "|---|---:|---:|",
    ]

    for _, row in unite_totals.iterrows():
        lignes.append(
            f"| {row['unite']} | {int(row['nombre_lignes'])} "
            f"| {mad(row['montant_total'])} |"
        )

    lignes += [
        "",
        "## Contrôle de cohérence",
        "",
        "Les indicateurs généraux sont calculés directement depuis "
        "PostgreSQL sur les contrats retenus. Les trois fichiers CSV "
        "reprennent les résultats des requêtes de `analyses.sql`.",
        "",
    ]

    (OUTPUT_DIR / "synthese_sql.md").write_text(
        "\n".join(lignes),
        encoding="utf-8",
    )

    print("\nExport terminé.")
    print(f"Lignes de location : {int(stats['nombre_lignes'])}")
    print(f"Contrats retenus   : {int(stats['nombre_contrats'])}")
    print(f"Chiffre d'affaires : {mad(stats['chiffre_affaires'])}")
    print(f"\nFichiers créés dans : {OUTPUT_DIR}")
    for path in sorted(OUTPUT_DIR.iterdir()):
        if path.is_file():
            print(f" - {path.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nERREUR : {error}")
        raise
