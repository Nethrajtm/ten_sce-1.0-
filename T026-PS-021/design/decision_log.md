# T026-PS-021 — Decision Log

**Team:** T026 · Nethraj T M / Niranjan / Palak Raj  
**Project:** Home Loan with Construction-Linked Disbursement Tranches and Pre-EMI  
**Language:** Python 3.10+

This log records every ambiguity encountered in the problem statement and the
decision made to resolve it.  Each entry follows the format:
`DL-NNN · <topic> · Decision · Rationale`.

---

## DL-001 · Sanction Expiry Scope (BR-09)

**Ambiguity:** The spec says "sanction valid 6 months" but does not state
whether validity applies only to *availing* the first disbursement or to *every*
subsequent tranche release.

**Decision:** Sanction expiry is the *first* check in the BR-26 precedence chain
and blocks ALL tranche releases, not just the first.

**Rationale:** The BR-26 precedence list (sanction validity → own contribution
→ stage certification → sanction cap → delinquency freeze) lists sanction
validity as step 1 without qualifying it to the first tranche only.  In real
housing-finance practice, the facility letter covers the full construction
period, but the spec text clearly places it first for every release check.

**Impact on tests:** Integration tests that span timelines longer than 6 months
must use loans with an `expiry_date` beyond the final tranche date.

---

## DL-002 · 90-Day Certification Freshness — Boundary (BR-13)

**Ambiguity:** The spec says "if a certification is older than 90 days a fresh
certification is required."  It is unclear whether *exactly* 90 days old is
fresh or stale.

**Decision:** Exactly 90 days old is considered **fresh** (inclusive boundary).
The check is `(release_date − cert_date).days <= 90`.

**Rationale:** "Older than 90 days" in plain English means > 90 days.
A document that is exactly 90 days old has not yet exceeded the limit.

---

## DL-003 · Pre-EMI Daily Accrual — Leap Year (BR-17)

**Ambiguity:** The spec says "computed daily actual/365 per tranche."  It does
not specify whether to use 366 in leap years.

**Decision:** The denominator is always **365**, even in leap years.

**Rationale:** "Actual/365" is a standard day-count convention that uses a
fixed 365 denominator (unlike ACT/ACT which uses the actual days in the year).
This matches the spec's literal wording.

---

## DL-004 · Month-36 Lapse Trigger — Boundary (BR-25)

**Ambiguity:** "Undisbursed sanction lapses at month 36."  Whether the lapse
fires *at* month 36 or *after* month 36 is unclear.

**Decision:** The lapse fires when `job_date >= add_months(sanction_date, 36)`.
The boundary is **inclusive** — the lapse triggers on the exact month-36 date.

**Rationale:** "At month 36" means the moratorium ends; the 37th month begins
full-EMI billing.  If the job runs on the first day of month 37 it must already
have triggered the lapse.

---

## DL-005 · Benchmark Change Effective Date (BR-20)

**Ambiguity:** The spec says "rate resets on the 1st of the month after a
benchmark change."  When the change itself is on the 1st of a month, it is
unclear if that same 1st counts.

**Decision:** The rate reset is always effective from the **1st of the NEXT
month** regardless of the change date, even if the change arrives on the 1st.

**Rationale:** "Month *after* a benchmark change" unambiguously means the
following calendar month.

---

## DL-006 · Own-Contribution Validation (BR-11)

**Ambiguity:** The spec requires that "own contribution must be paid in full
before the first tranche."  It does not specify how to verify "full" — whether
to check the amount against `agreement_value − sanctioned_amount` or simply
require that the OWN_CONTRIBUTION event has been recorded.

**Decision:** The system checks that at least one `OWN_CONTRIBUTION` event has
been recorded (binary paid/not-paid), without validating the amount against the
required contribution.

**Rationale:** The spec does not define the required own-contribution amount
in machine-checkable terms (it depends on LTV, which is already computed at
sanction time).  Requiring the event to be present ensures the borrower has
acknowledged the obligation.  The amount paid is recorded in the event ledger
for human review.

---

## DL-007 · Demand Percentage Basis (BR-12)

**Ambiguity:** "Demand of 20% when certified stage is 20%."  It is unclear
whether demand percentages are expressed as a fraction of the *agreement value*
or of the *sanctioned loan amount*.

**Decision:** Demand percentages in `DEMAND` commands are expressed as a
percentage of the **sanctioned loan amount**.  Stage percentages in
`STAGE_CERTIFIED` are expressed as a percentage of the *agreement value*
(stage plan).  The cumulative certification check converts both to a common
percentage of the agreement value via the LTV ratio.

**Rationale:** The sample command file uses demand_pct values that, when
applied to the sanctioned amount, yield sensible tranche amounts.  The stage
plan percentages clearly refer to construction progress (0–100% of the building).

---

## DL-008 · Rate Reset — Tenure vs EMI Priority (BR-21)

**Ambiguity:** "EMI kept constant and tenure adjusted unless tenure would exceed
the age cap, then EMI changes."  Which age cap applies — 70 years from primary
applicant's DOB?

**Decision:** The age cap is **70 years from the primary applicant's date of
birth**.  The maximum permitted remaining tenure at any point is
`months_to_age_70(primary_applicant) − elapsed_months`.  If the new calculated
tenure exceeds this cap, the EMI is recomputed for the capped tenure instead.

