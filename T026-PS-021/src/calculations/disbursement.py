"""
src/calculations/disbursement.py
Tranche release logic for construction-linked disbursements.
All monetary values use Decimal with ROUND_HALF_UP.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.loan import LoanAccount, DisburseRecord, EventLog
    from src.models.borrower import Borrower

getcontext().prec = 28

# Constants
MAX_MORATORIUM_MONTHS = 36
MIN_PREPAYMENT = Decimal('50000')
PENAL_RATE_PER_MONTH = Decimal('0.02')   # 2% per month
GRACE_DAYS = 15
CERT_VALIDITY_DAYS = 90
TRANCHE_RELEASE_DAYS = 7


def check_tranche_release(
    loan: "LoanAccount",
    demand_date: date,
    demand_amount: Decimal,
    certification_date: date,
    certified_pct: Decimal,         # cumulative % certified so far (after this stage)
    own_contribution_paid: bool,
    borrower: "Borrower",
    event_date: date,
    cumulative_demanded_pct: Decimal = Decimal('0'),
    consecutive_missed: int = 0,
) -> tuple[str, str, list[str], Decimal]:
    """
    Apply BR-26 precedence checks and return:
    (decision, reason, rules_applied, release_amount)
    decision: "RELEASED" | "REJECTED" | "PARTIAL"

    Precedence (BR-26):
    1. Sanction validity (BR-09)
    2. Own contribution paid (BR-11)
    3. Stage certification coverage (BR-12) + freshness (BR-16)
    4. Sanction cap (BR-13)
    5. Delinquency freeze (BR-14)
    """
    rules_applied = [("BR-26")]

    # 1. Sanction validity (BR-09)
    if event_date > loan.expiry_date:
        return (
            "REJECTED",
            f"Sanction expired on {loan.expiry_date}. Event date {event_date} is past expiry.",
            rules_applied + ["BR-09"],
            Decimal('0'),
        )

    # 2. Own contribution paid (BR-11)
    if not own_contribution_paid:
        return (
            "REJECTED",
            "Own contribution has not been paid. Must be paid before first tranche (BR-11).",
            rules_applied + ["BR-11"],
            Decimal('0'),
        )

    # 3a. Stage certification coverage (BR-12)
    # certified_pct must be >= cumulative demanded after this demand
    new_cumulative_demanded = cumulative_demanded_pct + (demand_amount / loan.sanctioned_amount * Decimal('100'))
    if certified_pct < new_cumulative_demanded:
        return (
            "REJECTED",
            (
                f"Stage certification ({certified_pct:.2f}%) insufficient for cumulative demand "
                f"({new_cumulative_demanded:.2f}%). BR-12 requires cert >= demand."
            ),
            rules_applied + ["BR-12"],
            Decimal('0'),
        )

    # 3b. Certification freshness (BR-16)
    cert_age_days = (event_date - certification_date).days
    if cert_age_days > CERT_VALIDITY_DAYS:
        return (
            "REJECTED",
            (
                f"Certification dated {certification_date} is {cert_age_days} days old "
                f"(limit {CERT_VALIDITY_DAYS} days). Fresh certification required (BR-16)."
            ),
            rules_applied + ["BR-16"],
            Decimal('0'),
        )

    # 4. Sanction cap (BR-13)
    cumulative_disbursed = sum(
        Decimal(str(r.get("amount", 0))) if isinstance(r, dict) else r.amount
        for r in loan.disbursement_records
        if (r.get("decision") if isinstance(r, dict) else r.decision) == "RELEASED"
    )
    remaining = loan.sanctioned_amount - cumulative_disbursed
    if remaining <= Decimal('0'):
        return (
            "REJECTED",
            f"Sanctioned amount fully disbursed (Rs {loan.sanctioned_amount:,.2f}). No further tranches (BR-13).",
            rules_applied + ["BR-13"],
            Decimal('0'),
        )

    # 5. Delinquency freeze (BR-14)
    if consecutive_missed >= 3:
        return (
            "REJECTED",
            f"Loan frozen due to {consecutive_missed} consecutive missed EMIs (BR-14).",
            rules_applied + ["BR-14"],
            Decimal('0'),
        )

    # All checks passed — compute release amount
    release = calculate_release_amount(
        demand_amount=demand_amount,
        cumulative_disbursed=cumulative_disbursed,
        sanctioned_amount=loan.sanctioned_amount,
        own_contribution_ratio=Decimal('0'),  # own contribution fully paid upfront
    )

    if release <= Decimal('0'):
        return (
            "REJECTED",
            "Calculated release amount is zero or negative after cap (BR-13).",
            rules_applied + ["BR-13"],
            Decimal('0'),
        )

    decision = "RELEASED"
    reason = f"Tranche released: Rs {release:,.2f}"

    if release < demand_amount:
        decision = "PARTIAL"
        reason = f"Partial release Rs {release:,.2f} (demand Rs {demand_amount:,.2f}). Capped at remaining sanctioned (BR-13)."

    return decision, reason, rules_applied + ["BR-13"], release


def calculate_release_amount(
    demand_amount: Decimal,
    cumulative_disbursed: Decimal,
    sanctioned_amount: Decimal,
    own_contribution_ratio: Decimal,
) -> Decimal:
    """
    BR-13: release = min(demand_amount, remaining_sanctioned).
    Since own contribution is paid upfront, each tranche demand is purely the
    loan portion.  We simply cap at remaining sanctioned.
    Round to nearest rupee ROUND_HALF_UP.
    """
    remaining = sanctioned_amount - cumulative_disbursed
    release = min(demand_amount, remaining)
    return release.quantize(Decimal('1'), rounding=ROUND_HALF_UP)


def consecutive_missed_emis(loan: "LoanAccount") -> int:
    """Count trailing consecutive missed/overdue EMIs (for BR-14)."""
    schedule = loan.emi_schedule
    if not schedule:
        return 0

    count = 0
    # Iterate from the end
    for entry in reversed(schedule):
        status = entry.get("status") if isinstance(entry, dict) else entry.status
        if status in ("OVERDUE",):
            count += 1
        elif status in ("PAID", "PART_PAID"):
            break
        # PENDING entries haven't been processed yet — stop counting
        elif status == "PENDING":
            break

    return count
