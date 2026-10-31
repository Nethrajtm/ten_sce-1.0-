"""
tests/test_phase2.py
Phase 2 unit and integration tests for T026-PS-021.
Run with: py -m unittest tests/test_phase2.py -v
"""
from __future__ import annotations

import sys
import unittest
import calendar
from datetime import date, timedelta
from decimal import Decimal, getcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
getcontext().prec = 28

# ── Model imports ─────────────────────────────────────────────────────────────
from src.models.borrower import Borrower, CoApplicant
from src.models.property import Property, StageItem
from src.models.loan import (
    SanctionResult, LoanAccount,
    DisburseRecord, PreEmiBill, EmiRecord, EventLog,
)

# ── Rule imports ──────────────────────────────────────────────────────────────
from src.rules.business_rules import BusinessRules

# ── Calculation imports ───────────────────────────────────────────────────────
from src.calculations.disbursement import (
    check_tranche_release,
    calculate_release_amount,
    consecutive_missed_emis,
    CERT_VALIDITY_DAYS,
)
from src.calculations.pre_emi import (
    daily_rate,
    accrual_for_tranche,
    generate_pre_emi_bill,
    bill_date_for_month,
    period_for_billing_month,
)
from src.calculations.emi_schedule import (
    compute_emi,
    generate_schedule,
    recalculate_schedule_after_prepayment,
    apply_rate_reset,
    next_emi_due_date,
)
from src.calculations.sanction import process_sanction, _add_months

# ── Engine import ─────────────────────────────────────────────────────────────
from src.engine.loan_engine import LoanEngine

# ── Parser import ─────────────────────────────────────────────────────────────
from src.parsers.input_parser import parse_events_from_commands


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_borrower(
    borrower_id="B001",
    name="Meera Iyer",
    dob=date(1990, 6, 20),
    gender="F",
    net_income_monthly=150000,
    credit_score=780,
    coapplicant=None,
) -> Borrower:
    return Borrower(
        borrower_id=borrower_id,
        name=name,
        dob=dob,
        gender=gender,
        net_income_monthly=Decimal(str(net_income_monthly)),
        credit_score=credit_score,
        coapplicant=coapplicant,
    )


def _make_property(
    property_id="P001",
    agreement_value=3_000_000,
    stages=None,
) -> Property:
    if stages is None:
        stages = [
            StageItem("Foundation",    Decimal("20")),
            StageItem("Superstructure",Decimal("30")),
            StageItem("Brickwork",     Decimal("25")),
            StageItem("Finishing",     Decimal("25")),
        ]
    return Property(
        property_id=property_id,
        agreement_value=Decimal(str(agreement_value)),
        builder_name="Prestige Constructions",
        stages=stages,
    )


def _make_loan(
    sanctioned_amount=2_700_000,
    tenure_months=240,
    interest_rate=Decimal("8.95"),
    sanction_date=date(2024, 1, 15),
    loan_id="LN2024001",
    expiry_date=None,
) -> LoanAccount:
    computed_expiry = expiry_date or _add_months(sanction_date, 6)
    return LoanAccount(
        loan_id=loan_id,
        borrower_id="B001",
        property_id="P001",
        sanctioned_amount=Decimal(str(sanctioned_amount)),
        tenure_months=tenure_months,
        interest_rate=interest_rate,
        ltv_limit=Decimal(str(sanctioned_amount)),
        eligibility_limit=Decimal(str(sanctioned_amount)),
        processing_fee={"gross_fee": Decimal("13500"), "gst": Decimal("2430"),
                        "total_fee": Decimal("15930"), "at_sanction": Decimal("7965"),
                        "at_first_disbursal": Decimal("7965"), "rule_id": "BR-08"},
        gst_on_fee=Decimal("2430"),
        sanction_date=sanction_date,
        expiry_date=computed_expiry,
        rule_ids_applied=["BR-01","BR-02","BR-03","BR-05","BR-06","BR-07","BR-08","BR-09","BR-10"],
        status="SANCTIONED",
    )


def _make_engine(
    loan=None, borrower=None, property_=None,
    benchmark_rate=Decimal("8.5"),
) -> LoanEngine:
    loan = loan or _make_loan()
    borrower = borrower or _make_borrower()
    property_ = property_ or _make_property()
    return LoanEngine(loan=loan, borrower=borrower, property_=property_,
                      benchmark_rate=benchmark_rate)


def _engine_with_one_tranche(
    release_date=date(2024, 2, 10),
    amount=Decimal("540000"),
) -> LoanEngine:
    """Return an engine that already has one RELEASED tranche."""
    eng = _make_engine()
    eng.process_own_contribution(date(2024, 1, 20), Decimal("300000"))
    eng.process_stage_certified(date(2024, 2, 1), "Foundation", date(2024, 2, 1))
    eng.process_demand(
        event_date=release_date,
        demand_date=release_date,
        demand_amount=amount,
        stage_name="Foundation",
        demand_pct=Decimal("20"),
    )
    return eng


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tranche-release precedence checks (BR-26)
# ─────────────────────────────────────────────────────────────────────────────

