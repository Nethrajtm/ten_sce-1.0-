"""
src/calculations/fees.py
Processing-fee calculation (BR-08).
All amounts rounded to 2 decimal places with ROUND_HALF_UP.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, getcontext

from src.rules.business_rules import BusinessRules

getcontext().prec = 28

_TWO_DP = Decimal('0.01')


def calculate_processing_fee(sanction_amount: Decimal) -> dict:
    """
    BR-08: Calculate the full processing-fee breakdown.

    Returns
    -------
    dict with keys:
        gross_fee          – 0.5 % of sanction, clamped [10 000, 25 000]
        gst                – 18 % of gross_fee
        total_fee          – gross_fee + gst
        at_sanction        – 50 % of total_fee
        at_first_disbursal – 50 % of total_fee
        rule_id            – "BR-08"
    """
    gross_fee = BusinessRules.processing_fee_gross(sanction_amount).quantize(
        _TWO_DP, rounding=ROUND_HALF_UP
    )
    gst = BusinessRules.processing_fee_gst(gross_fee).quantize(
        _TWO_DP, rounding=ROUND_HALF_UP
    )
    total_fee = (gross_fee + gst).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    half = (total_fee / Decimal('2')).quantize(_TWO_DP, rounding=ROUND_HALF_UP)

    return {
        "gross_fee": gross_fee,
        "gst": gst,
        "total_fee": total_fee,
        "at_sanction": half,
        "at_first_disbursal": half,
        "rule_id": BusinessRules.BR_08,
    }
