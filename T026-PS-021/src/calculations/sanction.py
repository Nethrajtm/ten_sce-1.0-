"""
src/calculations/sanction.py
Orchestrates the full sanction eligibility process.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, getcontext
from typing import Optional

from src.models.borrower import Borrower
from src.models.property import Property
from src.models.loan import SanctionResult
from src.rules.business_rules import BusinessRules
from src.calculations.eligibility import (
    calculate_combined_income,
    calculate_ltv_limit,
    calculate_max_tenure,
    calculate_interest_rate,
    calculate_eligibility_limit,
)
from src.calculations.fees import calculate_processing_fee

getcontext().prec = 28

# Module-level counter for auto-generating loan IDs (resets per process).
_loan_counter: dict[int, int] = {}


def _next_loan_id(year: int) -> str:
    """Return an auto-generated loan ID in the format LN{year}{seq:03d}."""
    _loan_counter[year] = _loan_counter.get(year, 0) + 1
    return f"LN{year}{_loan_counter[year]:03d}"


def _add_months(d: date, months: int) -> date:
    """
    Add *months* calendar months to *d*, clamping to the last valid day when
    the resulting month has fewer days than the original day.

    e.g. Jan 31 + 6 months → Jul 31  (July has 31 days, OK)
         Aug 31 + 6 months → Feb 28/29
    """
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def process_sanction(
    borrower: Borrower,
    property_: Property,
    benchmark_rate: Decimal,
    sanction_date: date,
    loan_id: Optional[str] = None,
) -> SanctionResult:
    """
    Run all Phase-1 eligibility rules and produce a SanctionResult.

    Parameters
    ----------
    borrower       : Primary borrower (may include co-applicant).
    property_      : Target property with agreement value and stages.
    benchmark_rate : Current RBI / bank benchmark rate (annual %).
    sanction_date  : Date on which sanction is processed.
    loan_id        : Override auto-generated loan ID (useful in tests).

    Returns
    -------
    SanctionResult with all computed fields populated.
    """
    rule_ids: list[str] = []

    # ── BR-01: LTV limit ─────────────────────────────────────────────────
    ltv_limit, br01 = calculate_ltv_limit(property_.agreement_value)
    rule_ids.append(br01)

    # ── BR-02: Tenure ────────────────────────────────────────────────────
    tenure_months, br02 = calculate_max_tenure(borrower, sanction_date)
    rule_ids.append(br02)

    # ── BR-03 / BR-04: Combined income ───────────────────────────────────
    combined_income = calculate_combined_income(borrower)
    rule_ids.append(BusinessRules.BR_03)
    if borrower.coapplicant is not None:
        rule_ids.append(BusinessRules.BR_04)

    # ── BR-05 / BR-06: Interest rate ─────────────────────────────────────
    interest_rate, rate_rules = calculate_interest_rate(
        benchmark_rate, borrower.credit_score, borrower.gender
    )
    rule_ids.extend(rate_rules)

    # ── BR-10: Eligibility limit ──────────────────────────────────────────
    eligibility_limit, br10 = calculate_eligibility_limit(
        combined_income, tenure_months, interest_rate
    )
    rule_ids.append(br10)

    # ── BR-07: Sanctioned amount ──────────────────────────────────────────
    sanctioned_amount = BusinessRules.sanctioned_amount(ltv_limit, eligibility_limit)
    rule_ids.append(BusinessRules.BR_07)

    # ── BR-08: Processing fee ─────────────────────────────────────────────
    fee_breakdown = calculate_processing_fee(sanctioned_amount)
    rule_ids.append(BusinessRules.BR_08)

    # ── BR-09: Sanction expiry ────────────────────────────────────────────
    expiry_date = _add_months(sanction_date, BusinessRules.SANCTION_VALIDITY_MONTHS)
    rule_ids.append(BusinessRules.BR_09)

    # ── Auto loan ID ──────────────────────────────────────────────────────
    if loan_id is None:
        loan_id = _next_loan_id(sanction_date.year)

    return SanctionResult(
        loan_id=loan_id,
        borrower_id=borrower.borrower_id,
        property_id=property_.property_id,
        sanctioned_amount=sanctioned_amount,
        tenure_months=tenure_months,
        interest_rate=interest_rate,
        ltv_limit=ltv_limit,
        eligibility_limit=eligibility_limit,
        processing_fee=fee_breakdown,
        gst_on_fee=fee_breakdown["gst"],
        sanction_date=sanction_date,
        expiry_date=expiry_date,
        rule_ids_applied=rule_ids,
        status="SANCTIONED",
    )