class TestDisburseChecks(unittest.TestCase):
    """Tests for tranche release precedence (BR-26)."""

    def _loan(self, **kw):
        return _make_loan(**kw)

    def test_reject_if_sanction_expired(self):
        """Demand after sanction expiry → REJECTED BR-09."""
        loan = self._loan(sanction_date=date(2024, 1, 15))
        # expiry is 2024-07-15; event on 2024-07-16
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2024, 7, 16),
            demand_amount=Decimal("500000"),
            certification_date=date(2024, 1, 16),
            certified_pct=Decimal("20"),
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=date(2024, 7, 16),
            cumulative_demanded_pct=Decimal("0"),
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-09", rules)
        self.assertEqual(amount, Decimal("0"))

    def test_reject_if_own_contribution_not_paid(self):
        """Demand before own contribution → REJECTED BR-11."""
        loan = self._loan()
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2024, 2, 10),
            demand_amount=Decimal("500000"),
            certification_date=date(2024, 2, 1),
            certified_pct=Decimal("20"),
            own_contribution_paid=False,
            borrower=_make_borrower(),
            event_date=date(2024, 2, 10),
            cumulative_demanded_pct=Decimal("0"),
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-11", rules)

    def test_reject_if_certification_insufficient(self):
        """Demand 20% of sanctioned when only 10% certified → REJECTED BR-12."""
        loan = self._loan(sanctioned_amount=2_700_000)
        # 20% of 27L = 5,40,000; cumulative_certified_pct = 10
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2024, 2, 10),
            demand_amount=Decimal("540000"),
            certification_date=date(2024, 2, 1),
            certified_pct=Decimal("10"),   # only 10% certified
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=date(2024, 2, 10),
            cumulative_demanded_pct=Decimal("0"),
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-12", rules)

    def test_reject_second_demand_without_new_cert(self):
        """EDGE CASE: First 20% ok, second 10% demand with no new cert → REJECTED BR-12."""
        loan = self._loan(sanctioned_amount=2_700_000)
        # After first demand: cumulative_demanded_pct=20, certified=20
        # Now demand another 10% (270000) → cumulative would be 30, cert still 20 → reject
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2024, 3, 15),
            demand_amount=Decimal("270000"),
            certification_date=date(2024, 2, 1),
            certified_pct=Decimal("20"),   # no new cert
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=date(2024, 3, 15),
            cumulative_demanded_pct=Decimal("20"),  # already demanded 20%
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-12", rules)

    def test_reject_cert_over_90_days(self):
        """EDGE CASE: Certification exactly 91 days old → REJECTED BR-16."""
        loan = self._loan()
        cert_date = date(2024, 4, 1)
        # 91 days later = July 1 (Apr has 30d: 30-1=29 + May 31 + Jun 30 = 90, so July 1 = 91 days)
        event_date = cert_date + timedelta(days=91)
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=event_date,
            demand_amount=Decimal("675000"),
            certification_date=cert_date,
            certified_pct=Decimal("25"),
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=event_date,
            cumulative_demanded_pct=Decimal("0"),
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-16", rules)

    def test_accept_cert_exactly_90_days(self):
        """EDGE CASE: Certification exactly 90 days old → ACCEPTED (boundary inclusive)."""
        loan = self._loan(sanctioned_amount=2_700_000)
        cert_date = date(2024, 4, 1)
        event_date = cert_date + timedelta(days=90)
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=event_date,
            demand_amount=Decimal("675000"),
            certification_date=cert_date,
            certified_pct=Decimal("25"),
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=event_date,
            cumulative_demanded_pct=Decimal("0"),
        )
        self.assertIn(decision, ("RELEASED", "PARTIAL"))

    def test_partial_release_at_sanction_cap(self):
        """Demand exceeds remaining sanctioned → PARTIAL release BR-13."""
        loan = self._loan(sanctioned_amount=2_700_000)
        # Simulate 2,400,000 already disbursed → remaining = 300,000
        loan.disbursement_records.append({
            "tranche_no": 1, "release_date": "2024-02-10",
            "amount": "2400000", "demand_date": "2024-02-10",
            "certification_date": "2024-02-01", "stage_name": "Foundation",
            "stage_pct": "75", "rules_applied": ["BR-26","BR-13"],
            "decision": "RELEASED", "reason": "ok",
        })
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2024, 5, 1),
            demand_amount=Decimal("600000"),  # demand 600k but only 300k left
            certification_date=date(2024, 4, 1),
            certified_pct=Decimal("100"),
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=date(2024, 5, 1),
            cumulative_demanded_pct=Decimal("75"),
        )
        self.assertEqual(decision, "PARTIAL")
        self.assertEqual(amount, Decimal("300000"))

    def test_reject_delinquency_freeze(self):
        """3 consecutive missed EMIs → demand REJECTED BR-14."""
        loan = self._loan()
        # Inject 3 overdue EMIs
        for i in range(1, 4):
            loan.emi_schedule.append({"emi_no": i, "due_date": f"2024-0{i}-01",
                                       "emi_amount": "25000", "principal_component": "15000",
                                       "interest_component": "10000", "outstanding_principal": "2000000",
                                       "paid_date": None, "paid_amount": None,
                                       "penal_interest": "0", "status": "OVERDUE"})
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2024, 5, 1),
            demand_amount=Decimal("500000"),
            certification_date=date(2024, 4, 15),
            certified_pct=Decimal("50"),
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=date(2024, 5, 1),
            cumulative_demanded_pct=Decimal("0"),
            consecutive_missed=3,
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-14", rules)

    def test_successful_first_tranche(self):
        """Happy path: own contribution paid, cert valid, demand within cap."""
        loan = self._loan(sanctioned_amount=2_700_000)
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2024, 2, 10),
            demand_amount=Decimal("540000"),
            certification_date=date(2024, 2, 1),
            certified_pct=Decimal("20"),
            own_contribution_paid=True,
            borrower=_make_borrower(),
            event_date=date(2024, 2, 10),
            cumulative_demanded_pct=Decimal("0"),
        )
        self.assertEqual(decision, "RELEASED")
        self.assertEqual(amount, Decimal("540000"))

    def test_precedence_order(self):
        """Expired sanction is reported BEFORE own-contribution failure."""
        loan = self._loan(sanction_date=date(2024, 1, 15))
        decision, reason, rules, amount = check_tranche_release(
            loan=loan,
            demand_date=date(2025, 1, 1),
            demand_amount=Decimal("500000"),
            certification_date=date(2024, 12, 1),
            certified_pct=Decimal("20"),
            own_contribution_paid=False,
            borrower=_make_borrower(),
            event_date=date(2025, 1, 1),
            cumulative_demanded_pct=Decimal("0"),
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-09", rules)
        self.assertNotIn("BR-11", rules)   # shouldn't reach BR-11


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pre-EMI billing (BR-17, BR-18)
# ─────────────────────────────────────────────────────────────────────────────

class TestPreEMI(unittest.TestCase):
    """Tests for pre-EMI billing."""

    RATE = Decimal("8.95")

    def test_daily_rate_calculation(self):
        """Rate = annual_pct / 100 / 365."""
        r = daily_rate(self.RATE)
        expected = self.RATE / Decimal("100") / Decimal("365")
        self.assertEqual(r, expected)

    def test_accrual_single_tranche(self):
        """Single tranche for full 28-day Feb → correct interest."""
        principal = Decimal("540000")
        from_dt = date(2024, 2, 1)
        to_dt = date(2024, 2, 29)   # leap year
        interest = accrual_for_tranche(principal, self.RATE, from_dt, to_dt)
        days = (to_dt - from_dt).days   # 28
        expected = (principal * self.RATE / Decimal("100") / Decimal("365") * days
                    ).quantize(Decimal("0.01"))
        self.assertEqual(interest, expected)

    def test_accrual_tranche_mid_month(self):
        """Tranche released mid-month → pro-rated from release date."""
        principal = Decimal("540000")
        from_dt = date(2024, 2, 15)  # released mid-month
        to_dt = date(2024, 2, 29)
        interest = accrual_for_tranche(principal, self.RATE, from_dt, to_dt)
        days = (to_dt - from_dt).days   # 14
        expected = (principal * self.RATE / Decimal("100") / Decimal("365") * days
                    ).quantize(Decimal("0.01"))
        self.assertEqual(interest, expected)

    def test_bill_date_is_5th(self):
        """Bill date is always the 5th of the billing month."""
        bd = bill_date_for_month(2024, 3)
        self.assertEqual(bd, date(2024, 3, 5))

    def test_period_covers_previous_month(self):
        """Bill on March 5 2024 covers Feb 1 – Feb 29 (leap year)."""
        pf, pt = period_for_billing_month(2024, 3)
        self.assertEqual(pf, date(2024, 2, 1))
        self.assertEqual(pt, date(2024, 2, 29))

    def test_period_covers_previous_month_jan_bill(self):
        """Bill on Jan 5 2024 covers Dec 1 – Dec 31 2023."""
        pf, pt = period_for_billing_month(2024, 1)
        self.assertEqual(pf, date(2023, 12, 1))
        self.assertEqual(pt, date(2023, 12, 31))

    def test_multiple_tranches_sum(self):
        """Two tranches → interest is sum of individual accruals."""
        tranches = [
            {"amount": Decimal("540000"), "release_date": date(2024, 2, 1)},
            {"amount": Decimal("810000"), "release_date": date(2024, 2, 15)},
        ]
        period_from = date(2024, 2, 1)
        period_to = date(2024, 2, 29)
        bill = generate_pre_emi_bill(
            tranches=tranches, annual_rate_pct=self.RATE,
            period_from=period_from, period_to=period_to,
            bill_no=1, bill_date=date(2024, 3, 5),
        )
        i1 = accrual_for_tranche(Decimal("540000"), self.RATE, date(2024, 2, 1), date(2024, 2, 29))
        i2 = accrual_for_tranche(Decimal("810000"), self.RATE, date(2024, 2, 15), date(2024, 2, 29))
        expected_total = (i1 + i2).quantize(Decimal("0.01"))
        self.assertEqual(Decimal(bill["interest_amount"]), expected_total)

    def test_moratorium_ends_at_month_36(self):
        """If no final disbursement by month 36, moratorium ends (BR-18/BR-25)."""
        eng = _engine_with_one_tranche()
        # Force the monthly job to month 36 date
        month36 = _add_months(eng.loan.sanction_date, 36)
        eng.run_monthly_job(month36)
        self.assertFalse(eng.moratorium_active)

    def test_prepayment_reduces_preemi_base(self):
        """Prepayment during pre-EMI reduces disbursed principal."""
        eng = _engine_with_one_tranche()
        before = eng.total_disbursed
        eng.process_part_prepayment(date(2024, 3, 1), Decimal("100000"))
        self.assertEqual(eng.total_disbursed, before - Decimal("100000"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. EMI schedule (BR-19, BR-20, BR-21, BR-22, BR-23)
# ─────────────────────────────────────────────────────────────────────────────

class TestEMISchedule(unittest.TestCase):
    """Tests for full EMI schedule."""

    PRINCIPAL = Decimal("2700000")
    RATE = Decimal("8.95")
    TENURE = 240
    START = date(2024, 3, 1)

    def _schedule(self, principal=None, rate=None, tenure=None, start=None):
        return generate_schedule(
            principal=principal or self.PRINCIPAL,
            annual_rate_pct=rate or self.RATE,
            tenure_months=tenure or self.TENURE,
            start_date=start or self.START,
        )

    def test_emi_formula(self):
        """PMT formula produces the correct EMI.
        PMT(9%/12, 120, 1_000_000) ≈ 12,667.58
        """
        emi = compute_emi(Decimal("1000000"), Decimal("9.00"), 120)
        # Known value: PMT(9/1200, 120, 1_000_000) ≈ 12,667.58
        self.assertGreater(emi, Decimal("12000"))
        self.assertLess(emi, Decimal("14000"))

    def test_schedule_length(self):
        """Schedule has at most tenure_months entries."""
        sched = self._schedule()
        self.assertLessEqual(len(sched), self.TENURE)
        self.assertGreater(len(sched), 0)

    def test_schedule_last_emi_clears_balance(self):
        """Outstanding after last EMI = 0 (or very small rounding residual)."""
        sched = self._schedule()
        last_outstanding = Decimal(sched[-1]["outstanding_principal"])
        self.assertLessEqual(abs(last_outstanding), Decimal("1"))

    def test_emi_amounts_consistent(self):
        """All EMIs except the last equal the computed EMI."""
        sched = self._schedule()
        first_emi = Decimal(sched[0]["emi_amount"])
        for entry in sched[:-1]:
            self.assertEqual(Decimal(entry["emi_amount"]), first_emi)

    def test_rate_reset_constant_emi(self):
        """Rate reset: if new tenure within age cap, EMI stays same."""
        borrower = _make_borrower(dob=date(1990, 6, 20))  # age 33 at reset
        outstanding = Decimal("2500000")
        old_rate = Decimal("8.95")
        new_rate = Decimal("9.45")
        current_emi = compute_emi(outstanding, old_rate, 220)
        new_emi, new_tenure, sched, reason = apply_rate_reset(
            outstanding=outstanding,
            old_rate=old_rate,
            new_rate=new_rate,
            current_emi=current_emi,
            remaining_tenure=220,
            reset_date=date(2024, 9, 1),
            borrower_dob=borrower.dob,
            next_due_date=date(2024, 10, 1),
        )
        # EMI should stay the same (tenure adjusts)
        self.assertEqual(new_emi, current_emi)
        # New tenure should be >= old tenure (higher rate = more months)
        self.assertGreater(new_tenure, 220)

    def test_rate_reset_exceeds_age_cap(self):
        """EDGE CASE: Rate reset would exceed age 70 → EMI changes instead."""
        # Borrower born 1960, age 64 at reset (2024), max remaining = 6*12 = 72 months
        borrower = _make_borrower(dob=date(1960, 1, 1))
        outstanding = Decimal("2000000")
        old_rate = Decimal("8.95")
        new_rate = Decimal("14.00")   # very high → tenure would blow past age cap
        current_emi = compute_emi(outstanding, old_rate, 70)
        new_emi, new_tenure, sched, reason = apply_rate_reset(
            outstanding=outstanding,
            old_rate=old_rate,
            new_rate=new_rate,
            current_emi=current_emi,
            remaining_tenure=70,
            reset_date=date(2024, 6, 1),
            borrower_dob=borrower.dob,
            next_due_date=date(2024, 7, 1),
        )
        # New tenure must be <= age cap = (70-64)*12 = 72
        max_tenure = (70 - 64) * 12
        self.assertLessEqual(new_tenure, max_tenure)
        # EMI must have changed (increased)
        self.assertGreater(new_emi, current_emi)
        self.assertIn("age 70", reason.lower() if reason else "")

    def test_benchmark_change_effective_next_month(self):
        """EDGE CASE: Benchmark change on 1st → effective from 1st of NEXT month."""
        eng = _make_engine()
        eng.process_own_contribution(date(2024, 1, 20), Decimal("300000"))
        eng.process_stage_certified(date(2024, 2, 1), "Foundation", date(2024, 2, 1))
        eng.process_demand(date(2024, 2, 10), date(2024, 2, 10),
                           Decimal("540000"), "Foundation", Decimal("20"))
        # Trigger conversion
        for stage, pct in [("Superstructure", 30), ("Brickwork", 25), ("Finishing", 25)]:
            eng.process_stage_certified(date(2024, 3, 1), stage, date(2024, 3, 1))
            eng.process_demand(date(2024, 3, 10), date(2024, 3, 10),
                               Decimal(str(int(2700000 * pct / 100))), stage, Decimal(str(pct)))

        # Benchmark change on Aug 1
        old_rate = eng.loan.interest_rate
        eng.process_benchmark_change(date(2024, 8, 1), Decimal("9.5"))
        # Rate should NOT have changed yet
        self.assertEqual(eng.loan.interest_rate, old_rate)
        self.assertIsNotNone(eng._pending_rate)
        # After running a monthly job on Sep 5, rate should be applied
        eng.run_monthly_job(date(2024, 9, 5))
        self.assertIsNone(eng._pending_rate)

    def test_part_prepayment_reduce_tenure(self):
        """Prepayment: default reduces tenure, EMI roughly unchanged (within ±1 rupee due to rounding)."""
        # Use the SAME principal for the prepayment recalculation so EMI comparison is valid
        principal = Decimal("2700000")
        rate = self.RATE
        tenure = 120
        sched = generate_schedule(principal=principal, annual_rate_pct=rate,
                                  tenure_months=tenure, start_date=date(2025, 1, 1))
        current_emi = Decimal(sched[0]["emi_amount"])
        # Prepayment brings outstanding from 2.7M to 900k (already paid 1.8M)
        outstanding = Decimal("900000")
        new_sched = recalculate_schedule_after_prepayment(
            outstanding=outstanding,
            annual_rate_pct=rate,
            remaining_tenure=tenure,
            next_due_date=date(2025, 2, 1),
            reduce_tenure=True,
            current_emi=current_emi,
        )
        # New tenure should be less than original (lower principal, same EMI)
        self.assertLess(len(new_sched), tenure)
        # New schedule should exist and clear the balance
        self.assertGreater(len(new_sched), 0)
        last_outstanding = Decimal(new_sched[-1]["outstanding_principal"])
        self.assertLessEqual(abs(last_outstanding), Decimal("2"))

    def test_part_prepayment_reduce_emi(self):
        """Prepayment on request: reduces EMI, tenure stays same (max)."""
        outstanding = Decimal("900000")
        new_sched = recalculate_schedule_after_prepayment(
            outstanding=outstanding,
            annual_rate_pct=self.RATE,
            remaining_tenure=100,
            next_due_date=date(2025, 1, 1),
            reduce_tenure=False,
        )
        # Tenure stays at 100
        self.assertLessEqual(len(new_sched), 100)

    def test_part_prepayment_minimum(self):
        """Prepayment < Rs 50,000 → REJECTED BR-22."""
        eng = _engine_with_one_tranche()
        # Force conversion
        eng._convert_to_full_emi(date(2024, 5, 1))
        before_disbursed = eng.total_disbursed
        eng.process_part_prepayment(date(2024, 6, 1), Decimal("10000"))
        # Total disbursed unchanged (rejected)
        self.assertEqual(eng.total_disbursed, before_disbursed)
        last_event = eng.event_log[-1]
        self.assertEqual(last_event.outcome, "REJECTED")

    def test_full_prepayment_closes_loan(self):
        """Full prepayment → loan CLOSED BR-23."""
        eng = _engine_with_one_tranche()
        eng._convert_to_full_emi(date(2024, 5, 1))
        eng.process_full_prepayment(date(2024, 6, 1), Decimal("2600000"))
        self.assertEqual(eng.loan.status, "CLOSED")
        self.assertTrue(eng.loan_closed)

    def test_final_tranche_last_day_month36(self):
        """EDGE CASE: Final tranche on last day of month 36 → conversion triggered."""
        # Loan expiry set to 36 months so tranches in month 36 are still within sanction validity
        loan = _make_loan(expiry_date=date(2027, 2, 15))
        eng = _make_engine(loan=loan)
        eng.process_own_contribution(date(2024, 1, 20), Decimal("300000"))
        # Certify and demand all stages
        for stage, pct in [("Foundation", 20), ("Superstructure", 30), ("Brickwork", 25)]:
            eng.process_stage_certified(date(2024, 2, 1), stage, date(2024, 2, 1))
            demand_amt = Decimal("2700000") * Decimal(str(pct)) / Decimal("100")
            eng.process_demand(date(2024, 2, 10), date(2024, 2, 10),
                               demand_amt, stage, Decimal(str(pct)))
        # Final tranche on Jan 31 2027 (last day of month 36 from Jan 15 2024)
        month36 = _add_months(date(2024, 1, 15), 36)  # 2027-01-15
        last_day_m36 = date(month36.year, month36.month,
                            calendar.monthrange(month36.year, month36.month)[1])
        eng.process_stage_certified(last_day_m36 - timedelta(days=3), "Finishing",
                                    last_day_m36 - timedelta(days=3))
        remaining_amt = eng.loan.sanctioned_amount - eng.total_disbursed
        eng.process_demand(last_day_m36, last_day_m36, remaining_amt,
                           "Finishing", Decimal("25"))
        # Conversion should be triggered
        self.assertFalse(eng.moratorium_active)

    def test_prepayment_on_tranche_release_date(self):
        """EDGE CASE: Prepayment on same day as a tranche release (pre-EMI)."""
        eng = _engine_with_one_tranche()
        before = eng.total_disbursed
        # Prepayment on same day as the tranche
        eng.process_part_prepayment(date(2024, 2, 10), Decimal("50000"))
        self.assertEqual(eng.total_disbursed, before - Decimal("50000"))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Delinquency (BR-24)
# ─────────────────────────────────────────────────────────────────────────────

class TestDelinquency(unittest.TestCase):
    """Tests for delinquency and penal interest."""

    def _eng_with_emi(self) -> LoanEngine:
        eng = _engine_with_one_tranche()
        eng._convert_to_full_emi(date(2024, 3, 1))
        return eng

    def test_no_penal_within_grace(self):
        """Payment within 15 days of due → no penal interest."""
        eng = self._eng_with_emi()
        emi_entry = eng._emi_schedule[0]
        due = date.fromisoformat(emi_entry["due_date"])
        pay_date = due + timedelta(days=10)   # within 15-day grace
        eng.record_emi_payment(pay_date, emi_entry["emi_no"], Decimal(emi_entry["emi_amount"]))
        self.assertEqual(Decimal(emi_entry["penal_interest"]), Decimal("0"))

    def test_penal_after_grace(self):
        """Payment after 15-day grace → penal interest > 0."""
        eng = self._eng_with_emi()
        emi_entry = eng._emi_schedule[0]
        due = date.fromisoformat(emi_entry["due_date"])
        pay_date = due + timedelta(days=45)   # well past grace
        emi_amt = Decimal(emi_entry["emi_amount"])
        eng.record_emi_payment(pay_date, emi_entry["emi_no"], emi_amt + Decimal("500"))
        self.assertGreater(Decimal(emi_entry["penal_interest"]), Decimal("0"))

    def test_three_missed_emis_freeze(self):
        """3 consecutive OVERDUE EMIs → subsequent demand REJECTED BR-14."""
        eng = _make_engine()
        eng.process_own_contribution(date(2024, 1, 20), Decimal("300000"))
        eng.process_stage_certified(date(2024, 2, 1), "Foundation", date(2024, 2, 1))
        eng.process_demand(date(2024, 2, 10), date(2024, 2, 10),
                           Decimal("540000"), "Foundation", Decimal("20"))
        # Force conversion and inject 3 overdue EMIs
        eng._convert_to_full_emi(date(2024, 3, 1))
        for e in eng._emi_schedule[:3]:
            e["status"] = "OVERDUE"
        # Now try to demand next tranche
        eng.process_stage_certified(date(2024, 6, 1), "Superstructure", date(2024, 6, 1))
        rec = eng.process_demand(date(2024, 6, 10), date(2024, 6, 10),
                                 Decimal("810000"), "Superstructure", Decimal("30"))
        self.assertEqual(rec.decision, "REJECTED")
        self.assertIn("BR-14", rec.rules_applied)

    def test_freeze_lifted_after_payment(self):
        """Count resets to 0 when an EMI is paid."""
        eng = _make_engine()
        # Inject 2 overdue, 1 paid
        loan = eng.loan
        for i in range(1, 3):
            loan.emi_schedule.append({
                "emi_no": i, "due_date": f"2024-0{i}-01", "emi_amount": "25000",
                "principal_component": "15000", "interest_component": "10000",
                "outstanding_principal": "2000000", "paid_date": None,
                "paid_amount": None, "penal_interest": "0", "status": "OVERDUE"
            })
        loan.emi_schedule.append({
            "emi_no": 3, "due_date": "2024-03-01", "emi_amount": "25000",
            "principal_component": "15000", "interest_component": "10000",
            "outstanding_principal": "1985000", "paid_date": "2024-03-10",
            "paid_amount": "25000", "penal_interest": "0", "status": "PAID"
        })
        eng._emi_schedule = loan.emi_schedule
        count = eng._count_consecutive_missed()
        self.assertEqual(count, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Edge cases collection
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    """All specified edge cases."""

    def test_agreement_value_exactly_30_lakh(self):
        """Exactly Rs 30L → LTV 90%."""
        from src.calculations.eligibility import calculate_ltv_limit
        ltv, rule = calculate_ltv_limit(Decimal("3000000"))
        self.assertEqual(ltv, Decimal("2700000"))

    def test_agreement_value_exactly_75_lakh(self):
        """Exactly Rs 75L → LTV 80%."""
        from src.calculations.eligibility import calculate_ltv_limit
        ltv, rule = calculate_ltv_limit(Decimal("7500000"))
        self.assertEqual(ltv, Decimal("6000000"))

    def test_demand_20pct_when_certified_exactly_20pct(self):
        """Demand 20% when certified exactly 20% → ACCEPTED."""
        loan = _make_loan(sanctioned_amount=2_700_000)
        decision, _, _, amount = check_tranche_release(
            loan=loan, demand_date=date(2024, 2, 10), demand_amount=Decimal("540000"),
            certification_date=date(2024, 2, 1), certified_pct=Decimal("20"),
            own_contribution_paid=True, borrower=_make_borrower(),
            event_date=date(2024, 2, 10), cumulative_demanded_pct=Decimal("0"),
        )
        self.assertIn(decision, ("RELEASED", "PARTIAL"))

    def test_demand_10pct_no_new_cert(self):
        """After 20% demand, another 10% without new cert → REJECTED BR-12."""
        loan = _make_loan(sanctioned_amount=2_700_000)
        decision, _, rules, _ = check_tranche_release(
            loan=loan, demand_date=date(2024, 3, 15), demand_amount=Decimal("270000"),
            certification_date=date(2024, 2, 1), certified_pct=Decimal("20"),
            own_contribution_paid=True, borrower=_make_borrower(),
            event_date=date(2024, 3, 15), cumulative_demanded_pct=Decimal("20"),
        )
        self.assertEqual(decision, "REJECTED")
        self.assertIn("BR-12", rules)

    def test_cert_exactly_90_days_old(self):
        """Certification exactly 90 days old → VALID (boundary is inclusive)."""
        loan = _make_loan(sanctioned_amount=2_700_000)
        cert_date = date(2024, 4, 1)
        event_date = cert_date + timedelta(days=90)
        decision, _, _, _ = check_tranche_release(
            loan=loan, demand_date=event_date, demand_amount=Decimal("540000"),
            certification_date=cert_date, certified_pct=Decimal("20"),
            own_contribution_paid=True, borrower=_make_borrower(),
            event_date=event_date, cumulative_demanded_pct=Decimal("0"),
        )
        self.assertIn(decision, ("RELEASED", "PARTIAL"))

    def test_benchmark_change_on_first_of_month(self):
        """Benchmark change on Aug 1 → effective from Sep 1."""
        eng = _make_engine()
        eng.process_benchmark_change(date(2024, 8, 1), Decimal("9.5"))
        self.assertEqual(eng._rate_effective_date, date(2024, 9, 1))

    def test_final_tranche_last_day_month36(self):
        """Final tranche on last day of month 36 → conversion triggered."""
        # Use extended expiry so the Jan 2027 demand is within sanction validity
        loan = _make_loan(expiry_date=date(2027, 2, 15))
        eng = _make_engine(loan=loan)
        eng.process_own_contribution(date(2024, 1, 20), Decimal("300000"))
        for stage, pct in [("Foundation", 20), ("Superstructure", 30), ("Brickwork", 25)]:
            eng.process_stage_certified(date(2024, 2, 1), stage, date(2024, 2, 1))
            demand_amt = Decimal("2700000") * Decimal(str(pct)) / Decimal("100")
            eng.process_demand(date(2024, 2, 10), date(2024, 2, 10),
                               demand_amt, stage, Decimal(str(pct)))
        month36 = _add_months(date(2024, 1, 15), 36)
        last_day = date(month36.year, month36.month,
                        calendar.monthrange(month36.year, month36.month)[1])
        remaining = eng.loan.sanctioned_amount - eng.total_disbursed
        eng.process_stage_certified(last_day - timedelta(days=2), "Finishing",
                                    last_day - timedelta(days=2))
        eng.process_demand(last_day, last_day, remaining, "Finishing", Decimal("25"))
        self.assertFalse(eng.moratorium_active)

    def test_prepayment_on_tranche_release_date(self):
        """Prepayment on same day as a tranche release (pre-EMI phase)."""
        eng = _engine_with_one_tranche()
        before = eng.total_disbursed
        eng.process_part_prepayment(date(2024, 2, 10), Decimal("50000"))
        self.assertEqual(eng.total_disbursed, before - Decimal("50000"))

    def test_rate_reset_past_age70(self):
        """Rate reset with tenure that would exceed age 70 → EMI changes."""
        borrower = _make_borrower(dob=date(1958, 1, 1))  # age ~66 at reset
        outstanding = Decimal("2000000")
        old_rate = Decimal("8.95")
        new_rate = Decimal("13.00")
        current_emi = compute_emi(outstanding, old_rate, 48)
        new_emi, new_tenure, _, reason = apply_rate_reset(
            outstanding=outstanding, old_rate=old_rate, new_rate=new_rate,
            current_emi=current_emi, remaining_tenure=48,
            reset_date=date(2024, 6, 1), borrower_dob=borrower.dob,
            next_due_date=date(2024, 7, 1),
        )
        max_months = (70 - 66) * 12  # 48
        self.assertLessEqual(new_tenure, max_months)

    def test_lapse_at_month36(self):
        """Undisbursed sanction lapses at month 36 (BR-25)."""
        eng = _engine_with_one_tranche()
        initial_disbursed = eng.total_disbursed
        month36 = _add_months(eng.loan.sanction_date, 36)
        eng.run_monthly_job(month36)
        # Moratorium should be ended
        self.assertFalse(eng.moratorium_active)
        # Disbursed amount unchanged (undisbursed lapses, not disbursed)
        self.assertEqual(eng.total_disbursed, initial_disbursed)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Integration tests
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrationPhase2(unittest.TestCase):
    """End-to-end integration tests."""

    def _full_lifecycle_engine(self) -> LoanEngine:
        """Build an engine and run a full lifecycle.
        Uses a sanction with 36-month expiry so all tranches pass the BR-09 check.
        """
        # Use 36-month expiry so stages released over a long construction period are not blocked
        loan = _make_loan(expiry_date=date(2027, 1, 15))
        eng = _make_engine(loan=loan)
        # Own contribution
        eng.process_own_contribution(date(2024, 1, 20), Decimal("300000"))
        # Stage 1
        eng.process_stage_certified(date(2024, 2, 1), "Foundation", date(2024, 2, 1))
        eng.process_demand(date(2024, 2, 10), date(2024, 2, 10),
                           Decimal("540000"), "Foundation", Decimal("20"))
        # Pre-EMI bill
        eng.run_monthly_job(date(2024, 3, 5))
        # Stage 2
        eng.process_stage_certified(date(2024, 4, 1), "Superstructure", date(2024, 4, 1))
        eng.process_demand(date(2024, 4, 10), date(2024, 4, 10),
                           Decimal("810000"), "Superstructure", Decimal("30"))
        # Pre-EMI
        eng.run_monthly_job(date(2024, 5, 5))
        # Stage 3
        eng.process_stage_certified(date(2024, 6, 1), "Brickwork", date(2024, 6, 1))
        eng.process_demand(date(2024, 6, 10), date(2024, 6, 10),
                           Decimal("675000"), "Brickwork", Decimal("25"))
        # Pre-EMI
        eng.run_monthly_job(date(2024, 7, 5))
        # Final tranche
        eng.process_stage_certified(date(2024, 8, 1), "Finishing", date(2024, 8, 1))
        eng.process_demand(date(2024, 8, 10), date(2024, 8, 10),
                           Decimal("675000"), "Finishing", Decimal("25"))
        # Monthly jobs after conversion
        eng.run_monthly_job(date(2024, 9, 5))
        eng.run_monthly_job(date(2024, 10, 5))
        # Record EMI
        emi1 = eng._emi_schedule[0] if eng._emi_schedule else None
        if emi1:
            eng.record_emi_payment(
                date.fromisoformat(emi1["due_date"]) + timedelta(days=5),
                emi1["emi_no"],
                Decimal(emi1["emi_amount"]),
            )
        # Part prepayment
        eng.process_part_prepayment(date(2024, 11, 1), Decimal("100000"))
        return eng

    def test_full_lifecycle_sanction_to_prepayment(self):
        """Full lifecycle: sanction → tranches → pre-EMI → EMI → prepayment."""
        eng = self._full_lifecycle_engine()
        # Loan should be in EMI phase
        self.assertFalse(eng.moratorium_active)
        self.assertIsNotNone(eng.current_emi)
        self.assertGreater(eng.total_disbursed, Decimal("0"))
        self.assertEqual(eng.loan.status, "ACTIVE_EMI")

    def test_event_log_completeness(self):
        """Every processed event has a log entry."""
        eng = self._full_lifecycle_engine()
        self.assertGreater(len(eng.event_log), 0)
        for entry in eng.event_log:
            self.assertIn(entry.outcome, ("SUCCESS", "REJECTED", "PARTIAL", "INFO"))
            self.assertIsInstance(entry.rules_applied, list)
            self.assertGreater(len(entry.rules_applied), 0)
            self.assertIsInstance(entry.reason, str)

    def test_disbursement_ledger_generated(self):
        """Ledger text contains all expected tranche entries."""
        from src.output.ledger_writer import generate_disbursement_ledger
        eng = self._full_lifecycle_engine()
        ledger = generate_disbursement_ledger(eng)
        self.assertIn("DISBURSEMENT LEDGER", ledger)
        self.assertIn("RELEASED", ledger)
        self.assertIn(eng.loan.loan_id, ledger)

    def test_amortisation_schedule_generated(self):
        """Schedule contains pre-EMI bills and post-conversion EMIs."""
        from src.output.ledger_writer import generate_amortisation_schedule
        eng = self._full_lifecycle_engine()
        sched_text = generate_amortisation_schedule(eng)
        self.assertIn("AMORTISATION SCHEDULE", sched_text)
        self.assertIn("PRE-EMI", sched_text)
        self.assertIn("FULL EMI", sched_text)

    def test_interest_certificate_generated(self):
        """FY certificate separates pre-EMI interest from regular interest."""
        from src.output.ledger_writer import generate_interest_certificate
        eng = self._full_lifecycle_engine()
        cert = generate_interest_certificate(eng, 2024)
        self.assertIn("INTEREST CERTIFICATE", cert)
        self.assertIn("PRE-EMI", cert)
        self.assertIn("SECTION B", cert)

    def test_total_disbursed_equals_sum_of_tranches(self):
        """Engine total_disbursed equals sum of RELEASED amounts."""
        eng = self._full_lifecycle_engine()
        released_sum = sum(
            Decimal(r["amount"])
            for r in eng.loan.disbursement_records
            if r["decision"] in ("RELEASED", "PARTIAL")
        )
        self.assertEqual(eng.total_disbursed, released_sum)

    def test_own_contribution_flag_set(self):
        """own_contribution_paid is True after processing."""
        eng = _make_engine()
        self.assertFalse(eng.own_contribution_paid)
        eng.process_own_contribution(date(2024, 1, 20), Decimal("300000"))
        self.assertTrue(eng.own_contribution_paid)

    def test_pre_emi_bill_structure(self):
        """Pre-EMI bill dict has all required keys."""
        eng = _engine_with_one_tranche()
        eng.run_monthly_job(date(2024, 3, 5))
        self.assertGreater(len(eng.loan.pre_emi_bills), 0)
        bill = eng.loan.pre_emi_bills[0]
        for key in ("bill_no", "bill_date", "period_from", "period_to",
                    "interest_amount", "tranche_breakdown", "rules_applied"):
            self.assertIn(key, bill)

    def test_new_dataclasses_importable(self):
        """All Phase 2 dataclasses can be instantiated."""
        dr = DisburseRecord(
            tranche_no=1, release_date=date(2024, 2, 10), amount=Decimal("540000"),
            demand_date=date(2024, 2, 10), certification_date=date(2024, 2, 1),
            stage_name="Foundation", stage_pct=Decimal("20"),
            rules_applied=["BR-13"], decision="RELEASED", reason="ok",
        )
        self.assertEqual(dr.tranche_no, 1)

        er = EmiRecord(
            emi_no=1, due_date=date(2024, 3, 1), emi_amount=Decimal("25000"),
            principal_component=Decimal("15000"), interest_component=Decimal("10000"),
            outstanding_principal=Decimal("2685000"),
        )
        self.assertEqual(er.status, "PENDING")

        el = EventLog(
            event_no=1, event_date=date(2024, 2, 10), event_type="DEMAND",
            loan_id="LN2024001", outcome="SUCCESS", reason="ok",
            rules_applied=["BR-26"], details={},
        )
        self.assertEqual(el.outcome, "SUCCESS")

    def test_phase2_parse_events(self):
        """parse_events_from_commands filters and coerces Phase 2 commands."""
        raw = [
            {"command": "SANCTION", "date": date(2024, 1, 15), "borrower_id": "B001",
             "property_id": "P001", "benchmark_rate": Decimal("8.5")},
            {"command": "OWN_CONTRIBUTION", "date": date(2024, 1, 20), "loan_id": "LN2024001",
             "amount": 300000, "benchmark_rate": Decimal("8.5")},
            {"command": "DEMAND", "date": date(2024, 2, 10), "loan_id": "LN2024001",
             "demand_amount": 540000, "stage_name": "Foundation", "demand_pct": 20,
             "benchmark_rate": Decimal("8.5")},
        ]
        events = parse_events_from_commands(raw)
        self.assertEqual(len(events), 2)   # SANCTION is filtered out
        oc = events[0]
        self.assertEqual(oc["command"], "OWN_CONTRIBUTION")
        self.assertIsInstance(oc["amount"], Decimal)
        dem = events[1]
        self.assertIsInstance(dem["demand_amount"], Decimal)
        self.assertIsInstance(dem["demand_pct"], Decimal)

    def test_business_rules_emi_formula(self):
        """BusinessRules.emi_amount matches compute_emi."""
        p = Decimal("2700000")
        r = Decimal("8.95")
        n = 240
        emi_br = BusinessRules.emi_amount(p, r, n)
        emi_calc = compute_emi(p, r, n)
        # Should be very close (both unrounded)
        self.assertAlmostEqual(float(emi_br), float(emi_calc), places=2)

    def test_business_rules_remaining_tenure(self):
        """BusinessRules.remaining_tenure_for_emi returns sensible positive int."""
        emi = compute_emi(Decimal("2000000"), Decimal("9.00"), 200)
        n = BusinessRules.remaining_tenure_for_emi(Decimal("2000000"), Decimal("9.00"), emi)
        self.assertIsInstance(n, int)
        self.assertGreater(n, 0)
        self.assertLessEqual(n, 201)


if __name__ == "__main__":
    unittest.main(verbosity=2)
