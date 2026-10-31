"""
src/output/ledger_writer.py
Output generators for Phase 2:
- Disbursement ledger
- Amortisation schedule
- Interest certificate (FY-wise)
- Event log
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.loan_engine import LoanEngine


def format_inr(amount) -> str:
    """Format as Indian currency string."""
    try:
        amt = Decimal(str(amount))
    except Exception:
        amt = Decimal('0')
    return f"Rs {amt:,.2f}"


def _line(width: int = 70) -> str:
    return "-" * width


def generate_disbursement_ledger(engine: "LoanEngine") -> str:
    """
    Generate a formatted text disbursement ledger showing:
    - All tranche releases with dates, amounts, stage %, rule IDs
    - Rejected demands with reasons
    - Running total disbursed vs sanctioned
    """
    loan = engine.loan
    lines = [
        "=" * 70,
        f"  DISBURSEMENT LEDGER — {loan.loan_id}",
        f"  Borrower : {engine.borrower.name} ({loan.borrower_id})",
        f"  Property : {engine.property_.builder_name} ({loan.property_id})",
        f"  Sanctioned Amount : {format_inr(loan.sanctioned_amount)}",
        f"  Sanction Date     : {loan.sanction_date}  |  Expiry: {loan.expiry_date}",
        "=" * 70,
        "",
    ]

    running_total = Decimal('0')
    records = engine.loan.disbursement_records

    if not records:
        lines.append("  No disbursement records.")
    else:
        header = f"{'#':>3}  {'Date':<12} {'Stage':<18} {'Decision':<10} {'Amount':>14}  {'Running':>14}  {'Certified%':>10}"
        lines.append(header)
        lines.append(_line())

        for r in records:
            if r["decision"] in ("RELEASED", "PARTIAL"):
                amt = Decimal(str(r["amount"]))
                running_total += amt
            else:
                amt = Decimal('0')

            tranche_no = r.get("tranche_no", "-")
            release_date = r.get("release_date", "")[:10]
            stage = r.get("stage_name", "")[:18]
            decision = r.get("decision", "")[:10]
            cert_pct = r.get("stage_pct", "0")

            lines.append(
                f"{tranche_no:>3}  {release_date:<12} {stage:<18} {decision:<10} "
                f"{format_inr(amt):>14}  {format_inr(running_total):>14}  {cert_pct:>10}%"
            )
            if r["decision"] == "REJECTED":
                lines.append(f"     ↳ REJECTED: {r.get('reason', '')[:65]}")
            rules = ", ".join(r.get("rules_applied", []))
            lines.append(f"     Rules: {rules}")
        lines.append(_line())

    lines += [
        "",
        f"  Total Disbursed   : {format_inr(running_total)}",
        f"  Undisbursed       : {format_inr(loan.sanctioned_amount - running_total)}",
        "",
    ]
    return "\n".join(lines)


def generate_amortisation_schedule(engine: "LoanEngine") -> str:
    """
    Generate full amortisation table:
    - Pre-EMI bills (moratorium period)
    - Full EMI schedule post-conversion
    """
    loan = engine.loan
    lines = [
        "=" * 90,
        f"  AMORTISATION SCHEDULE — {loan.loan_id}",
        f"  Principal : {format_inr(engine.total_disbursed)}",
        f"  Rate      : {loan.interest_rate}% p.a.",
        "=" * 90,
        "",
    ]

    # Pre-EMI bills
    pre_emi_bills = engine.loan.pre_emi_bills
    if pre_emi_bills:
        lines.append("  ── PRE-EMI BILLS (Moratorium Period) ──")
        lines.append("")
        hdr = f"  {'Bill#':>5}  {'Bill Date':<12} {'Period':<25} {'Interest':>14}"
        lines.append(hdr)
        lines.append("  " + _line(60))
        for bill in pre_emi_bills:
            bill_no = bill.get("bill_no", "")
            bill_date = bill.get("bill_date", "")[:10]
            period = f"{bill.get('period_from','')[:10]} to {bill.get('period_to','')[:10]}"
            interest = format_inr(bill.get("interest_amount", "0"))
            lines.append(f"  {bill_no:>5}  {bill_date:<12} {period:<25} {interest:>14}")
        lines.append("")

    # EMI Schedule
    emi_schedule = engine.loan.emi_schedule
    if emi_schedule:
        lines.append("  ── FULL EMI SCHEDULE (Post-Conversion) ──")
        lines.append("")
        hdr = (
            f"  {'EMI#':>5}  {'Due Date':<12} {'EMI Amt':>12}  {'Principal':>12}  "
            f"{'Interest':>12}  {'Outstanding':>14}  {'Status':<10}"
        )
        lines.append(hdr)
        lines.append("  " + _line(85))
        for e in emi_schedule:
            emi_no = e.get("emi_no", "")
            due_date = e.get("due_date", "")[:10]
            emi_amt = format_inr(e.get("emi_amount", "0"))
            principal = format_inr(e.get("principal_component", "0"))
            interest = format_inr(e.get("interest_component", "0"))
            outstanding = format_inr(e.get("outstanding_principal", "0"))
            status = e.get("status", "")
            penal = Decimal(str(e.get("penal_interest", "0")))

            lines.append(
                f"  {emi_no:>5}  {due_date:<12} {emi_amt:>12}  {principal:>12}  "
                f"{interest:>12}  {outstanding:>14}  {status:<10}"
            )
            if penal > Decimal('0'):
                lines.append(f"         ↳ Penal interest: {format_inr(penal)}")

    lines.append("")
    return "\n".join(lines)


def generate_interest_certificate(engine: "LoanEngine", fy_start_year: int) -> str:
    """
    FY interest certificate for FY fy_start_year/fy_start_year+1.
    (FY = April 1 to March 31)
    """
    fy_from = date(fy_start_year, 4, 1)
    fy_to = date(fy_start_year + 1, 3, 31)

    loan = engine.loan
    lines = [
        "=" * 70,
        f"  INTEREST CERTIFICATE — {loan.loan_id}",
        f"  Financial Year : {fy_start_year}-{str(fy_start_year+1)[2:]}",
        f"  (April 1 {fy_start_year} to March 31 {fy_start_year+1})",
        "=" * 70,
        "",
        "  SECTION A: PRE-EMI INTEREST (Moratorium Period)",
        "  " + _line(50),
    ]

    pre_emi_total = Decimal('0')
    for bill in engine.loan.pre_emi_bills:
        bill_date = date.fromisoformat(bill["bill_date"][:10])
        if fy_from <= bill_date <= fy_to:
            interest = Decimal(str(bill.get("interest_amount", "0")))
            pre_emi_total += interest
            lines.append(
                f"    Bill #{bill['bill_no']:>3}  {bill['bill_date'][:10]}  "
                f"Period: {bill['period_from'][:10]} – {bill['period_to'][:10]}  "
                f"Interest: {format_inr(interest)}"
            )

    lines += [
        f"  Total Pre-EMI Interest : {format_inr(pre_emi_total)}",
        "",
        "  SECTION B: EMI INTEREST (Post-Conversion)",
        "  " + _line(50),
    ]

    emi_interest_total = Decimal('0')
    principal_repaid_total = Decimal('0')
    for e in engine.loan.emi_schedule:
        paid_date = e.get("paid_date")
        if not paid_date:
            continue
        pd = date.fromisoformat(paid_date[:10])
        if fy_from <= pd <= fy_to:
            interest = Decimal(str(e.get("interest_component", "0")))
            principal = Decimal(str(e.get("principal_component", "0")))
            emi_interest_total += interest
            principal_repaid_total += principal

    lines += [
        f"    Total Interest Paid    : {format_inr(emi_interest_total)}",
        f"    Total Principal Repaid : {format_inr(principal_repaid_total)}",
        "",
        "  SECTION C: SUMMARY",
        "  " + _line(50),
        f"    Pre-EMI Interest       : {format_inr(pre_emi_total)}",
        f"    EMI Interest           : {format_inr(emi_interest_total)}",
        f"    Total Interest (FY)    : {format_inr(pre_emi_total + emi_interest_total)}",
        f"    Principal Repaid (FY)  : {format_inr(principal_repaid_total)}",
        "",
        "  Note: Pre-EMI interest is reported separately per BR-17.",
        "=" * 70,
        "",
    ]
    return "\n".join(lines)


def generate_event_log_text(engine: "LoanEngine") -> str:
    """Human-readable event audit log."""
    lines = [
        "=" * 80,
        f"  EVENT AUDIT LOG — {engine.loan.loan_id}",
        "=" * 80,
        "",
        f"  {'#':>4}  {'Date':<12} {'Type':<20} {'Outcome':<10} {'Reason'}",
        "  " + _line(75),
    ]
    for entry in engine.event_log:
        lines.append(
            f"  {entry.event_no:>4}  {str(entry.event_date):<12} {entry.event_type:<20} "
            f"{entry.outcome:<10} {entry.reason[:45]}"
        )
        rules = ", ".join(entry.rules_applied)
        lines.append(f"        Rules: [{rules}]")

    lines.append("")
    return "\n".join(lines)


def write_phase2_outputs(engine: "LoanEngine", output_dir: Path, fy_year: int = 2024):
    """Write all Phase 2 output files for a loan."""
    output_dir.mkdir(parents=True, exist_ok=True)
    loan_id = engine.loan.loan_id

    files_written = []

    # Disbursement ledger
    ledger = generate_disbursement_ledger(engine)
    p = output_dir / f"{loan_id}_disbursement_ledger.txt"
    p.write_text(ledger, encoding="utf-8")
    files_written.append(str(p))

    # Amortisation schedule
    sched = generate_amortisation_schedule(engine)
    p = output_dir / f"{loan_id}_amortisation_schedule.txt"
    p.write_text(sched, encoding="utf-8")
    files_written.append(str(p))

    # Interest certificate
    cert = generate_interest_certificate(engine, fy_year)
    p = output_dir / f"{loan_id}_interest_cert_FY{fy_year}.txt"
    p.write_text(cert, encoding="utf-8")
    files_written.append(str(p))

    # Event log
    ev_log = generate_event_log_text(engine)
    p = output_dir / f"{loan_id}_event_log.txt"
    p.write_text(ev_log, encoding="utf-8")
    files_written.append(str(p))

    # JSON dump of event log for programmatic use
    ev_json = [
        {
            "event_no": e.event_no,
            "event_date": str(e.event_date),
            "event_type": e.event_type,
            "loan_id": e.loan_id,
            "outcome": e.outcome,
            "reason": e.reason,
            "rules_applied": e.rules_applied,
            "details": {k: str(v) if not isinstance(v, (str, bool, int, float, type(None))) else v
                        for k, v in e.details.items()},
        }
        for e in engine.event_log
    ]
    p = output_dir / f"{loan_id}_event_log.json"
    p.write_text(json.dumps(ev_json, indent=2, default=str), encoding="utf-8")
    files_written.append(str(p))

    return files_written
