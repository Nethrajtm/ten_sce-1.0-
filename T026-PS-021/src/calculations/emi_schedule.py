"""
src/calculations/emi_schedule.py
Full EMI schedule generation, rate resets, prepayments.
BR-19 through BR-23.
"""
from __future__ import annotations

import math
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.borrower import Borrower
    from src.models.loan import LoanAccount, EmiRecord

getcontext().prec = 28

_MAX_AGE_AT_LOAN_END = 70


def compute_emi(principal: Decimal, annual_rate_pct: Decimal, tenure_months: int) -> Decimal:
    """Standard PMT formula. Round to 2dp ROUND_HALF_UP."""
    r = annual_rate_pct / Decimal('1200')
    one_plus_r_n = (Decimal('1') + r) ** tenure_months
    emi = principal * r * one_plus_r_n / (one_plus_r_n - Decimal('1'))
    return emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def generate_schedule(
    principal: Decimal,
    annual_rate_pct: Decimal,
    tenure_months: int,
    start_date: date,        # date of first EMI due
) -> list[dict]:
    """
    BR-19/BR-20: Generate full amortisation schedule.
    Returns list of EmiRecord-compatible dicts.
    Due dates: same day of month as start_date for each subsequent month.
    Last EMI adjusted to clear outstanding exactly (no negative balance).
    """
    emi = compute_emi(principal, annual_rate_pct, tenure_months)
    r = annual_rate_pct / Decimal('1200')
    anchor_day = start_date.day

    schedule = []
    outstanding = principal
    current_date = start_date

    for i in range(1, tenure_months + 1):
        interest_component = (outstanding * r).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        principal_component = emi - interest_component

        # Last EMI: adjust to clear exactly
        if i == tenure_months or principal_component >= outstanding:
            principal_component = outstanding
            emi_this = (principal_component + interest_component).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            outstanding = Decimal('0')
        else:
            emi_this = emi
            outstanding = outstanding - principal_component
            outstanding = outstanding.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        schedule.append({
            "emi_no": i,
            "due_date": current_date.isoformat(),
            "emi_amount": str(emi_this),
            "principal_component": str(principal_component),
            "interest_component": str(interest_component),
            "outstanding_principal": str(outstanding),
            "paid_date": None,
            "paid_amount": None,
            "penal_interest": str(Decimal('0')),
            "status": "PENDING",
        })

        if outstanding <= Decimal('0'):
            break

        # Advance to next due date
        current_date = next_emi_due_date_after(current_date, anchor_day)

    return schedule


def next_emi_due_date_after(current_date: date, anchor_day: int) -> date:
    """
    Next month's EMI due date from a given date.
    Advance by one month, clamp to last day of that month.
    """
    month = current_date.month + 1
    year = current_date.year
    if month > 12:
        month = 1
        year += 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_emi_due_date(current_date: date, anchor_day: int) -> date:
    """
    Next EMI due date from current_date.
    Clamp anchor_day to last day of month if it exceeds month length.
    If current_date.day < anchor_day, due date is anchor_day of THIS month.
    Otherwise it's the anchor_day of NEXT month.
    """
    year = current_date.year
    month = current_date.month
    last_day = calendar.monthrange(year, month)[1]
    clamped = min(anchor_day, last_day)
    if current_date.day < clamped:
        return date(year, month, clamped)
    # Move to next month
    month += 1
    if month > 12:
        month = 1
        year += 1
    last_day = calendar.monthrange(year, month)[1]
    clamped = min(anchor_day, last_day)
    return date(year, month, clamped)


def recalculate_schedule_after_prepayment(
    outstanding: Decimal,
    annual_rate_pct: Decimal,
    remaining_tenure: int,
    next_due_date: date,
    reduce_tenure: bool = True,
    current_emi: Optional[Decimal] = None,
) -> list[dict]:
    """
    BR-22: After prepayment, recalculate schedule.
    If reduce_tenure=True: keep same EMI, compute new tenure.
    If reduce_tenure=False: keep same tenure, reduce EMI.
    """
    if reduce_tenure and current_emi is not None:
        # Compute new tenure keeping same EMI
        r_float = float(annual_rate_pct) / 1200.0
        p_float = float(outstanding)
        e_float = float(current_emi)
        ratio = r_float * p_float / e_float
        if ratio >= 1.0:
            new_tenure = remaining_tenure
        else:
            new_tenure = math.ceil(-math.log(1.0 - ratio) / math.log(1.0 + r_float))
        new_tenure = min(new_tenure, remaining_tenure)
        # Generate schedule using the SAME emi so it remains unchanged for non-last entries
        return _generate_schedule_fixed_emi(outstanding, annual_rate_pct, new_tenure,
                                            next_due_date, current_emi)
    else:
        # Keep same tenure, recompute EMI
        return generate_schedule(outstanding, annual_rate_pct, remaining_tenure, next_due_date)


