"""
main.py — Entry point for Home Loan Servicing Engine (Phase 1 + Phase 2)
Team T026 / PS-021

Usage:
    py main.py --borrowers data/sample/borrowers.json \\
               --properties data/sample/properties.json \\
               --commands data/sample/commands.json \\
               --output output_files/

    # Phase 2 (with events):
    py main.py --borrowers data/sample/borrowers.json \\
               --properties data/sample/properties.json \\
               --commands data/sample/commands_phase2.json \\
               --output output_files/ \\
               --fy-year 2024
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# Force UTF-8 on Windows consoles so Rs and other Unicode prints cleanly.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from src.parsers.input_parser import (
    parse_borrower_file,
    parse_property_file,
    parse_command_file,
    parse_events_from_commands,
)
from src.calculations.sanction import process_sanction
from src.models.loan import LoanAccount
from src.engine.loan_engine import LoanEngine
from src.output.sanction_letter import generate_sanction_letter
from src.output.report_writer import write_sanction_letter, write_json_output
from src.output.ledger_writer import write_phase2_outputs


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Home Loan Servicing Engine — Team T026 / PS-021"
    )
    p.add_argument("--borrowers",   required=True, help="Path to borrowers JSON file")
    p.add_argument("--properties",  required=True, help="Path to properties JSON file")
    p.add_argument("--commands",    required=True, help="Path to commands JSON file")
    p.add_argument("--output",      required=True, help="Output directory")
    p.add_argument("--fy-year",     type=int, default=2024,
                   help="Financial year start for interest certificates (default: 2024)")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    output_dir    = Path(args.output)
    borrowers_path = Path(args.borrowers)
    properties_path = Path(args.properties)
    commands_path  = Path(args.commands)
    fy_year        = args.fy_year

    # ── Load master data ──────────────────────────────────────────────────
    print("Loading input files…")
    borrowers  = {b.borrower_id: b for b in parse_borrower_file(borrowers_path)}
    properties = {p.property_id: p for p in parse_property_file(properties_path)}
    commands   = parse_command_file(commands_path)
    print(f"  Borrowers loaded  : {len(borrowers)}")
    print(f"  Properties loaded : {len(properties)}")
    print(f"  Commands loaded   : {len(commands)}")
    print()

    # ── Runtime state: loan_id -> LoanEngine ─────────────────────────────
    engines: dict[str, LoanEngine] = {}
    loan_registry: dict[str, LoanAccount] = {}
    loan_borrower_map: dict[str, str] = {}   # loan_id -> borrower_id
    loan_property_map: dict[str, str] = {}   # loan_id -> property_id
    results_summary = []
    success_count = 0
    error_count   = 0

    # ── Process commands ──────────────────────────────────────────────────
    for idx, cmd in enumerate(commands, start=1):
        command_type = cmd.get("command", "").upper()
        if cmd.get("comment"):
            pass  # ignore comment fields silently

        # ── SANCTION ───────────────────────────────────────────────────
        if command_type == "SANCTION":
            borrower_id  = cmd["borrower_id"]
            property_id  = cmd["property_id"]
            benchmark_rt = cmd["benchmark_rate"]
            sanction_dt  = cmd["date"]

            if borrower_id not in borrowers:
                print(f"  [ERROR] Command {idx}: Borrower '{borrower_id}' not found.")
                error_count += 1
                continue
            if property_id not in properties:
                print(f"  [ERROR] Command {idx}: Property '{property_id}' not found.")
                error_count += 1
                continue

            borrower  = borrowers[borrower_id]
            property_ = properties[property_id]

            try:
                result = process_sanction(
                    borrower=borrower,
                    property_=property_,
                    benchmark_rate=benchmark_rt,
                    sanction_date=sanction_dt,
                )

                # Build LoanAccount and engine
                loan_acct = LoanAccount.from_sanction_result(result)
                engine    = LoanEngine(
                    loan=loan_acct,
                    borrower=borrower,
                    property_=property_,
                    benchmark_rate=benchmark_rt,
                )
                engines[result.loan_id]          = engine
                loan_registry[result.loan_id]    = loan_acct
                loan_borrower_map[result.loan_id] = borrower_id
                loan_property_map[result.loan_id] = property_id

                # Generate and save sanction letter
                letter     = generate_sanction_letter(result, borrower, property_)
                letter_path = write_sanction_letter(letter, output_dir, result.loan_id)

                # Save JSON summary
                summary = {
                    "loan_id":             result.loan_id,
                    "borrower_id":         result.borrower_id,
                    "property_id":         result.property_id,
                    "sanctioned_amount":   str(result.sanctioned_amount),
                    "tenure_months":       result.tenure_months,
                    "interest_rate":       str(result.interest_rate),
                    "ltv_limit":           str(result.ltv_limit),
                    "eligibility_limit":   str(result.eligibility_limit),
                    "processing_fee_total": str(result.processing_fee["total_fee"]),
                    "sanction_date":       str(result.sanction_date),
                    "expiry_date":         str(result.expiry_date),
                    "status":              result.status,
                    "rules_applied":       result.rule_ids_applied,
                }
                write_json_output(summary, output_dir, f"{result.loan_id}_summary.json")
                results_summary.append(summary)
                success_count += 1

                print(f"  [{idx}] SANCTION — {result.loan_id}")
                print(f"        Borrower  : {borrower.name} ({borrower_id})")
                print(f"        Property  : {property_.builder_name} ({property_id})")
                print(f"        Amount    : Rs {result.sanctioned_amount:,.2f}")
                print(f"        Tenure    : {result.tenure_months} months")
                print(f"        Rate      : {result.interest_rate}% p.a.")
                print(f"        Expiry    : {result.expiry_date}")
                print(f"        Letter    : {letter_path}")
                print()

            except Exception as exc:
                print(f"  [ERROR] Command {idx} ({borrower_id}/{property_id}): {exc}")
                error_count += 1

        # ── Phase 2 events ─────────────────────────────────────────────
        elif command_type in ("OWN_CONTRIBUTION", "STAGE_CERTIFIED", "DEMAND",
                              "BENCHMARK_CHANGE", "MONTHLY_JOB", "RECORD_EMI",
                              "PREPAYMENT_PART", "PREPAYMENT_FULL"):
            loan_id  = cmd.get("loan_id", "")
            ev_date  = cmd["date"]

            # BENCHMARK_CHANGE applies to all active engines
            if command_type == "BENCHMARK_CHANGE":
                new_bm = Decimal(str(cmd["new_benchmark"]))
                for eng in engines.values():
                    eng.process_benchmark_change(ev_date, new_bm)
                print(f"  [{idx}] BENCHMARK_CHANGE: new rate {new_bm}% (effective 1st of next month)")
                continue

            # All other Phase 2 events require a loan_id
            if loan_id not in engines:
                print(f"  [WARN] Command {idx}: Loan '{loan_id}' not found — skipped.")
                continue

            eng = engines[loan_id]

            if command_type == "OWN_CONTRIBUTION":
                amount = Decimal(str(cmd["amount"]))
                eng.process_own_contribution(ev_date, amount)
                print(f"  [{idx}] OWN_CONTRIBUTION {loan_id}: Rs {amount:,.2f}")

            elif command_type == "STAGE_CERTIFIED":
                stage     = cmd["stage_name"]
                cert_date = cmd.get("certification_date", ev_date)
                if isinstance(cert_date, str):
                    cert_date = date.fromisoformat(cert_date)
                eng.process_stage_certified(ev_date, stage, cert_date)
                print(f"  [{idx}] STAGE_CERTIFIED {loan_id}: {stage} on {cert_date}")

            elif command_type == "DEMAND":
                demand_amt = Decimal(str(cmd["demand_amount"]))
                stage      = cmd["stage_name"]
                demand_pct = Decimal(str(cmd["demand_pct"]))
                rec = eng.process_demand(ev_date, ev_date, demand_amt, stage, demand_pct)
                status_icon = "✓" if rec.decision in ("RELEASED", "PARTIAL") else "✗"
                print(f"  [{idx}] DEMAND {loan_id}: {stage} Rs {demand_amt:,.2f} → {status_icon} {rec.decision} Rs {rec.amount:,.2f}")
                if rec.decision == "REJECTED":
                    print(f"         Reason: {rec.reason}")

            elif command_type == "MONTHLY_JOB":
                eng.run_monthly_job(ev_date)
                bills = len(eng.loan.pre_emi_bills)
                print(f"  [{idx}] MONTHLY_JOB {loan_id}: {ev_date} (pre-EMI bills: {bills})")

            elif command_type == "RECORD_EMI":
                emi_no = int(cmd["emi_no"])
                amount = Decimal(str(cmd["amount"]))
                eng.record_emi_payment(ev_date, emi_no, amount)
                print(f"  [{idx}] RECORD_EMI {loan_id}: EMI #{emi_no} Rs {amount:,.2f}")

            elif command_type == "PREPAYMENT_PART":
                amount        = Decimal(str(cmd["amount"]))
                reduce_tenure = bool(cmd.get("reduce_tenure", True))
                eng.process_part_prepayment(ev_date, amount, reduce_tenure)
                print(f"  [{idx}] PREPAYMENT_PART {loan_id}: Rs {amount:,.2f} (reduce_tenure={reduce_tenure})")

            elif command_type == "PREPAYMENT_FULL":
                amount = Decimal(str(cmd["amount"]))
                eng.process_full_prepayment(ev_date, amount)
                print(f"  [{idx}] PREPAYMENT_FULL {loan_id}: Rs {amount:,.2f} — loan CLOSED")

        else:
            print(f"  [WARN] Command {idx}: Unknown command type '{command_type}' — skipped.")

    # ── Write Phase 2 outputs for each engine ────────────────────────────
    print()
    print("Writing Phase 2 outputs…")
    for loan_id, eng in engines.items():
        files = write_phase2_outputs(eng, output_dir, fy_year)
        print(f"  {loan_id}: {len(files)} files written")

    # ── Write aggregate summary ───────────────────────────────────────────
    write_json_output(
        {"total": len(commands), "success": success_count, "errors": error_count,
         "sanctions": results_summary},
        output_dir,
        "run_summary.json",
    )

    # ── Final report ──────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  Run complete.  Success: {success_count}  Errors: {error_count}")
    print(f"  Output files written to: {output_dir.resolve()}")
    print("=" * 60)

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
