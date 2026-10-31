"""
src/rules/business_rules.py
Business rules for the Home Loan with Construction-Linked
Disbursement Tranches and Pre-EMI product.  Phase 1 (BR-01 to BR-10)
and Phase 2 (BR-11 to BR-26).

Each rule is identified by a BR-xx ID and documented as a class constant.
"""
from __future__ import annotations

import math
from decimal import Decimal, getcontext

getcontext().prec = 28

# ─────────────────────────────────────────────────────────────────────────────
# Constants / thresholds used by multiple rules
# ─────────────────────────────────────────────────────────────────────────────
_THIRTY_LAKH = Decimal('3000000')
_SEVENTY_FIVE_LAKH = Decimal('7500000')

_LTV_BELOW_30L = Decimal('0.90')   # 90 %
_LTV_30L_TO_75L = Decimal('0.80')  # 80 %
_LTV_ABOVE_75L = Decimal('0.75')   # 75 %

_MAX_TENURE_YEARS = 30
_MAX_TENURE_MONTHS = _MAX_TENURE_YEARS * 12   # 360
_MAX_AGE_AT_LOAN_END = 70

_INCOME_THRESHOLD = Decimal('100000')
_RATIO_BELOW_THRESHOLD = Decimal('0.55')
_RATIO_ABOVE_THRESHOLD = Decimal('0.60')

_SPREAD_HIGH_CREDIT = Decimal('0.50')   # credit_score >= 775
_SPREAD_MID_CREDIT = Decimal('0.90')    # 725 <= score <= 774
_SPREAD_LOW_CREDIT = Decimal('1.40')    # score < 725

_WOMEN_CONCESSION = Decimal('-0.05')

_FEE_RATE = Decimal('0.005')            # 0.5 %
_FEE_MIN = Decimal('10000')
_FEE_MAX = Decimal('25000')
_GST_RATE = Decimal('0.18')             # 18 %

_SANCTION_VALIDITY_MONTHS = 6


