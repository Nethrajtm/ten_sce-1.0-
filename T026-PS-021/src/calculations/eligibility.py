"""
src/calculations/eligibility.py
Core eligibility calculation functions for Phase 1.
All monetary values use Decimal with ROUND_HALF_UP.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, getcontext
from datetime import date
from typing import Tuple, List

from src.models.borrower import Borrower
from src.rules.business_rules import BusinessRules

getcontext().prec = 28

_TWO = Decimal('0.01')


def calculate_combined_income(borrower: Borrower) -> Decimal:
    """
    BR-03 / BR-04: Return the combined weighted monthly income.

    combined = borrower.net_income_monthly
             + (coapplicant.income_monthly * weight)
    where weight is 1.0 for SPOUSE, 0.5 for OTHER (BR-04).
    """
    income = borrower.net_income_monthly
    if borrower.coapplicant is not None:
        weight = BusinessRules.coapplicant_weight(borrower.coapplicant.relationship)
        income = income + borrower.coapplicant.income_monthly * weight
    return income


def calculate_ltv_limit(
    agreement_value: Decimal,
) -> Tuple[Decimal, str]:
    """
    BR-01: Return (ltv_amount, rule_id).

    ltv_amount is rounded down to the nearest rupee (ROUND_HALF_UP on 0 dp).
    """
    ratio = BusinessRules.ltv_ratio(agreement_value)
    ltv_amount = (agreement_value * ratio).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return ltv_amount, BusinessRules.BR_01


def calculate_max_tenure(
    borrower: Borrower,
    sanction_date: date,
) -> Tuple[int, str]:
    """
    BR-02: Return (tenure_months, rule_id).

    tenure_months = min(360, (70 - age_at_sanction) * 12)
    """
    age = borrower.age_at_date(sanction_date)
    tenure = BusinessRules.max_tenure_months(age)
    return tenure, BusinessRules.BR_02


def calculate_interest_rate(
    benchmark_rate: Decimal,
    credit_score: int,
    gender: str,
) -> Tuple[Decimal, List[str]]:
    """
    BR-05 / BR-06: Return (annual_rate_pct, [rule_ids]).

    annual_rate = benchmark_rate + credit_spread + women_concession
    """
    spread = BusinessRules.credit_spread(credit_score)
    concession = BusinessRules.women_concession(gender)
    annual_rate = benchmark_rate + spread + concession
    # Round to 2 dp to keep tidy
    annual_rate = annual_rate.quantize(_TWO, rounding=ROUND_HALF_UP)
    rules = [BusinessRules.BR_05]
    if gender == "F":
        rules.append(BusinessRules.BR_06)
    return annual_rate, rules


def calculate_eligibility_limit(
    combined_income: Decimal,
    tenure_months: int,
    annual_rate: Decimal,
) -> Tuple[Decimal, str]:
    """
    BR-10: Return (max_loan, rule_id).

    max_emi  = combined_income * ratio          (BR-03)
    max_loan = max_emi * ((1+r)^n - 1) / (r*(1+r)^n)
    where r  = annual_rate / 1200
    """
    ratio = BusinessRules.emi_income_ratio(combined_income)
    max_emi = combined_income * ratio
    max_loan = BusinessRules.max_loan_from_emi(max_emi, tenure_months, annual_rate)
    max_loan = max_loan.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return max_loan, BusinessRules.BR_10