**Rationale:** Only the primary applicant's age is mentioned in eligibility
rules (BR-03).  Co-applicant age is not used in tenure calculations.

---

## DL-009 · PMT Formula — Integer Ceiling (BR-21)

**Ambiguity:** After a rate reset the new tenure n is computed as
`n = −log(1 − r·P/EMI) / log(1+r)`.  The result is non-integer; the correct
rounding direction is not specified.

**Decision:** **Ceiling** (`math.ceil`) is applied to n.

**Rationale:** Ceiling ensures the final EMI pays off the remaining balance
without leaving a residual.  Floor could leave a small outstanding balance
after the last EMI.

---

## DL-010 · Part Prepayment During Pre-EMI (BR-19)

**Ambiguity:** "Prepayment during pre-EMI reduces disbursed principal."  It is
unclear whether it reduces per-tranche balances proportionally or reduces a
single aggregate balance.

**Decision:** Part prepayment during the moratorium reduces **total_disbursed**
directly as a single lump adjustment.  Future pre-EMI bills use the reduced
total_disbursed figure.  Individual tranche records are not retroactively
adjusted.

**Rationale:** Per-tranche proportional allocation is operationally complex
and the spec gives no formula for it.  The billing effect (lower interest on
reduced principal) is identical whether allocation is per-tranche or aggregate.

---

## DL-011 · Full Prepayment — EMI Status (BR-19)

**Ambiguity:** When a full prepayment is received, the spec does not state
whether all remaining PENDING EMIs are to be marked PAID or simply cancelled.

**Decision:** All PENDING EMIs are marked **PAID** with the prepayment date as
the payment date, and the loan status is set to `CLOSED`.

**Rationale:** Marking them PAID preserves the schedule history for certificate
generation (principal + interest totals still add up correctly).  CANCELLED
would require special-casing in the interest certificate generator.

---

## DL-012 · Processing Fee — GST Rate (BR-08)

**Ambiguity:** The spec says "0.5% of sanction min ₹10,000 max ₹25,000 + GST"
but does not state the GST rate.

**Decision:** GST is applied at **18%** (standard financial services rate in
India as of 2024).

**Rationale:** 18% GST is the prevailing statutory rate on financial services
processing fees under the GST Act.

---

## DL-013 · Penal Interest Compounding (BR-23)

**Ambiguity:** "2% per month penal on the overdue amount."  It is unclear
whether penal interest itself attracts further penal interest (compound) or is
simple.

**Decision:** Penal interest is **simple** — 2% per month on the original
overdue EMI amount only, not compounding on accrued penalties.

**Rationale:** Simple penal interest is the standard practice in Indian retail
mortgage products under RBI guidelines.  The spec says "penal on the overdue
amount," which refers to the principal EMI amount outstanding.

---

## DL-014 · Tranche Release — "Within 7 Days" (BR-14)

**Ambiguity:** "Release within 7 days of the later of demand and certification."
Whether 7 calendar days or 7 working days is not specified.

**Decision:** **7 calendar days** are used.

**Rationale:** The spec does not reference a holiday calendar or working-day
convention anywhere (sanction expiry on a holiday is listed as an edge case
to *handle explicitly*, not to exclude).

---

## DL-015 · Sanction Expiry on Holiday — Edge Case

**Ambiguity:** The spec lists "sanction expiring on a holiday" as an edge case.
No holiday calendar is provided.

**Decision:** The system uses the **statutory date** as-is.  No holiday roll
forward or backward is applied.  The decision is recorded in the event log with
the note that the expiry fell on a weekend/public holiday if applicable.

**Rationale:** Without a holiday calendar the system cannot determine holidays
reliably.  The spec requires the edge case to be *handled explicitly*, not
necessarily extended.  The event log records the exact expiry date and the
outcome (expired / not expired).

---

## DL-016 · Interest Certificate — Pre-EMI Classification

**Ambiguity:** "Pre-EMI interest is reported separately and is not treated as
principal repayment."  It is unclear under which Section 24 sub-head pre-EMI
interest should appear.

**Decision:** Pre-EMI interest is reported under **"Section B – Pre-Construction
Interest"** separately from regular EMI interest in the FY interest certificate.
It is never shown as principal repayment.

**Rationale:** Under Indian income tax rules (Section 24(b)), pre-construction
interest is deductible in 5 equal installments starting from the year of
possession.  Keeping it separate in the certificate allows the borrower to claim
the deduction correctly.

---

## DL-017 · Conversion Trigger — Final Disbursement vs Month 36

**Ambiguity:** "Full EMI starts from the month after the final tranche or the
37th month" — it is unclear what happens if the final tranche is released
*on* the last day of month 36.

**Decision:** If the final tranche is released on or before the end of month 36,
full EMI starts from month 37 (same month that the lapse trigger fires).  The
moratorium ends and the conversion happens at the same monthly job run.

**Rationale:** The spec says conversion happens from the month *after* the
final tranche; month 36 is the last moratorium month, so the month after is
month 37, which coincides with the lapse trigger.  No double-counting occurs
because the lapse fires only when `undisbursed > 0`, while conversion fires
when `total_disbursed > 0 and not yet converted`.

---

*End of decision log.  All decisions above are reflected in the business rules
module (`src/rules/business_rules.py`) and in the engine
(`src/engine/loan_engine.py`).*
