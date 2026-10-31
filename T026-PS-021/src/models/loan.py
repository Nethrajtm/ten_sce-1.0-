"""
src/models/loan.py
Dataclasses for SanctionResult and LoanAccount entities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional


@dataclass
class SanctionResult:
    """
    Immutable record produced after running the sanction eligibility engine.
    """
    loan_id: str
    borrower_id: str
    property_id: str
    sanctioned_amount: Decimal
    tenure_months: int
    interest_rate: Decimal          # annual rate as a percentage e.g. 9.00
    ltv_limit: Decimal
    eligibility_limit: Decimal
    processing_fee: dict            # full fee breakdown dict from calculate_processing_fee
    gst_on_fee: Decimal
    sanction_date: date
    expiry_date: date
    rule_ids_applied: List[str] = field(default_factory=list)
    status: str = "SANCTIONED"


@dataclass
class LoanAccount:
    """
    Live loan account that holds the sanction plus runtime records
    (disbursements, pre-EMI bills, full EMI schedule).
    """
    # ── Sanction fields (mirrors SanctionResult) ─────────────────────────
    loan_id: str
    borrower_id: str
    property_id: str
    sanctioned_amount: Decimal
    tenure_months: int
    interest_rate: Decimal
    ltv_limit: Decimal
    eligibility_limit: Decimal
    processing_fee: dict
    gst_on_fee: Decimal
    sanction_date: date
    expiry_date: date
    rule_ids_applied: List[str] = field(default_factory=list)
    status: str = "SANCTIONED"

    # ── Runtime records ───────────────────────────────────────────────────
    disbursement_records: List[dict] = field(default_factory=list)
    pre_emi_bills: List[dict] = field(default_factory=list)
    emi_schedule: List[dict] = field(default_factory=list)

    @classmethod
    def from_sanction_result(cls, result: SanctionResult) -> "LoanAccount":
        """Create a LoanAccount from a SanctionResult."""
        return cls(
            loan_id=result.loan_id,
            borrower_id=result.borrower_id,
            property_id=result.property_id,
            sanctioned_amount=result.sanctioned_amount,
            tenure_months=result.tenure_months,
            interest_rate=result.interest_rate,
            ltv_limit=result.ltv_limit,
            eligibility_limit=result.eligibility_limit,
            processing_fee=result.processing_fee,
            gst_on_fee=result.gst_on_fee,
            sanction_date=result.sanction_date,
            expiry_date=result.expiry_date,
            rule_ids_applied=list(result.rule_ids_applied),
            status=result.status,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DisburseRecord:
    """One released tranche."""
    tranche_no: int
    release_date: date
    amount: Decimal          # net released (after own-contribution deduction)
    demand_date: date
    certification_date: date
    stage_name: str
    stage_pct: Decimal       # cumulative % certified at release
    rules_applied: List[str]
    decision: str            # "RELEASED" | "REJECTED" | "PARTIAL"
    reason: str


@dataclass
class PreEmiBill:
    """Monthly pre-EMI interest bill."""
    bill_no: int
    bill_date: date          # always the 5th of the billing month
    period_from: date        # 1st of the previous month
    period_to: date          # last day of the previous month
    interest_amount: Decimal
    tranche_breakdown: List[dict]  # per-tranche accrual details
    rules_applied: List[str]


@dataclass
class EmiRecord:
    """One EMI in the amortisation schedule."""
    emi_no: int
    due_date: date
    emi_amount: Decimal
    principal_component: Decimal
    interest_component: Decimal
    outstanding_principal: Decimal
    paid_date: Optional[date] = None
    paid_amount: Optional[Decimal] = None
    penal_interest: Decimal = Decimal('0')
    status: str = "PENDING"   # PENDING | PAID | OVERDUE | PART_PAID


@dataclass
class EventLog:
    """Audit log entry for every event processed."""
    event_no: int
    event_date: date
    event_type: str
    loan_id: str
    outcome: str             # "SUCCESS" | "REJECTED" | "PARTIAL" | "INFO"
    reason: str
    rules_applied: List[str]
    details: dict            # event-specific payload