def _generate_schedule_fixed_emi(
    principal: Decimal,
    annual_rate_pct: Decimal,
    tenure_months: int,
    start_date: date,
    fixed_emi: Decimal,
) -> list[dict]:
    """Generate schedule using a fixed EMI amount (tenure-reduce case after prepayment)."""
    r = annual_rate_pct / Decimal('1200')
    anchor_day = start_date.day
    schedule = []
    outstanding = principal
    current_date = start_date

    for i in range(1, tenure_months + 1):
        interest_component = (outstanding * r).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        principal_component = fixed_emi - interest_component

        if i == tenure_months or principal_component >= outstanding:
            principal_component = outstanding
            emi_this = (principal_component + interest_component).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            outstanding = Decimal('0')
        else:
            emi_this = fixed_emi
            outstanding = outstanding - principal_component
            outstanding = outstanding.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        schedule.append({
            "emi_no": i,
            "due_date": current_date.isoformat(),
            "emi_amount": str(emi_this),
            "principal_component": str(principal_component),
            "interest_component": str(interest_component),
            "outstanding_principal": str(outstanding),
            "paid_date": None,
            "paid_amount": None,
            "penal_interest": str(Decimal('0')),
            "status": "PENDING",
        })

        if outstanding <= Decimal('0'):
            break

        current_date = next_emi_due_date_after(current_date, anchor_day)

    return schedule


def apply_rate_reset(
    outstanding: Decimal,
    old_rate: Decimal,
    new_rate: Decimal,
    current_emi: Decimal,
    remaining_tenure: int,
    reset_date: date,
    borrower_dob: date,
    next_due_date: date,
) -> tuple[Decimal, int, list[dict], str]:
    """
    BR-21: Rate reset. Try to keep EMI constant and adjust tenure.
    If new tenure > age cap (70 years), change EMI instead.
    Returns (new_emi, new_tenure, new_schedule, reason).
    """
    # Compute new tenure at same EMI
    r_float = float(new_rate) / 1200.0
    p_float = float(outstanding)
    e_float = float(current_emi)

    ratio = r_float * p_float / e_float
    if ratio >= 1.0:
        # EMI doesn't cover interest at new rate — must increase EMI
        new_tenure = remaining_tenure
        new_emi = compute_emi(outstanding, new_rate, new_tenure)
        reason = f"Rate reset to {new_rate}%: EMI increased to Rs {new_emi:,.2f} (tenure {new_tenure} months)"
        schedule = generate_schedule(outstanding, new_rate, new_tenure, next_due_date)
        return new_emi, new_tenure, schedule, reason

    new_tenure = math.ceil(-math.log(1.0 - ratio) / math.log(1.0 + r_float))

    # Check age cap: borrower age at reset_date + new_tenure months <= 70
    age_at_reset = reset_date.year - borrower_dob.year
    if (reset_date.month, reset_date.day) < (borrower_dob.month, borrower_dob.day):
        age_at_reset -= 1
    max_remaining_months = (_MAX_AGE_AT_LOAN_END - age_at_reset) * 12

    if new_tenure > max_remaining_months:
        # Cannot extend tenure past age 70 — increase EMI instead
        new_tenure = max_remaining_months
        new_emi = compute_emi(outstanding, new_rate, new_tenure)
        reason = (
            f"Rate reset to {new_rate}%: tenure capped at {new_tenure} months (age 70 limit). "
            f"EMI changed to Rs {new_emi:,.2f} (BR-21)."
        )
    else:
        new_emi = current_emi
        reason = (
            f"Rate reset to {new_rate}%: EMI unchanged at Rs {current_emi:,.2f}, "
            f"tenure adjusted to {new_tenure} months (BR-21)."
        )

    schedule = generate_schedule(outstanding, new_rate, new_tenure, next_due_date)
    return new_emi, new_tenure, schedule, reason
