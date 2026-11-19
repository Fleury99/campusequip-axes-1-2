"""Traitement contrôlé des lots CampusEquip v2 (axes 1 et 2)."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

RULES_VERSION = "campusequip-v2.0"
COLUMNS = [
    "contract_id", "client_id", "site_id", "start_date", "status",
    "line_no", "equipment_id", "quantity", "unit", "duration", "unit_rate",
]
STATUSES = {"paid", "closed", "draft", "cancelled"}
UNITS = {"hour", "day"}


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Fichier de configuration absent : {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_campaign_config(path: Path, campaign_id: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    output = []
    for line in lines:
        if line.strip().startswith("CAMPAIGN_ID="):
            output.append(f"CAMPAIGN_ID={campaign_id}")
            updated = True
        else:
            output.append(line)
    if not updated:
        output.append(f"CAMPAIGN_ID={campaign_id}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _save_attempt(root: Path, folder: Path, report: dict[str, Any],
                  quarantine: list[dict[str, Any]], duplicates: list[dict[str, Any]],
                  anomalies: list[dict[str, Any]]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = root / "rapports" / folder.name / stamp
    _write_json(out / "report.json", report)
    _write_jsonl(out / "quarantaine.jsonl", quarantine)
    _write_jsonl(out / "doublons.jsonl", duplicates)
    _write_jsonl(out / "anomalies.jsonl", anomalies)
    return out


def _positive_int(value: str, field: str, maximum: int | None = None) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ValueError(f"INVALID_{field.upper()}")
    number = int(value)
    if number < 1 or (maximum is not None and number > maximum):
        raise ValueError(f"INVALID_{field.upper()}")
    return number


def _parse_row(raw: dict[str, str], refs: dict[str, set[int]]) -> tuple[dict[str, Any], list[str]]:
    row = {key: (raw[key].strip() if raw[key] is not None else "") for key in COLUMNS}
    row["status"] = row["status"].lower()
    row["unit"] = row["unit"].lower()
    parsed: dict[str, Any] = {}
    reasons: list[str] = []

    integer_fields = {
        "contract_id": None, "client_id": None, "site_id": None,
        "line_no": None, "equipment_id": None, "quantity": 100,
    }
    for field, maximum in integer_fields.items():
        try:
            parsed[field] = _positive_int(row[field], field, maximum)
        except ValueError:
            reasons.append(f"INVALID_{field.upper()}")

    if "client_id" in parsed and parsed["client_id"] not in refs["clients"]:
        reasons.append("UNKNOWN_CLIENT")
    if "site_id" in parsed and parsed["site_id"] not in refs["sites"]:
        reasons.append("UNKNOWN_SITE")
    if "equipment_id" in parsed and parsed["equipment_id"] not in refs["equipment"]:
        reasons.append("UNKNOWN_EQUIPMENT")

    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["start_date"]) is None:
            raise ValueError
        parsed["start_date"] = date.fromisoformat(row["start_date"])
    except ValueError:
        reasons.append("INVALID_DATE")

    if row["status"] not in STATUSES:
        reasons.append("INVALID_STATUS")
    else:
        parsed["status"] = row["status"]

    if row["unit"] not in UNITS:
        reasons.append("INVALID_UNIT")
    else:
        parsed["unit"] = row["unit"]

    try:
        duration = _positive_int(row["duration"], "duration")
        max_duration = 720 if row["unit"] == "hour" else 365
        if row["unit"] in UNITS and duration > max_duration:
            raise ValueError
        parsed["duration"] = duration
    except ValueError:
        reasons.append("INVALID_DURATION")

    try:
        if re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", row["unit_rate"]) is None:
            raise ValueError
        amount = Decimal(row["unit_rate"])
        if not amount.is_finite() or amount < Decimal("0"):
            raise ValueError
        parsed["unit_rate"] = amount
    except (ValueError, InvalidOperation):
        reasons.append("INVALID_UNIT_RATE")

    # Les valeurs normalisées sont conservées pour comparer les en-têtes et les clés.
    parsed["_normalized"] = row
    return parsed, reasons


def _load_input(folder: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
    if not (folder / "READY").is_file() or (folder / "READY").read_text(encoding="utf-8").strip() != "campusequip-v2":
        raise ValueError("Marqueur READY absent ou invalide")
    if manifest.get("schema_version") != "campusequip-v2":
        raise ValueError("Version de lot incompatible")
    expected_files = {"locations.csv", "referentiels.json"}
    if set(manifest.get("files", {})) != expected_files:
        raise ValueError("Le manifeste doit décrire locations.csv et referentiels.json")

    locations_path = folder / "locations.csv"
    refs_path = folder / "referentiels.json"
    locations_hash = _sha256(locations_path)
    refs_hash = _sha256(refs_path)
    if locations_hash != manifest["files"]["locations.csv"]:
        raise ValueError("Empreinte SHA-256 incorrecte : locations.csv")
    if refs_hash != manifest["files"]["referentiels.json"]:
        raise ValueError("Empreinte SHA-256 incorrecte : referentiels.json")

    refs = json.loads(refs_path.read_text(encoding="utf-8"))
    if refs.get("schema_version") != "campusequip-v2":
        raise ValueError("Version des référentiels incompatible")
    for key in ("campuses", "sites", "clients", "categories", "equipment"):
        if not isinstance(refs.get(key), list):
            raise ValueError(f"Référentiel absent ou invalide : {key}")

    with locations_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != COLUMNS:
            raise ValueError("Structure CSV invalide : colonnes absentes, supplémentaires ou mauvais ordre")
        raw_rows: list[dict[str, Any]] = []
        for source_row, values in enumerate(reader, start=2):
            if len(values) != len(COLUMNS):
                raise ValueError(f"Structure CSV invalide à la ligne {source_row} : 11 champs attendus")
            raw_rows.append({"source_row": source_row, "raw": dict(zip(COLUMNS, values))})

    if len(raw_rows) != manifest.get("rows"):
        raise ValueError("Nombre de lignes CSV différent du manifeste")
    return raw_rows, refs, locations_hash, refs_hash


def traiter_lot(dossier, manifeste):
    """Valide un lot, met les contrats incohérents en quarantaine et charge atomiquement.

    Retourne CHARGE, DEJA_CHARGE ou REJETE_STRUCTURE. Les erreurs de base et
    les conflits inter-lots sont levés pour rester visibles dans surveiller.py.
    """
    folder = Path(dossier).resolve()
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    duplicates: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []

    try:
        raw_rows, references, locations_hash, refs_hash = _load_input(folder, manifeste)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        report = {
            "status": "REJETE_STRUCTURE", "rules_version": RULES_VERSION,
            "lot": folder.name, "error": str(exc), "raw_rows": 0,
            "duplicates_removed": 0, "accepted_rows": 0, "rejected_rows": 0,
            "accepted_contracts": 0, "anomaly_rows": 0, "reject_rate": 0.0,
        }
        report_dir = _save_attempt(root, folder, report, quarantine, duplicates, anomalies)
        return {"status": "REJETE_STRUCTURE", "report": str(report_dir)}

    signature_source = f"{locations_hash}:{refs_hash}:{RULES_VERSION}".encode("utf-8")
    signature = hashlib.sha256(signature_source).hexdigest()

    # Normaliser, puis retirer uniquement les répétitions entièrement identiques.
    unique_rows: list[dict[str, Any]] = []
    first_seen: dict[tuple[str, ...], int] = {}
    for item in raw_rows:
        normalized = {k: (v.strip() if v is not None else "") for k, v in item["raw"].items()}
        normalized["status"] = normalized["status"].lower()
        normalized["unit"] = normalized["unit"].lower()
        key = tuple(normalized[column] for column in COLUMNS)
        if key in first_seen:
            duplicates.append({
                "source_row": item["source_row"],
                "first_source_row": first_seen[key],
                "reason": "EXACT_DUPLICATE_AFTER_NORMALIZATION",
                "raw": item["raw"],
            })
            continue
        first_seen[key] = item["source_row"]
        unique_rows.append({"source_row": item["source_row"], "raw": item["raw"], "normalized": normalized})

    ref_sets = {
        "clients": {int(r["client_id"]) for r in references["clients"]},
        "sites": {int(r["site_id"]) for r in references["sites"]},
        "equipment": {int(r["equipment_id"]) for r in references["equipment"]},
    }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ungrouped: list[dict[str, Any]] = []
    for item in unique_rows:
        parsed, reasons = _parse_row(item["normalized"], ref_sets)
        item["parsed"] = parsed
        item["reasons"] = reasons
        contract_id = parsed.get("contract_id")
        if contract_id is None:
            ungrouped.append(item)
        else:
            groups[str(contract_id)].append(item)

    accepted_contracts: list[tuple[int, dict[str, Any], list[dict[str, Any]]]] = []
    for contract_key, items in groups.items():
        # Cohérence de l'en-tête sur les valeurs normalisées.
        headers = {
            (
                item["parsed"].get("client_id", item["normalized"]["client_id"]),
                item["parsed"].get("site_id", item["normalized"]["site_id"]),
                item["parsed"].get("start_date", item["normalized"]["start_date"]),
                item["parsed"].get("status", item["normalized"]["status"]),
            )
            for item in items
        }
        header_conflict = len(headers) > 1

        # Une clé de ligne répétée après dédoublonnage est nécessairement conflictuelle.
        line_numbers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            parsed_line_no = item["parsed"].get("line_no")
            line_key = f"int:{parsed_line_no}" if parsed_line_no is not None else f"raw:{item['normalized']['line_no']}"
            line_numbers[line_key].append(item)
        conflict_line_rows = {
            id(item)
            for same_key_rows in line_numbers.values() if len(same_key_rows) > 1
            for item in same_key_rows
        }
        line_conflict = bool(conflict_line_rows)
        has_invalid_row = any(item["reasons"] for item in items)
        invalid_contract = header_conflict or line_conflict or has_invalid_row

        if invalid_contract:
            for item in items:
                reasons = list(item["reasons"])
                if header_conflict:
                    reasons.append("CONTRACT_HEADER_CONFLICT")
                if id(item) in conflict_line_rows:
                    reasons.append("LINE_KEY_CONFLICT")
                if not reasons:
                    reasons.append("CONTRACT_QUARANTINED")
                quarantine.append({
                    "source_row": item["source_row"],
                    "contract_id": contract_key,
                    "raw": item["raw"],
                    "normalized": item["normalized"],
                    "reasons": sorted(set(reasons)),
                })
            continue

        contract_id = int(contract_key)
        header_item = items[0]["parsed"]
        contract_header = {
            "contract_id": contract_id,
            "client_id": header_item["client_id"],
            "site_id": header_item["site_id"],
            "start_date": header_item["start_date"],
            "status": header_item["status"],
        }
        accepted_lines = []
        for item in items:
            parsed = item["parsed"]
            accepted_lines.append({
                "contract_id": contract_id,
                "line_no": parsed["line_no"],
                "equipment_id": parsed["equipment_id"],
                "quantity": parsed["quantity"],
                "unit": parsed["unit"],
                "duration": parsed["duration"],
                "unit_rate": parsed["unit_rate"],
                "source_row": item["source_row"],
            })
            if parsed["quantity"] > 20:
                anomalies.append({
                    "source_row": item["source_row"],
                    "contract_id": contract_id,
                    "line_no": parsed["line_no"],
                    "reason": "QUANTITY_ABOVE_20",
                    "quantity": parsed["quantity"],
                })
        accepted_contracts.append((contract_id, contract_header, accepted_lines))

    for item in ungrouped:
        quarantine.append({
            "source_row": item["source_row"],
            "contract_id": item["normalized"].get("contract_id", ""),
            "raw": item["raw"],
            "normalized": item["normalized"],
            "reasons": item["reasons"] or ["INVALID_CONTRACT_ID"],
        })

    accepted_rows = sum(len(lines) for _, _, lines in accepted_contracts)
    rejected_rows = len(quarantine)
    deduplicated_rows = len(unique_rows)
    reject_rate = rejected_rows / deduplicated_rows if deduplicated_rows else 0.0
    report: dict[str, Any] = {
        "status": "PREPARE", "rules_version": RULES_VERSION,
        "campaign_id": manifeste["campaign_id"],
        "batch_number": int(manifeste["batch_number"]),
        "input_signature": signature,
        "locations_sha256": locations_hash,
        "referentiels_sha256": refs_hash,
        "raw_rows": len(raw_rows),
        "duplicates_removed": len(duplicates),
        "deduplicated_rows": deduplicated_rows,
        "accepted_rows": accepted_rows,
        "rejected_rows": rejected_rows,
        "accepted_contracts": len(accepted_contracts),
        "anomaly_rows": len(anomalies),
        "reject_rate": round(reject_rate, 6),
        "alerts": ["HIGH_REJECT_RATE"] if reject_rate > 0.20 else [],
    }

    config = _read_env(env_path)
    conninfo = {
        "host": "127.0.0.1", "port": 5434,
        "dbname": config["POSTGRES_DB"],
        "user": config["POSTGRES_USER"],
        "password": config["POSTGRES_PASSWORD"],
    }
    campaign_id = str(manifeste["campaign_id"])
    if config.get("CAMPAIGN_ID") and config["CAMPAIGN_ID"] != campaign_id:
        raise RuntimeError("CAMPAIGN_CONFLICT: une autre campagne est configurée pour cette base")

    try:
        with psycopg.connect(**conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT campaign_id, referentiels_sha256 FROM ingestion_batches")
                prior_batches = cur.fetchall()
                if any(str(existing_campaign) != campaign_id for existing_campaign, _ in prior_batches):
                    raise RuntimeError("CAMPAIGN_CONFLICT: cette base contient déjà une autre campagne")
                if any(existing_refs != refs_hash for _, existing_refs in prior_batches):
                    raise RuntimeError("REFERENCE_CONFLICT: les référentiels ont changé dans une campagne")

                cur.execute("SELECT 1 FROM ingestion_batches WHERE signature = %s", (signature,))
                if cur.fetchone():
                    report["status"] = "DEJA_CHARGE"
                    report_dir = _save_attempt(root, folder, report, quarantine, duplicates, anomalies)
                    return {"status": "DEJA_CHARGE", "input_signature": signature,
                            "report": str(report_dir), "accepted_rows": accepted_rows}

                # Les référentiels doivent être présents dans les tables cibles.
                for table, id_col, expected in [
                    ("campuses", "campus_id", 6), ("sites", "site_id", 12),
                    ("clients", "client_id", 2000), ("categories", "category_id", 6),
                    ("equipments", "equipment_id", 120),
                ]:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    actual = cur.fetchone()[0]
                    if actual != expected:
                        raise RuntimeError(f"REFERENTIALS_NOT_READY: {table}={actual}, attendu {expected}")

                # Un identifiant de contrat déjà chargé dans un autre lot interdit tout le nouveau lot.
                contract_ids = [contract_id for contract_id, _, _ in accepted_contracts]
                if contract_ids:
                    cur.execute(
                        "SELECT contract_id FROM contracts WHERE contract_id = ANY(%s)",
                        (contract_ids,),
                    )
                    conflicts = [row[0] for row in cur.fetchall()]
                    if conflicts:
                        raise RuntimeError(f"ORDER_ID_CONFLICT: contrats déjà chargés : {conflicts[:10]}")

                cur.executemany(
                    "INSERT INTO contracts (contract_id, client_id, site_id, start_date, status) VALUES (%s, %s, %s, %s, %s)",
                    [(
                        header["contract_id"], header["client_id"], header["site_id"],
                        header["start_date"], header["status"],
                    ) for _, header, _ in accepted_contracts],
                ) if accepted_contracts else None

                line_values = [
                    (line["contract_id"], line["line_no"], line["equipment_id"],
                     line["quantity"], line["unit"], line["duration"], line["unit_rate"])
                    for _, _, lines in accepted_contracts for line in lines
                ]
                if line_values:
                    cur.executemany(
                        """INSERT INTO contract_lines
                        (contract_id, line_no, equipment_id, quantity, unit, duration, unit_rate)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        line_values,
                    )

                report["status"] = "CHARGE"
                cur.execute(
                    """INSERT INTO ingestion_batches
                    (signature, campaign_id, batch_number, rules_version,
                     locations_sha256, referentiels_sha256, raw_rows,
                     duplicates_removed, accepted_rows, rejected_rows,
                     accepted_contracts, anomaly_rows, reject_rate, report)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        signature, campaign_id, int(manifeste["batch_number"]), RULES_VERSION,
                        locations_hash, refs_hash, len(raw_rows), len(duplicates),
                        accepted_rows, rejected_rows, len(accepted_contracts),
                        len(anomalies), Decimal(str(round(reject_rate, 6))), Jsonb(report),
                    ),
                )

        # La base est commitée : mémoriser aussi la campagne dans la configuration locale.
        _write_campaign_config(env_path, campaign_id)
        report_dir = _save_attempt(root, folder, report, quarantine, duplicates, anomalies)
        return {
            "status": "CHARGE", "input_signature": signature,
            "raw_rows": len(raw_rows), "duplicates_removed": len(duplicates),
            "accepted_rows": accepted_rows, "rejected_rows": rejected_rows,
            "accepted_contracts": len(accepted_contracts), "anomaly_rows": len(anomalies),
            "reject_rate": round(reject_rate, 6), "report": str(report_dir),
        }

    except Exception as exc:
        report["status"] = "FAILED"
        report["load_error"] = f"{type(exc).__name__}: {exc}"
        _save_attempt(root, folder, report, quarantine, duplicates, anomalies)
        raise
