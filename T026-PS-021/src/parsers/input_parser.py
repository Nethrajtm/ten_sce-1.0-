"""
src/parsers/input_parser.py
Parse JSON input files into domain model objects.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List

from src.models.borrower import Borrower, CoApplicant
from src.models.property import Property, StageItem


def parse_borrower_file(path: Path) -> List[Borrower]:
    """
    Parse a borrowers JSON file and return a list of Borrower objects.

    Expected structure:
    {
        "borrowers": [
            {
                "borrower_id": "B001",
                "name": "...",
                "dob": "YYYY-MM-DD",
                "gender": "M" | "F",
                "net_income_monthly": <number>,
                "credit_score": <int>,
                "coapplicant": {              # optional
                    "name": "...",
                    "income_monthly": <number>,
                    "relationship": "SPOUSE" | "OTHER"
                }
            }
        ]
    }
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    borrowers: List[Borrower] = []
    for b in data["borrowers"]:
        coa = None
        if b.get("coapplicant"):
            c = b["coapplicant"]
            coa = CoApplicant(
                name=c["name"],
                income_monthly=Decimal(str(c["income_monthly"])),
                relationship=c["relationship"],
            )
        dob = date.fromisoformat(b["dob"])
        borrowers.append(
            Borrower(
                borrower_id=b["borrower_id"],
                name=b["name"],
                dob=dob,
                gender=b["gender"],
                net_income_monthly=Decimal(str(b["net_income_monthly"])),
                credit_score=int(b["credit_score"]),
                coapplicant=coa,
            )
        )
    return borrowers


def parse_property_file(path: Path) -> List[Property]:
    """
    Parse a properties JSON file and return a list of Property objects.

    Expected structure:
    {
        "properties": [
            {
                "property_id": "P001",
                "agreement_value": <number>,
                "builder_name": "...",
                "stages": [
                    {"stage_name": "...", "percentage": <number>},
                    ...
                ]
            }
        ]
    }
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    properties: List[Property] = []
    for p in data["properties"]:
        stages = [
            StageItem(
                stage_name=s["stage_name"],
                percentage=Decimal(str(s["percentage"])),
            )
            for s in p.get("stages", [])
        ]
        properties.append(
            Property(
                property_id=p["property_id"],
                agreement_value=Decimal(str(p["agreement_value"])),
                builder_name=p["builder_name"],
                stages=stages,
            )
        )
    return properties


def parse_command_file(path: Path) -> List[dict]:
    """
    Parse a commands JSON file and return a list of command dicts.

    Expected structure:
    {
        "benchmark_rate": <number>,
        "commands": [
            {
                "command": "SANCTION",
                "date": "YYYY-MM-DD",
                "borrower_id": "B001",
                "property_id": "P001"
            }
        ]
    }

    Each returned dict merges the top-level benchmark_rate into every command.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    benchmark_rate = Decimal(str(data["benchmark_rate"]))
    commands: List[dict] = []
    for cmd in data["commands"]:
        entry = dict(cmd)
        entry["benchmark_rate"] = benchmark_rate
        entry["date"] = date.fromisoformat(cmd["date"])
        # Pre-parse STAGE_CERTIFIED.certification_date so callers always get a date object
        if entry.get("command", "").upper() == "STAGE_CERTIFIED":
            cd = entry.get("certification_date")
            if isinstance(cd, str):
                entry["certification_date"] = date.fromisoformat(cd)
        commands.append(entry)
    return commands


def parse_events_from_commands(commands: List[dict]) -> List[dict]:
    """
    Extract Phase 2 events from the commands list.
    Phase 2 command types: DEMAND, STAGE_CERTIFIED, OWN_CONTRIBUTION,
    BENCHMARK_CHANGE, MONTHLY_JOB, RECORD_EMI, PREPAYMENT_PART, PREPAYMENT_FULL.

    Each command dict already has "date" as a date object and "benchmark_rate" merged in.
    Returns the same list with Phase-2 fields coerced to the correct types.

    Additional fields by type:
    DEMAND           : loan_id, demand_amount (Decimal), stage_name, demand_pct (Decimal)
    STAGE_CERTIFIED  : loan_id, stage_name, certification_date (date)
    OWN_CONTRIBUTION : loan_id, amount (Decimal)
    BENCHMARK_CHANGE : new_benchmark (Decimal)
    MONTHLY_JOB      : (no extra fields beyond date/loan_id)
    RECORD_EMI       : loan_id, emi_no (int), amount (Decimal)
    PREPAYMENT_PART  : loan_id, amount (Decimal), reduce_tenure (bool, default True)
    PREPAYMENT_FULL  : loan_id, amount (Decimal)
    """
    PHASE2_TYPES = {
        "DEMAND", "STAGE_CERTIFIED", "OWN_CONTRIBUTION",
        "BENCHMARK_CHANGE", "MONTHLY_JOB", "RECORD_EMI",
        "PREPAYMENT_PART", "PREPAYMENT_FULL",
    }

    result: List[dict] = []
    for cmd in commands:
        cmd_type = cmd.get("command", "").upper()
        if cmd_type not in PHASE2_TYPES:
            continue

        entry = dict(cmd)

        # Coerce numeric and date fields per command type
        if cmd_type == "DEMAND":
            entry["demand_amount"] = Decimal(str(entry["demand_amount"]))
            entry["demand_pct"] = Decimal(str(entry["demand_pct"]))

        elif cmd_type == "STAGE_CERTIFIED":
            if isinstance(entry.get("certification_date"), str):
                entry["certification_date"] = date.fromisoformat(entry["certification_date"])

        elif cmd_type == "OWN_CONTRIBUTION":
            entry["amount"] = Decimal(str(entry["amount"]))

        elif cmd_type == "BENCHMARK_CHANGE":
            entry["new_benchmark"] = Decimal(str(entry["new_benchmark"]))

        elif cmd_type == "RECORD_EMI":
            entry["emi_no"] = int(entry["emi_no"])
            entry["amount"] = Decimal(str(entry["amount"]))

        elif cmd_type in ("PREPAYMENT_PART", "PREPAYMENT_FULL"):
            entry["amount"] = Decimal(str(entry["amount"]))
            if cmd_type == "PREPAYMENT_PART":
                entry["reduce_tenure"] = bool(entry.get("reduce_tenure", True))

        result.append(entry)

    return result
