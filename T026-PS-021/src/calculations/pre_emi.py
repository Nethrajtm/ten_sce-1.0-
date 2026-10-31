"""
src/calculations/pre_emi.py
Pre-EMI billing: daily actual/365 accrual per tranche.
BR-17, BR-18.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 28


def daily_rate(annual_rate_pct: Decimal) -> Decimal:
    """annual_rate_pct / 100 / 365  (actual/365 basis)."""
    return annual_rate_pct / Decimal('100') / Decimal('365')


def accrual_for_tranche(
    principal: Decimal,
    annual_rate_pct: Decimal,
    from_date: date,
    to_date: date,
) -> Decimal:
    """
    BR-17: Interest = principal * daily_rate * days
    days = (to_date - from_date).days   (actual day count)
    Rounded to 2dp ROUND_HALF_UP.
    """
    days = (to_date - from_date).days
    if days <= 0:
        return Decimal('0')
    rate = daily_rate(annual_rate_pct)
    interest = principal * rate * Decimal(str(days))
    return interest.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def generate_pre_emi_bill(
    tranches: list[dict],    # list of {"amount": Decimal, "release_date": date}
    annual_rate_pct: Decimal,
    period_from: date,       # 1st of previous month
    period_to: date,         # last day of previous month
    bill_no: int,
    bill_date: date,         # 5th of current month
) -> dict:
    """
    BR-17/BR-18: Generate a pre-EMI bill for a calendar month.
    Each tranche accrues from max(release_date, period_from) to period_to.
    Returns a dict matching PreEmiBill structure.
    """
    breakdown = []
    total_interest = Decimal('0')

    for t in tranches:
        amount = t["amount"]
        release_date = t["release_date"]

        # Only accrue if tranche was released before or during the period
        if release_date > period_to:
            continue

        # Accrue from max(release_date, period_from) to period_to
        accrual_from = max(release_date, period_from)
        days = (period_to - accrual_from).days
        if days <= 0:
            continue

        interest = accrual_for_tranche(amount, annual_rate_pct, accrual_from, period_to)
        total_interest += interest

        breakdown.append({
            "release_date": release_date.isoformat(),
            "amount": str(amount),
            "accrual_from": accrual_from.isoformat(),
            "accrual_to": period_to.isoformat(),
            "days": days,
            "interest": str(interest),
        })

    return {
        "bill_no": bill_no,
        "bill_date": bill_date.isoformat(),
        "period_from": period_from.isoformat(),
        "period_to": period_to.isoformat(),
        "interest_amount": str(total_interest.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        "tranche_breakdown": breakdown,
        "rules_applied": ["BR-17", "BR-18"],
    }


def bill_date_for_month(year: int, month: int) -> date:
    """Return the 5th of the given month (billing date for that month)."""
    return date(year, month, 5)


def period_for_billing_month(bill_year: int, bill_month: int) -> tuple[date, date]:
    """
    The bill issued on the 5th of bill_month covers the PREVIOUS calendar month.
    Returns (period_from, period_to) = (1st of prev month, last day of prev month).
    """
    if bill_month == 1:
        prev_year = bill_year - 1
        prev_month = 12
    else:
        prev_year = bill_year
        prev_month = bill_month - 1

    period_from = date(prev_year, prev_month, 1)
    last_day = calendar.monthrange(prev_year, prev_month)[1]
    period_to = date(prev_year, prev_month, last_day)
    return period_from, period_to