class BusinessRules:
    """
    Registry of all Phase-1 business rules.

    Each rule is documented with its ID, description, and the key parameters
    it uses.  Static / class methods provide the computation logic so that
    callers can refer back to a specific BR-xx ID.
    """

    # ── Rule identifiers ─────────────────────────────────────────────────
    BR_01 = "BR-01"   # LTV ratios
    BR_02 = "BR-02"   # Maximum eligible tenure
    BR_03 = "BR-03"   # EMI-to-income ratio limits
    BR_04 = "BR-04"   # Co-applicant income weighting
    BR_05 = "BR-05"   # Rate spread by credit score
    BR_06 = "BR-06"   # Women primary applicant concession
    BR_07 = "BR-07"   # Sanction amount = min(LTV, eligibility)
    BR_08 = "BR-08"   # Processing fee
    BR_09 = "BR-09"   # Sanction validity
    BR_10 = "BR-10"   # Eligibility: combined EMI must not exceed ratio limit

    # ── BR-01: LTV ratios ─────────────────────────────────────────────────
    @staticmethod
    def ltv_ratio(agreement_value: Decimal) -> Decimal:
        """
        BR-01: Return the applicable LTV ratio for a given property value.

        - agreement_value <= 30,00,000  → 90 %
        - 30,00,000 < value <= 75,00,000 → 80 %
        - value > 75,00,000             → 75 %
        """
        if agreement_value <= _THIRTY_LAKH:
            return _LTV_BELOW_30L
        elif agreement_value <= _SEVENTY_FIVE_LAKH:
            return _LTV_30L_TO_75L
        else:
            return _LTV_ABOVE_75L

    # ── BR-02: Maximum eligible tenure ────────────────────────────────────
    @staticmethod
    def max_tenure_months(age_at_sanction: int) -> int:
        """
        BR-02: Return the maximum allowable tenure in months.

        cap_by_age   = (70 - current_age) * 12
        max_tenure   = min(360, cap_by_age)
        """
        months_to_70 = (_MAX_AGE_AT_LOAN_END - age_at_sanction) * 12
        return min(_MAX_TENURE_MONTHS, months_to_70)

    # ── BR-03: EMI-to-income ratio ────────────────────────────────────────
    @staticmethod
    def emi_income_ratio(combined_income: Decimal) -> Decimal:
        """
        BR-03: Return the maximum EMI/NMI ratio for a given combined income.

        - combined_income <= 1,00,000 → 55 %
        - combined_income >  1,00,000 → 60 %
        """
        if combined_income <= _INCOME_THRESHOLD:
            return _RATIO_BELOW_THRESHOLD
        return _RATIO_ABOVE_THRESHOLD

    # ── BR-04: Co-applicant income weighting ──────────────────────────────
    @staticmethod
    def coapplicant_weight(relationship: str) -> Decimal:
        """
        BR-04: Return the income weighting factor for a co-applicant.

        - SPOUSE → 100 % (Decimal('1'))
        - OTHER  →  50 % (Decimal('0.5'))
        """
        if relationship == "SPOUSE":
            return Decimal('1')
        return Decimal('0.5')

    # ── BR-05: Rate spread by credit score ───────────────────────────────
    @staticmethod
    def credit_spread(credit_score: int) -> Decimal:
        """
        BR-05: Return the rate spread (in percentage points) for a credit score.

        - score >= 775 → +0.50 %
        - 725 <= score <= 774 → +0.90 %
        - score < 725 → +1.40 %
        """
        if credit_score >= 775:
            return _SPREAD_HIGH_CREDIT
        elif credit_score >= 725:
            return _SPREAD_MID_CREDIT
        else:
            return _SPREAD_LOW_CREDIT

    # ── BR-06: Women primary applicant concession ─────────────────────────
    @staticmethod
    def women_concession(gender: str) -> Decimal:
        """
        BR-06: Return the interest rate concession for a female primary borrower.

        - gender == 'F' → -0.05 %
        - otherwise     →  0.00 %
        """
        if gender == "F":
            return _WOMEN_CONCESSION
        return Decimal('0')

    # ── BR-07: Sanction amount ────────────────────────────────────────────
    @staticmethod
    def sanctioned_amount(ltv_limit: Decimal, eligibility_limit: Decimal) -> Decimal:
        """
        BR-07: Sanction amount = min(LTV limit, eligibility limit).
        """
        return min(ltv_limit, eligibility_limit)

    # ── BR-08: Processing fee ─────────────────────────────────────────────
    @staticmethod
    def processing_fee_gross(sanction_amount: Decimal) -> Decimal:
        """
        BR-08: Gross processing fee before GST.

        fee = 0.5% of sanction_amount, clamped to [10,000 ; 25,000]
        """
        fee = (sanction_amount * _FEE_RATE).quantize(Decimal('0.01'))
        fee = max(_FEE_MIN, min(_FEE_MAX, fee))
        return fee

    @staticmethod
    def processing_fee_gst(gross_fee: Decimal) -> Decimal:
        """BR-08: GST = 18% of gross processing fee."""
        return (gross_fee * _GST_RATE).quantize(Decimal('0.01'))

    # ── BR-09: Sanction validity ──────────────────────────────────────────
    SANCTION_VALIDITY_MONTHS = _SANCTION_VALIDITY_MONTHS

    # ── BR-10: Eligibility PMT formula ────────────────────────────────────
    @staticmethod
    def max_loan_from_emi(max_emi: Decimal, tenure_months: int, annual_rate_pct: Decimal) -> Decimal:
        """
        BR-10: Calculate the maximum loan amount for a given monthly EMI.

        Formula:
            r         = annual_rate_pct / 1200  (monthly rate as a fraction)
            max_loan  = max_emi * ((1+r)^n - 1) / (r * (1+r)^n)

        Uses Decimal arithmetic throughout.
        """
        r = annual_rate_pct / Decimal('1200')
        n = tenure_months
        one_plus_r_n = (Decimal('1') + r) ** n
        max_loan = max_emi * (one_plus_r_n - Decimal('1')) / (r * one_plus_r_n)
        return max_loan

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 Rule Identifiers (BR-11 to BR-26)
    # ─────────────────────────────────────────────────────────────────────────
    BR_11 = "BR-11"  # Own contribution must be paid before first tranche
    BR_12 = "BR-12"  # Stage certification must cover cumulative demand %
    BR_13 = "BR-13"  # Tranche cap: release up to remaining sanctioned amount only
    BR_14 = "BR-14"  # Delinquency freeze after 3 consecutive missed EMIs
    BR_15 = "BR-15"  # Tranche release within 7 days of later of demand/certification
    BR_16 = "BR-16"  # Certification older than 90 days requires fresh certification
    BR_17 = "BR-17"  # Pre-EMI: daily actual/365 on disbursed amount per tranche
    BR_18 = "BR-18"  # Moratorium: pre-EMI period is until final disbursement or 36 months
    BR_19 = "BR-19"  # Full EMI starts from month after final tranche or 37th month
    BR_20 = "BR-20"  # EMI computed on total disbursed (not sanctioned) for remaining tenure
    BR_21 = "BR-21"  # Rate reset: keep EMI constant, adjust tenure; if exceeds age cap change EMI
    BR_22 = "BR-22"  # Part prepayment: min Rs 50,000, reduces tenure by default
    BR_23 = "BR-23"  # Full prepayment: closes loan
    BR_24 = "BR-24"  # Penal interest: 2% per month on overdue after 15-day grace
    BR_25 = "BR-25"  # Undisbursed sanction lapses at month 36
    BR_26 = "BR-26"  # Tranche precedence order

    # Phase 2 constants
    MAX_MORATORIUM_MONTHS = 36
    MIN_PREPAYMENT = Decimal('50000')
    PENAL_RATE_PER_MONTH = Decimal('0.02')   # 2% per month
    GRACE_DAYS = 15
    CERT_VALIDITY_DAYS = 90
    MAX_AGE_AT_LOAN_END = 70

    # ── BR-11/BR-20: EMI formula ──────────────────────────────────────────
    @staticmethod
    def emi_amount(principal: Decimal, annual_rate_pct: Decimal, tenure_months: int) -> Decimal:
        """
        PMT formula: monthly EMI for a given principal, rate and tenure.
        r = annual_rate_pct / 1200
        EMI = P * r * (1+r)^n / ((1+r)^n - 1)
        """
        r = annual_rate_pct / Decimal('1200')
        one_plus_r_n = (Decimal('1') + r) ** tenure_months
        emi = principal * r * one_plus_r_n / (one_plus_r_n - Decimal('1'))
        return emi

    @staticmethod
    def outstanding_principal(
        principal: Decimal,
        annual_rate_pct: Decimal,
        emi: Decimal,
        months_paid: int,
    ) -> Decimal:
        """
        Outstanding balance after months_paid EMIs.
        Balance = P*(1+r)^n - EMI*((1+r)^n - 1)/r
        """
        r = annual_rate_pct / Decimal('1200')
        one_plus_r_n = (Decimal('1') + r) ** months_paid
        balance = principal * one_plus_r_n - emi * (one_plus_r_n - Decimal('1')) / r
        return balance

    @staticmethod
    def remaining_tenure_for_emi(
        outstanding: Decimal,
        annual_rate_pct: Decimal,
        emi: Decimal,
    ) -> int:
        """
        How many more months to pay off outstanding at given rate keeping same EMI.
        Solve: n = -log(1 - r*P/EMI) / log(1+r)
        Return ceil of result.
        """
        r = float(annual_rate_pct) / 1200.0
        p = float(outstanding)
        e = float(emi)
        ratio = r * p / e
        if ratio >= 1.0:
            # EMI doesn't cover interest - effectively infinite tenure
            return 999
        n = -math.log(1.0 - ratio) / math.log(1.0 + r)
        return math.ceil(n)
