"""
src/engine/loan_engine.py
Main event-processing engine for Phase 2.
Processes DEMAND, STAGE_CERTIFIED, BENCHMARK_CHANGE, MONTHLY_JOB,
RECORD_EMI, PREPAYMENT_PART, PREPAYMENT_FULL events.
Maintains a LoanAccount and deterministic EventLog.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Optional

from src.models.borrower import Borrower
from src.models.property import Property
from src.models.loan import LoanAccount, DisburseRecord, PreEmiBill, EmiRecord, EventLog
from src.rules.business_rules import BusinessRules
from src.calculations.disbursement import (
    check_tranche_release,
    calculate_release_amount,
    consecutive_missed_emis,
    CERT_VALIDITY_DAYS,
)
from src.calculations.pre_emi import (
    generate_pre_emi_bill,
    period_for_billing_month,
    bill_date_for_month,
    accrual_for_tranche,
)
from src.calculations.emi_schedule import (
    compute_emi,
    generate_schedule,
    recalculate_schedule_after_prepayment,
    apply_rate_reset,
    next_emi_due_date,
)
from src.calculations.sanction import _add_months

getcontext().prec = 28


class LoanEngine:
    """
    Stateful engine that processes events for one loan account.
    All state is held in self.loan (LoanAccount), self.event_log (list[EventLog]).
    """

    def __init__(
        self,
        loan: LoanAccount,
        borrower: Borrower,
        property_: Property,
        benchmark_rate: Decimal,
    ):
        self.loan = loan
        self.borrower = borrower
        self.property_ = property_
        self.benchmark_rate = benchmark_rate
        self.event_log: list[EventLog] = []
        self._event_counter = 0

        # Runtime state
        self.own_contribution_paid: bool = False
        self.certified_stages: dict[str, date] = {}     # stage_name -> certification_date
        self.cumulative_certified_pct: Decimal = Decimal('0')
        self.cumulative_demanded_pct: Decimal = Decimal('0')
        self.total_disbursed: Decimal = Decimal('0')
        self.moratorium_active: bool = True
        self.final_disbursement_date: Optional[date] = None
        self.conversion_month: Optional[int] = None     # EMI month number (1-based)
        self.emi_start_date: Optional[date] = None
        self.current_emi: Optional[Decimal] = None
        self.remaining_tenure: Optional[int] = None
        self.loan_closed: bool = False
        self._tranche_counter: int = 0
        self._bill_counter: int = 0
        self._pre_emi_bills: list[dict] = []    # internal list of pre-EMI bills as dicts
        self._disbursements: list[DisburseRecord] = []  # typed records
        self._emi_schedule: list[dict] = []     # current live EMI schedule

        # Track benchmark change effective date
        self._pending_rate: Optional[Decimal] = None
        self._rate_effective_date: Optional[date] = None

    # ─────────────────────────────────────────────────────────────────────────
    # Internal logging helper
    # ─────────────────────────────────────────────────────────────────────────

    def _log(
        self,
        event_date: date,
        event_type: str,
        outcome: str,
        reason: str,
        rules: list[str],
        details: dict = None,
    ) -> EventLog:
        self._event_counter += 1
        entry = EventLog(
            event_no=self._event_counter,
            event_date=event_date,
            event_type=event_type,
            loan_id=self.loan.loan_id,
            outcome=outcome,
            reason=reason,
            rules_applied=rules,
            details=details or {},
        )
        self.event_log.append(entry)
        return entry

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: latest certification date for a stage or any stage
    # ─────────────────────────────────────────────────────────────────────────

    def _latest_cert_date(self, stage_name: Optional[str] = None) -> Optional[date]:
        if stage_name and stage_name in self.certified_stages:
            return self.certified_stages[stage_name]
        if self.certified_stages:
            return max(self.certified_stages.values())
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Event handlers
    # ─────────────────────────────────────────────────────────────────────────

    def process_own_contribution(self, event_date: date, amount: Decimal):
        """Mark own contribution as paid (BR-11)."""
        own_contribution = self.property_.agreement_value - self.loan.sanctioned_amount
        self.own_contribution_paid = True
        self._log(
            event_date, "OWN_CONTRIBUTION", "SUCCESS",
            f"Own contribution Rs {amount:,.2f} received (required Rs {own_contribution:,.2f}). BR-11 satisfied.",
            ["BR-11"],
            {"amount": str(amount), "required": str(own_contribution)},
        )

    def process_stage_certified(
        self,
        event_date: date,
        stage_name: str,
        certification_date: date,
    ):
        """Record a stage certification."""
        # Find the stage percentage from property
        stage_pct = Decimal('0')
        for s in self.property_.stages:
            if s.stage_name == stage_name:
                stage_pct = s.percentage
                break

        self.certified_stages[stage_name] = certification_date
        # Update cumulative certified pct based on all certified stages
        self.cumulative_certified_pct = sum(
            s.percentage for s in self.property_.stages
            if s.stage_name in self.certified_stages
        )

        self._log(
            event_date, "STAGE_CERTIFIED", "INFO",
            f"Stage '{stage_name}' certified on {certification_date}. "
            f"Cumulative certified: {self.cumulative_certified_pct:.2f}%.",
            ["BR-12", "BR-16"],
            {
                "stage_name": stage_name,
                "certification_date": certification_date.isoformat(),
                "stage_pct": str(stage_pct),
                "cumulative_certified_pct": str(self.cumulative_certified_pct),
            },
        )

    def process_demand(
        self,
        event_date: date,
        demand_date: date,
        demand_amount: Decimal,
        stage_name: str,
        demand_pct: Decimal,    # % of agreement value being demanded
    ) -> DisburseRecord:
        """
        Process a builder DEMAND event.
        Apply BR-26 precedence checks, compute release, update state.
        """
        if self.loan_closed:
            rec = self._make_disburse_record(
                "REJECTED", "Loan is closed.", ["BR-23"], Decimal('0'),
                demand_date, event_date, stage_name,
            )
            self._log(event_date, "DEMAND", "REJECTED", "Loan is closed.", ["BR-23"],
                      {"stage_name": stage_name, "demand_amount": str(demand_amount)})
            return rec

        # Apply rate if pending
        self._apply_pending_rate_if_due(event_date)

        # Get the freshest certification date for this stage (or any stage)
        cert_date = self._latest_cert_date(stage_name) or self._latest_cert_date()

        if cert_date is None:
            rec = self._make_disburse_record(
                "REJECTED", "No stage certification found (BR-12).", ["BR-12", "BR-26"],
                Decimal('0'), demand_date, event_date, stage_name,
            )
            self._log(event_date, "DEMAND", "REJECTED", "No stage certification on file.",
                      ["BR-12", "BR-26"],
                      {"stage_name": stage_name, "demand_amount": str(demand_amount)})
            return rec

        # Calculate what cumulative % this demand represents
        # demand_pct is % of agreement_value; convert to % of sanctioned_amount for cap check
        demand_pct_of_sanctioned = (
            demand_amount / self.loan.sanctioned_amount * Decimal('100')
        )

        missed = self._count_consecutive_missed()

        decision, reason, rules_applied, release_amount = check_tranche_release(
            loan=self.loan,
            demand_date=demand_date,
            demand_amount=demand_amount,
            certification_date=cert_date,
            certified_pct=self.cumulative_certified_pct,
            own_contribution_paid=self.own_contribution_paid,
            borrower=self.borrower,
            event_date=event_date,
            cumulative_demanded_pct=self.cumulative_demanded_pct,
            consecutive_missed=missed,
        )

        self._tranche_counter += 1 if decision != "REJECTED" else 0

        # Build DisburseRecord
        rec = DisburseRecord(
            tranche_no=self._tranche_counter,
            release_date=event_date,
            amount=release_amount,
            demand_date=demand_date,
            certification_date=cert_date,
            stage_name=stage_name,
            stage_pct=self.cumulative_certified_pct,
            rules_applied=rules_applied,
            decision=decision,
            reason=reason,
        )

        if decision in ("RELEASED", "PARTIAL"):
            self.total_disbursed += release_amount
            self.cumulative_demanded_pct += demand_pct

            # Add to loan disbursement records as dict
            self.loan.disbursement_records.append({
                "tranche_no": rec.tranche_no,
                "release_date": rec.release_date.isoformat(),
                "amount": str(rec.amount),
                "demand_date": rec.demand_date.isoformat(),
                "certification_date": rec.certification_date.isoformat(),
                "stage_name": rec.stage_name,
                "stage_pct": str(rec.stage_pct),
                "rules_applied": rec.rules_applied,
                "decision": rec.decision,
                "reason": rec.reason,
            })
            self._disbursements.append(rec)

            # Check if this is the final tranche:
            # Either remaining sanctioned <= 1 rupee OR all property stages have been demanded
            remaining = self.loan.sanctioned_amount - self.total_disbursed
            total_stage_pct = sum(s.percentage for s in self.property_.stages)
            all_stages_done = self.cumulative_demanded_pct >= total_stage_pct
            if remaining <= Decimal('1') or all_stages_done:
                self.final_disbursement_date = event_date
                if self.moratorium_active:
                    self._convert_to_full_emi(event_date)

        # Map decision to a valid outcome code for EventLog
        outcome = decision if decision in ("REJECTED", "PARTIAL") else "SUCCESS"
        self._log(
            event_date, "DEMAND", outcome,
            reason, rules_applied,
            {
                "stage_name": stage_name,
                "demand_amount": str(demand_amount),
                "release_amount": str(release_amount),
                "total_disbursed": str(self.total_disbursed),
                "remaining_sanctioned": str(self.loan.sanctioned_amount - self.total_disbursed),
            },
        )
        return rec

    def run_monthly_job(self, job_date: date):
        """
        Run the monthly job for a given date.
        1. Apply any pending rate change if due.
        2. If moratorium active: generate pre-EMI bill (5th of month for prev month).
        3. If converted: post next EMI due, check for overdue/penal.
        4. Check for month-36 lapse (BR-25).
        """
        self._apply_pending_rate_if_due(job_date)

        # Month-36 lapse check
        self._check_month36_lapse(job_date)

        if self.moratorium_active:
            # Generate pre-EMI bill if we have disbursements
            if self._disbursements:
                self._generate_pre_emi_bill_for_date(job_date)
        else:
            # Post EMI dues and check overdue
            self._post_emi_overdue(job_date)

        self._log(
            job_date, "MONTHLY_JOB", "INFO",
            f"Monthly job run. Moratorium: {self.moratorium_active}. "
            f"Total disbursed: Rs {self.total_disbursed:,.2f}.",
            ["BR-17", "BR-18", "BR-19", "BR-24", "BR-25"],
            {
                "moratorium_active": self.moratorium_active,
                "total_disbursed": str(self.total_disbursed),
                "loan_closed": self.loan_closed,
            },
        )

    def process_benchmark_change(self, event_date: date, new_benchmark: Decimal):
        """
        BR-21: Update benchmark. Rate reset takes effect on the 1st of next month.
        """
        # Compute new interest rate using same spread
        from src.calculations.eligibility import calculate_interest_rate
        new_rate, _ = calculate_interest_rate(
            new_benchmark, self.borrower.credit_score, self.borrower.gender
        )

        # Rate effective from 1st of next month
        eff_month = event_date.month + 1
        eff_year = event_date.year
        if eff_month > 12:
            eff_month = 1
            eff_year += 1
        effective_date = date(eff_year, eff_month, 1)

        self._pending_rate = new_rate
        self._rate_effective_date = effective_date
        old_rate = self.loan.interest_rate
        self.benchmark_rate = new_benchmark

        self._log(
            event_date, "BENCHMARK_CHANGE", "INFO",
            f"Benchmark changed to {new_benchmark}%. New rate {new_rate}% effective from {effective_date}.",
            ["BR-21"],
            {
                "old_benchmark": str(old_rate),
                "new_benchmark": str(new_benchmark),
                "new_rate": str(new_rate),
                "effective_date": effective_date.isoformat(),
            },
        )

    def record_emi_payment(self, event_date: date, emi_no: int, amount: Decimal):
        """
        Post an EMI payment. Check grace period, compute penal if late (BR-24).
        """
        schedule = self._emi_schedule
        # Find the EMI in schedule
        target = None
        for entry in schedule:
            if entry["emi_no"] == emi_no:
                target = entry
                break

        if target is None:
            self._log(event_date, "RECORD_EMI", "REJECTED",
                      f"EMI #{emi_no} not found in schedule.", ["BR-24"],
                      {"emi_no": emi_no, "amount": str(amount)})
            return

        due_date = date.fromisoformat(target["due_date"])
        emi_amount = Decimal(target["emi_amount"])

        # Check penal interest (BR-24): 2% per month on overdue after 15-day grace
        penal = Decimal('0')
        grace_end = due_date + timedelta(days=BusinessRules.GRACE_DAYS)
        if event_date > grace_end:
            days_overdue = (event_date - grace_end).days
            months_overdue = Decimal(str(days_overdue)) / Decimal('30')
            penal = (emi_amount * BusinessRules.PENAL_RATE_PER_MONTH * months_overdue).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        total_due = emi_amount + penal
        status = "PAID" if amount >= total_due else "PART_PAID"

        target["paid_date"] = event_date.isoformat()
        target["paid_amount"] = str(amount)
        target["penal_interest"] = str(penal)
        target["status"] = status

        # Sync to loan.emi_schedule
        self.loan.emi_schedule = self._emi_schedule

        self._log(
            event_date, "RECORD_EMI", "SUCCESS",
            f"EMI #{emi_no} recorded. Status: {status}. Penal: Rs {penal:,.2f}.",
            ["BR-24"],
            {
                "emi_no": emi_no,
                "due_date": due_date.isoformat(),
                "emi_amount": str(emi_amount),
                "paid_amount": str(amount),
                "penal_interest": str(penal),
                "status": status,
            },
        )

    def process_part_prepayment(
        self,
        event_date: date,
        amount: Decimal,
        reduce_tenure: bool = True,
    ):
        """
        BR-22: Part prepayment.
        - Minimum Rs 50,000.
        - If during pre-EMI: reduces disbursed principal.
        - If during EMI: reduces outstanding, recalculates schedule.
        """
        if self.loan_closed:
            self._log(event_date, "PREPAYMENT_PART", "REJECTED",
                      "Loan is already closed.", ["BR-23"], {"amount": str(amount)})
            return

        if amount < BusinessRules.MIN_PREPAYMENT:
            self._log(
                event_date, "PREPAYMENT_PART", "REJECTED",
                f"Prepayment Rs {amount:,.2f} is below minimum Rs {BusinessRules.MIN_PREPAYMENT:,.2f} (BR-22).",
                ["BR-22"],
                {"amount": str(amount), "minimum": str(BusinessRules.MIN_PREPAYMENT)},
            )
            return

        if self.moratorium_active:
            # Pre-EMI: reduce total disbursed principal
            self.total_disbursed = max(Decimal('0'), self.total_disbursed - amount)
            self._log(
                event_date, "PREPAYMENT_PART", "SUCCESS",
                f"Pre-EMI prepayment Rs {amount:,.2f}. New disbursed principal: Rs {self.total_disbursed:,.2f}.",
                ["BR-22"],
                {
                    "amount": str(amount),
                    "new_total_disbursed": str(self.total_disbursed),
                    "phase": "pre_emi",
                },
            )
            return

        # During EMI phase
        # Find current outstanding from schedule
        outstanding = self._current_outstanding()
        if outstanding is None:
            self._log(event_date, "PREPAYMENT_PART", "REJECTED",
                      "No EMI schedule active.", ["BR-22"], {"amount": str(amount)})
            return

        new_outstanding = outstanding - amount
        if new_outstanding <= Decimal('0'):
            # Full closure
            self.process_full_prepayment(event_date, amount)
            return

        # Find next due date and remaining tenure
        next_due, rem_tenure = self._next_pending_emi_info(event_date)
        if next_due is None:
            self._log(event_date, "PREPAYMENT_PART", "REJECTED",
                      "No pending EMIs in schedule.", ["BR-22"], {"amount": str(amount)})
            return

        new_schedule = recalculate_schedule_after_prepayment(
            outstanding=new_outstanding,
            annual_rate_pct=self.loan.interest_rate,
            remaining_tenure=rem_tenure,
            next_due_date=next_due,
            reduce_tenure=reduce_tenure,
            current_emi=self.current_emi,
        )
        self._emi_schedule = new_schedule
        self.loan.emi_schedule = new_schedule
        if new_schedule:
            self.current_emi = Decimal(new_schedule[0]["emi_amount"])
            self.remaining_tenure = len(new_schedule)

        self._log(
            event_date, "PREPAYMENT_PART", "SUCCESS",
            f"Prepayment Rs {amount:,.2f}. New outstanding: Rs {new_outstanding:,.2f}. "
            f"Schedule recalculated ({len(new_schedule)} EMIs).",
            ["BR-22"],
            {
                "amount": str(amount),
                "old_outstanding": str(outstanding),
                "new_outstanding": str(new_outstanding),
                "reduce_tenure": reduce_tenure,
                "new_tenure": len(new_schedule),
            },
        )

    def process_full_prepayment(self, event_date: date, amount: Decimal):
        """BR-23: Full prepayment closes the loan."""
        if self.loan_closed:
            self._log(event_date, "PREPAYMENT_FULL", "REJECTED",
                      "Loan is already closed.", ["BR-23"], {"amount": str(amount)})
            return

        outstanding = self.total_disbursed if self.moratorium_active else (
            self._current_outstanding() or Decimal('0')
        )
        self.loan_closed = True
        self.loan.status = "CLOSED"
        # Mark all pending EMIs as PAID
        for entry in self._emi_schedule:
            if entry["status"] == "PENDING":
                entry["status"] = "PAID"
                entry["paid_date"] = event_date.isoformat()
                entry["paid_amount"] = entry["emi_amount"]
        self.loan.emi_schedule = self._emi_schedule

        self._log(
            event_date, "PREPAYMENT_FULL", "SUCCESS",
            f"Full prepayment Rs {amount:,.2f}. Loan CLOSED (BR-23).",
            ["BR-23"],
            {
                "amount": str(amount),
                "outstanding_cleared": str(outstanding),
            },
        )

    def _convert_to_full_emi(self, conversion_date: date):
        """
        BR-19/BR-20: Convert from pre-EMI to full EMI.
        EMI start date = first of month after conversion_date.
        EMI computed on total_disbursed for remaining tenure.
        """
        self.moratorium_active = False

        # EMI start date: 1st of month AFTER conversion_date
        emi_month = conversion_date.month + 1
        emi_year = conversion_date.year
        if emi_month > 12:
            emi_month = 1
            emi_year += 1
        self.emi_start_date = date(emi_year, emi_month, 1)

        # Compute months elapsed since sanction to determine remaining tenure
        sanction = self.loan.sanction_date
        months_elapsed = (conversion_date.year - sanction.year) * 12 + (
            conversion_date.month - sanction.month
        )
        remaining = max(1, self.loan.tenure_months - months_elapsed)
        self.remaining_tenure = remaining

        # Compute EMI on total_disbursed
        self.current_emi = compute_emi(self.total_disbursed, self.loan.interest_rate, remaining)

        # Generate schedule
        self._emi_schedule = generate_schedule(
            self.total_disbursed, self.loan.interest_rate, remaining, self.emi_start_date
        )
        self.loan.emi_schedule = self._emi_schedule

        self.loan.status = "ACTIVE_EMI"

        self._log(
            conversion_date, "CONVERSION", "SUCCESS",
            f"Converted to full EMI. Principal: Rs {self.total_disbursed:,.2f}, "
            f"EMI: Rs {self.current_emi:,.2f}, Tenure: {remaining} months from {self.emi_start_date}.",
            ["BR-19", "BR-20"],
            {
                "total_disbursed": str(self.total_disbursed),
                "emi_amount": str(self.current_emi),
                "remaining_tenure": remaining,
                "emi_start_date": self.emi_start_date.isoformat(),
            },
        )

    def _check_month36_lapse(self, job_date: date):
        """BR-25: If moratorium still active at month 36, lapse undisbursed and convert."""
        if not self.moratorium_active:
            return
        month36_date = _add_months(self.loan.sanction_date, 36)
        if job_date >= month36_date:
            undisbursed = self.loan.sanctioned_amount - self.total_disbursed
            if undisbursed > Decimal('0'):
                self._log(
                    job_date, "SANCTION_LAPSE", "INFO",
                    f"Month 36 reached. Undisbursed Rs {undisbursed:,.2f} lapses (BR-25). "
                    f"Converting to full EMI.",
                    ["BR-25", "BR-19", "BR-20"],
                    {
                        "month36_date": month36_date.isoformat(),
                        "undisbursed": str(undisbursed),
                        "total_disbursed": str(self.total_disbursed),
                    },
                )
            if self.total_disbursed > Decimal('0'):
                self.final_disbursement_date = job_date
                self._convert_to_full_emi(job_date)
            else:
                self.moratorium_active = False
                self.loan.status = "LAPSED"
                self._log(
                    job_date, "SANCTION_LAPSE", "INFO",
                    "Month 36 reached with zero disbursement. Loan lapsed.",
                    ["BR-25"],
                    {},
                )

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _generate_pre_emi_bill_for_date(self, job_date: date):
        """Generate a pre-EMI bill for the month preceding job_date."""
        period_from, period_to = period_for_billing_month(job_date.year, job_date.month)
        bill_dt = bill_date_for_month(job_date.year, job_date.month)

        tranches = [
            {
                "amount": d.amount,
                "release_date": d.release_date,
            }
            for d in self._disbursements
            if d.decision in ("RELEASED", "PARTIAL")
        ]

        if not tranches:
            return

        self._bill_counter += 1
        bill = generate_pre_emi_bill(
            tranches=tranches,
            annual_rate_pct=self.loan.interest_rate,
            period_from=period_from,
            period_to=period_to,
            bill_no=self._bill_counter,
            bill_date=bill_dt,
        )
        self._pre_emi_bills.append(bill)
        self.loan.pre_emi_bills.append(bill)

    def _apply_pending_rate_if_due(self, event_date: date):
        """Apply a pending benchmark rate change if it's effective now."""
        if self._pending_rate is None:
            return
        if event_date < self._rate_effective_date:
            return

        new_rate = self._pending_rate
        self._pending_rate = None
        self._rate_effective_date = None

        old_rate = self.loan.interest_rate
        self.loan.interest_rate = new_rate

        # If EMI is active, apply rate reset (BR-21)
        if not self.moratorium_active and self._emi_schedule and not self.loan_closed:
            outstanding = self._current_outstanding()
            if outstanding and outstanding > Decimal('0') and self.current_emi:
                next_due, rem_tenure = self._next_pending_emi_info(event_date)
                if next_due is not None:
                    new_emi, new_tenure, new_schedule, reason = apply_rate_reset(
                        outstanding=outstanding,
                        old_rate=old_rate,
                        new_rate=new_rate,
                        current_emi=self.current_emi,
                        remaining_tenure=rem_tenure,
                        reset_date=event_date,
                        borrower_dob=self.borrower.dob,
                        next_due_date=next_due,
                    )
                    self.current_emi = new_emi
                    self.remaining_tenure = new_tenure
                    self._emi_schedule = new_schedule
                    self.loan.emi_schedule = new_schedule

                    self._log(
                        event_date, "RATE_RESET", "SUCCESS",
                        reason,
                        ["BR-21"],
                        {
                            "old_rate": str(old_rate),
                            "new_rate": str(new_rate),
                            "new_emi": str(new_emi),
                            "new_tenure": new_tenure,
                        },
                    )

    def _post_emi_overdue(self, job_date: date):
        """Mark EMIs as OVERDUE if past grace period and unpaid."""
        grace_end_threshold = job_date - timedelta(days=BusinessRules.GRACE_DAYS)
        for entry in self._emi_schedule:
            if entry["status"] == "PENDING":
                due = date.fromisoformat(entry["due_date"])
                if due < grace_end_threshold:
                    entry["status"] = "OVERDUE"
        self.loan.emi_schedule = self._emi_schedule

    def _current_outstanding(self) -> Optional[Decimal]:
        """Get current outstanding principal from the last PENDING/OVERDUE EMI's balance."""
        for entry in self._emi_schedule:
            if entry["status"] in ("PENDING", "OVERDUE"):
                return Decimal(entry["outstanding_principal"]) + Decimal(entry["principal_component"])
        # All paid: check last entry
        if self._emi_schedule:
            return Decimal(self._emi_schedule[-1]["outstanding_principal"])
        return None

    def _next_pending_emi_info(self, event_date: date) -> tuple[Optional[date], int]:
        """Return (next_due_date, remaining_pending_count) for the next pending EMI."""
        pending = [e for e in self._emi_schedule if e["status"] in ("PENDING", "OVERDUE")]
        if not pending:
            return None, 0
        next_entry = pending[0]
        return date.fromisoformat(next_entry["due_date"]), len(pending)

    def _count_consecutive_missed(self) -> int:
        """Count leading consecutive overdue EMIs for BR-14.
        Counts OVERDUE entries from the beginning of the schedule,
        stopping when a PAID/PART_PAID entry is encountered.
        PENDING entries that have not yet been due are not counted.
        """
        count = 0
        for entry in self._emi_schedule:
            s = entry["status"]
            if s == "OVERDUE":
                count += 1
            elif s in ("PAID", "PART_PAID"):
                # A payment was made, reset the streak
                count = 0
            else:
                # PENDING — not yet due, stop counting
                break
        return count
