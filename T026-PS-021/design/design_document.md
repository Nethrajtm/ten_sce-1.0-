# T026-PS-021 — Design Document

**Team ID:** T026  
**Members:** Nethraj T M (1AT24CD052) · Niranjan (1AT24CD053) · Palak Raj (1AT24CD054)  
**Section:** CSDS A  
**Problem:** PS-021 · Home Loan with Construction-Linked Disbursement Tranches and Pre-EMI  
**Language:** Python 3.10+  
**Submission repo:** `T026-PS-021`

---

## Table of Contents

1. [Problem Summary](#1-problem-summary)
2. [System Architecture](#2-system-architecture)
3. [Data Flow](#3-data-flow)
4. [Module Descriptions](#4-module-descriptions)
5. [Business Rules (BR-01 to BR-26)](#5-business-rules)
6. [Edge Case Handling](#6-edge-case-handling)
7. [Key Design Decisions](#7-key-design-decisions)
8. [Sequence Diagrams](#8-sequence-diagrams)
9. [Test Coverage Summary](#9-test-coverage-summary)
10. [Assumptions & Limitations](#10-assumptions--limitations)

---

## 1. Problem Summary

A housing finance company disburses home loans against under-construction
properties in stages ("tranches") as the builder completes construction phases.
The borrower pays only interest on the disbursed amount (Pre-EMI) during
construction, then switches to full EMI after construction is complete.

The system must:

- Register borrowers (income, co-applicant, age, credit score) and properties
  (agreement value, builder, staged construction plan).
- Compute the sanctioned loan amount using LTV rules, income eligibility,
  and age constraints.
- Process builder DEMAND and valuer STAGE_CERTIFIED events; release tranches
  only when all precedence checks pass.
- Bill monthly Pre-EMI interest during the moratorium using daily actual/365
  accrual per tranche.
- Convert to full-EMI amortisation after the final disbursement or month 36,
  whichever is earlier.
- Handle benchmark rate changes (reset tenure / EMI per age cap), part
  prepayments and full prepayments.
- Generate a disbursement ledger, amortisation schedule, and FY interest
  certificates.
- Run entirely from command files — no UI, no external services.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py  (CLI)                          │
│           argparse → orchestrate phases → write outputs         │
└──────────┬──────────────┬──────────────────────────────────────┘
           │              │
    ┌──────▼──────┐ ┌─────▼───────────────────────────────────┐
    │   Parsers   │ │              Engine                      │
    │ input_parser│ │  loan_engine.py — LoanEngine             │
    │  .py        │ │  Dispatches events to calculation modules│
    └──────┬──────┘ └────┬──────────────────────────────────────┘
           │             │
    ┌──────▼──────────────▼────────────────────┐
    │               Calculations               │
    │  eligibility.py   — LTV, EMI eligibility │
    │  fees.py          — processing fee + GST │
    │  sanction.py      — process_sanction()   │
    │  disbursement.py  — tranche release check│
    │  pre_emi.py       — daily accrual        │
    │  emi_schedule.py  — PMT, reset, prepay   │
    └──────────────────┬───────────────────────┘
                       │
    ┌──────────────────▼───────────────────────┐
    │                 Models                   │
    │  borrower.py  — Borrower, CoApplicant    │
    │  property.py  — Property, StageItem      │
    │  loan.py      — LoanAccount, DisburseRec │
    │               — PreEmiBill, EmiRecord    │
    │               — EventLog, SanctionResult │
    └──────────────────┬───────────────────────┘
                       │
    ┌──────────────────▼───────────────────────┐
    │                  Rules                   │
    │  business_rules.py — BR-01 … BR-26       │
    │  (static validation methods)             │
    └──────────────────┬───────────────────────┘
                       │
    ┌──────────────────▼───────────────────────┐
    │                 Output                   │
    │  sanction_letter.py — formatted letter   │
    │  report_writer.py   — JSON / text        │
    │  ledger_writer.py   — ledger / amort /   │
    │                        cert / event log  │
    └──────────────────────────────────────────┘
```

**Layer responsibilities:**

| Layer | Role |
|---|---|
| CLI (`main.py`) | Parse arguments, load files, call sanction/engine, write outputs |
| Parsers | Deserialise JSON → domain objects; type-coerce all fields |
| Models | Immutable/mutable dataclasses; hold state per loan |
| Rules | Stateless validators returning `(bool, reason, [BR-IDs])` |
| Calculations | Pure functions; all `Decimal` arithmetic |
| Engine | Stateful event dispatcher; maintains ledger |
| Output | Format and write text/JSON reports |

---

## 3. Data Flow

```
borrowers.json ──┐
properties.json ─┤─► parse_borrower_file()    ─► List[Borrower]   ─┐
                 │   parse_property_file()     ─► List[Property]   ─┤
commands.json  ──┘   parse_command_file()      ─► List[dict]       ─┤
                     parse_events_from_commands() ─► Phase-2 events ─┘
                                                                    │
                ┌───────────────────────────────────────────────────▼───┐
                │  For each SANCTION command:                           │
                │    process_sanction(borrower, property, cmd)          │
                │    → SanctionResult → LoanAccount                    │
                │    → write sanction letter + JSON summary             │
                └───────────────────────────────────────────────────────┘
                                                                    │
                ┌───────────────────────────────────────────────────▼───┐
                │  LoanEngine initialised with all LoanAccounts         │
                │                                                        │
                │  For each Phase-2 event (chronological):              │
                │    DEMAND / STAGE_CERTIFIED → tranche logic           │
                │    OWN_CONTRIBUTION          → gate flag              │
                │    BENCHMARK_CHANGE          → store new rate         │
                │    MONTHLY_JOB               → pre-EMI bill / convert │
                │    RECORD_EMI                → mark payment           │
                │    PREPAYMENT_PART/FULL       → adjust principal      │
                │    Each event → EventLog entry (outcome + BR-IDs)     │
                └───────────────────────────────────────────────────────┘
                                                                    │
                ┌───────────────────────────────────────────────────▼───┐
                │  write_phase2_outputs(loan, output_dir, fy_year)      │
                │  ─ disbursement ledger (.txt)                         │
                │  ─ amortisation schedule (.txt)                       │
                │  ─ FY interest certificate (.txt)                     │
                │  ─ event log (.txt + .json)                           │
                └───────────────────────────────────────────────────────┘
```

**Input file formats:**

| File | Top-level keys |
|---|---|
| `borrowers.json` | `borrowers[]` — id, name, dob, gender, income, credit_score, coapplicant? |
| `properties.json` | `properties[]` — id, agreement_value, builder_name, stages[] |
| `commands.json` | `benchmark_rate`, `commands[]` — command, date, + type-specific fields |

---

## 4. Module Descriptions

### 4.1 `src/models/`

| File | Classes | Purpose |
|---|---|---|
| `borrower.py` | `CoApplicant`, `Borrower` | Immutable profile; age calculation helper |
| `property.py` | `StageItem`, `Property` | Agreement value, construction stage plan |
| `loan.py` | `SanctionResult`, `LoanAccount`, `DisburseRecord`, `PreEmiBill`, `EmiRecord`, `EventLog` | Full loan lifecycle state |

`LoanAccount` carries:
- `disbursements: List[DisburseRecord]` — each released tranche
- `pre_emi_bills: List[PreEmiBill]` — monthly interest bills
- `emi_schedule: List[EmiRecord]` — post-conversion amortisation
- `event_log: List[EventLog]` — immutable audit trail

### 4.2 `src/rules/business_rules.py`

Single `BusinessRules` class with **static methods**, one per rule.
Each method returns `(bool, str, List[str])` — (passed, reason, applicable BR IDs).

### 4.3 `src/calculations/`

| Module | Key functions |
|---|---|
| `eligibility.py` | `compute_ltv()`, `compute_max_tenure()`, `compute_rate()`, `compute_max_loan_eligibility()` |
| `fees.py` | `compute_processing_fee()`, `compute_gst()` |
| `sanction.py` | `process_sanction()` — orchestrates all Phase-1 rules |
| `disbursement.py` | `check_tranche_release()` — BR-26 chain; `calculate_release_amount()` |
| `pre_emi.py` | `daily_rate()`, `accrual_for_tranche()`, `generate_pre_emi_bill()` |
| `emi_schedule.py` | `compute_emi()` (PMT formula), `generate_schedule()`, `apply_rate_reset()`, `recalculate_schedule_after_prepayment()` |

### 4.4 `src/engine/loan_engine.py`

`LoanEngine` holds a `{loan_id: LoanAccount}` registry.

Event dispatch table:

| Event | Handler method |
|---|---|
| `OWN_CONTRIBUTION` | `_handle_own_contribution()` |
| `STAGE_CERTIFIED` | `_handle_stage_certified()` |
| `DEMAND` | `_handle_demand()` |
| `BENCHMARK_CHANGE` | `_handle_benchmark_change()` |
| `MONTHLY_JOB` | `_handle_monthly_job()` |
| `RECORD_EMI` | `_handle_record_emi()` |
| `PREPAYMENT_PART` | `_handle_prepayment_part()` |
| `PREPAYMENT_FULL` | `_handle_prepayment_full()` |

### 4.5 `src/output/`

| Module | Functions |
|---|---|
| `sanction_letter.py` | `format_sanction_letter()` |
| `report_writer.py` | `write_sanction_letter()`, `write_json_output()` |
| `ledger_writer.py` | `generate_disbursement_ledger()`, `generate_amortisation_schedule()`, `generate_interest_certificate()`, `generate_event_log_text()`, `write_phase2_outputs()` |

---

## 5. Business Rules

### BR-01 — LTV Calculation

**Input:** Agreement value  
**Formula:**

| Agreement Value | LTV % |
|---|---|
| ≤ ₹30 lakh | 90% |
| > ₹30 lakh and ≤ ₹75 lakh | 80% |
| > ₹75 lakh | 75% |

**Output:** Maximum loan amount = Agreement value × LTV %  
**Note:** Stamp duty and registration excluded from agreement value for LTV base.

---

### BR-02 — Income Eligibility (EMI/NMI Cap)

**Input:** Net monthly income (primary + co-applicant), proposed EMI  
**Formula:**

- If combined NMI ≤ ₹1,00,000: max EMI = 55% of NMI
- If combined NMI > ₹1,00,000: max EMI = 60% of NMI
- Co-applicant income added 100% if SPOUSE, 50% if OTHER

**Output:** Maximum permissible EMI → maximum eligible loan via PMT-inverse

---

### BR-03 — Tenure Cap (Age 70)

**Input:** Primary applicant DOB, loan start date, requested tenure  
**Formula:**  
`max_tenure_months = (70th birthday − start date).months`  
Final tenure = `min(requested_tenure, max_tenure_months, 360)`

---

### BR-04 — Maximum Loan Amount

**Output:** `min(LTV amount [BR-01], eligibility amount [BR-02])`

---

### BR-05 — Interest Rate Calculation

**Input:** Benchmark rate, credit score, borrower gender  
**Formula:**

| Credit Score | Spread |
|---|---|
| ≥ 775 | +0.50% |
| 725–774 | +0.90% |
| < 725 | +1.40% |

Women primary applicant: −0.05%  
**Final rate = Benchmark + Spread − (women discount)**

---

### BR-06 — Loan Sanction

Loan is sanctioned when:
- Eligible loan amount > 0
- Requested amount ≤ max eligible amount
- Tenure ≤ age cap and ≤ 360 months

---

### BR-07 — Sanction ID Generation

Loan IDs generated sequentially: `LN{YYYY}{NNN}` (e.g., `LN2024001`).

---

### BR-08 — Processing Fee

**Formula:**  
`fee = clamp(0.5% × sanctioned_amount, min=₹10,000, max=₹25,000)`  
`fee_with_gst = fee × 1.18` (18% GST)  
50% charged at sanction, 50% at first disbursement.  
Lapsed sanction forfeits the first 50%.

---

### BR-09 — Sanction Validity

Sanction is valid for **6 months** from the sanction date.  
A tranche cannot be released after the sanction expiry date.

---

### BR-10 — Own Contribution Gate

The first tranche cannot be released unless the borrower has recorded an
OWN_CONTRIBUTION event.  The contribution covers `agreement_value − sanctioned_amount`.

---

### BR-11 — Own Contribution Recording

OWN_CONTRIBUTION events record the date and amount paid.  
The gate (BR-10) is cleared once any OWN_CONTRIBUTION is recorded.

---

### BR-12 — Stage Certification vs Demand Check

A DEMAND is processed only if:  
`cumulative_certified_pct ≥ cumulative_demanded_pct + demand_pct`

where all percentages are of the agreement value.  
A demand that fails this check is **REJECTED** and logged with BR-12.

---

### BR-13 — Certification Freshness (90-Day Rule)

A STAGE_CERTIFIED event must have been issued within **90 calendar days** of
the tranche release date.  
`(release_date − certification_date).days ≤ 90`  
If stale, a fresh certification is required; demand is deferred.

---

### BR-14 — Seven-Day Release Window

The tranche must be released within **7 calendar days** of:  
`max(demand_date, certification_date)`  
The system records the release date and validates it against this deadline.

---

### BR-15 — Tranche Amount Calculation

`release_amount = demand_amount − borrower_own_contribution_share`  
where `own_contribution_share = demand_pct × (agreement_value − sanctioned_amount) / 100`  
(i.e., the proportional own contribution for this stage).

---

### BR-16 — Sanctioned Amount Cap

The cumulative disbursed amount cannot exceed the sanctioned loan amount.  
If a demand would exceed the cap, only the remaining eligible amount is released.  
Excess is noted in the event log.

---

### BR-17 — Pre-EMI Billing

During the moratorium (until final disbursement or 36 months):  
`daily_interest = tranche_principal × (annual_rate/100) / 365`  
`monthly_bill = Σ(tranche_daily_interest × actual_days_in_billing_period)`

Billed on the **5th of each month** for the previous calendar month.  
Each tranche accrues from its release date.

---

### BR-18 — Moratorium / Conversion

Moratorium ends when:
- The final tranche is disbursed, **OR**
- 36 months have elapsed since sanction date

Full EMI starts from the **month after** conversion.  
Undisbursed amount at month 36 lapses (BR-25).

---

### BR-19 — Prepayment

**Part prepayment:**
- Minimum ₹50,000
- No prepayment charge (floating rate, individual)
- Default: reduce tenure, keep EMI constant
- Optional: reduce EMI, keep tenure constant (on request)
- During pre-EMI: reduces `total_disbursed`; future bills adjusted

**Full prepayment:**
- Entire outstanding principal paid
- All PENDING EMIs marked PAID, loan status set to CLOSED

---

### BR-20 — Benchmark Change

When a BENCHMARK_CHANGE event arrives:
- New rate = new_benchmark + borrower's spread − women discount
- Effective from the **1st of the next month**

---

### BR-21 — Rate Reset with Constant EMI

After a rate reset (BR-20), the system:

1. Computes remaining principal `P` (outstanding balance at reset date)
2. Keeps EMI constant
3. Calculates new tenure: `n = ⌈−log(1 − r·P/EMI) / log(1+r)⌉`
   where `r = new_monthly_rate`
4. If new `n > remaining age-cap months` → recompute EMI for capped tenure

---

### BR-22 — EMI Schedule Generation (PMT)

`EMI = P × r × (1+r)^n / ((1+r)^n − 1)`  
where `r = annual_rate / 12 / 100`, `n = tenure_months`, `P = total_disbursed`.

---

### BR-23 — Penal Interest

EMI unpaid after a **15-day grace period** attracts:  
`penal = 2% per month × overdue_EMI_amount` (simple, not compound)

---

### BR-24 — Delinquency Freeze

**3 consecutive missed EMIs** (OVERDUE status, counted forward from first unpaid,
reset at any PAID) → freeze further tranche releases.  
Releases can resume once delinquency is cleared.

---

### BR-25 — Month-36 Lapse

If `job_date ≥ add_months(sanction_date, 36)`:
- Undisbursed balance lapses
- Conversion to full EMI is triggered on disbursed amount

---

### BR-26 — Tranche Release Precedence

Before any tranche is released, the following checks are enforced **in order**.
A failure at any step rejects the release:

1. **Sanction validity** (BR-09) — sanction must not be expired
2. **Own contribution** (BR-10) — contribution must be recorded
3. **Stage certification** (BR-12 + BR-13) — certified % sufficient and cert fresh
4. **Sanction cap** (BR-16) — cumulative disbursed < sanctioned amount
5. **Delinquency freeze** (BR-24) — fewer than 3 consecutive missed EMIs

---

## 6. Edge Case Handling

| # | Edge Case | Handling |
|---|---|---|
| EC-01 | Agreement value exactly ₹30 lakh | LTV = 90% (≤ boundary is inclusive; BR-01 uses `<=`) |
| EC-02 | Agreement value exactly ₹75 lakh | LTV = 80% (> 30L and ≤ 75L bracket) |
| EC-03 | Demand = 20% when cert = 20%; then demand 10% with no new cert | First demand passes (20 ≥ 0 + 20). Second demand fails BR-12 (20 < 20 + 10), REJECTED |
| EC-04 | Benchmark change on the 1st of a month | Effective 1st of the NEXT month (DL-005) |
| EC-05 | Final tranche on last day of month 36 | Moratorium ends; month-37 job triggers conversion and lapse simultaneously |
| EC-06 | Prepayment on tranche release date | Prepayment applied first (atomic event ordering in command file); pre-EMI bills use reduced balance |
| EC-07 | Rate reset pushing tenure past age-70 cap | New tenure capped; EMI recomputed for capped tenure (BR-21) |
| EC-08 | Sanction expiry on a holiday | Statutory date used as-is; no roll forward (DL-015); event log records the expiry date |
| EC-09 | Certification exactly 90 days old | Fresh — check is `<= 90`, boundary inclusive (DL-002) |
| EC-10 | Over-sanction demand | Released up to remaining sanctioned amount; excess noted (BR-16) |
| EC-11 | Unknown borrower_id in command | Event rejected with `UNKNOWN_BORROWER`; processing continues |
| EC-12 | Duplicate OWN_CONTRIBUTION | Second event accepted; amount added; gate remains open |

---

## 7. Key Design Decisions

### 7.1 `Decimal` Arithmetic

All monetary values and rates use `decimal.Decimal` with `ROUND_HALF_UP`.
`getcontext().prec = 28`. Float IEEE-754 arithmetic causes cumulative rounding
errors in amortisation schedules; `Decimal` guarantees exact results.

### 7.2 Event-Log Pattern

Every event produces an immutable `EventLog` entry:
```
EventLog(date, event_type, loan_id, outcome, reason, br_ids, amount)
```
The log drives the disbursement ledger and interest certificate, and provides
a verifiable audit trail for the viva.

### 7.3 BR-26 Precedence Chain

`check_tranche_release()` returns at the **first failure** in the precedence
list (BR-26 order).  This ensures rule IDs in the event log are specific —
the reviewer can see exactly which check blocked the release.

### 7.4 Standard Library Only

No third-party packages are used.  `decimal`, `datetime`, `json`, `pathlib`,
`argparse`, `math`, `unittest` — all standard library.  This makes the project
portable and reproducible without a `requirements.txt`.

### 7.5 Immutable Stage Plan

The property's construction stage plan is fixed at registration.  Demands are
validated against the cumulative certified percentage at the time of the demand,
not the stage plan percentages.

### 7.6 Schedule Regeneration Pattern

After a rate reset or prepayment, the amortisation schedule is **regenerated
from scratch** for the remaining tenure using the new parameters, rather than
patching existing records.  This avoids compounding rounding errors.

### 7.7 Fixed-EMI Tenure Reduction

When a part prepayment reduces tenure (default), the helper
`_generate_schedule_fixed_emi()` keeps the original EMI constant for all
non-final entries, adjusting only the last EMI to clear the balance exactly.
This avoids rounding divergence from re-running the PMT formula for the
shorter tenure.

---

## 8. Sequence Diagrams

### 8.1 Tranche Release (BR-26 Precedence)

```
Command File          LoanEngine          BusinessRules        LoanAccount
    │  DEMAND event       │                    │                    │
    │────────────────────►│                    │                    │
    │                     │ check_tranche_     │                    │
    │                     │ release()          │                    │
    │                     │────────────────────►                    │
    │                     │  BR-09: expired?   │                    │
    │                     │◄────────── FAIL ───│  (log REJECTED)   │
    │                     │  ── or ──          │                    │
    │                     │  BR-10: own_cont?  │                    │
    │                     │◄────────── FAIL ───│                    │
    │                     │  ── or ──          │                    │
    │                     │  BR-12+13: cert?   │                    │
    │                     │◄────────── FAIL ───│                    │
    │                     │  ── or ──          │                    │
    │                     │  BR-16: cap?       │                    │
    │                     │◄────────── FAIL ───│                    │
    │                     │  ── or ──          │                    │
    │                     │  BR-24: delinq?    │                    │
    │                     │◄────────── FAIL ───│                    │
    │                     │  ── or ──  PASS ──►│                    │
    │                     │ calculate_release_ │                    │
    │                     │ amount()           │                    │
    │                     │────────────────────►    DisburseRecord  │
    │                     │◄── release_amount ─│─────────────────►  │
    │                     │ EventLog(RELEASED)  │                    │
    │                     │────────────────────────────────────────►│
```

### 8.2 Pre-EMI Monthly Billing

```
Command File     LoanEngine           pre_emi.py           LoanAccount
    │  MONTHLY_JOB   │                    │                    │
    │───────────────►│                    │                    │
    │                │ moratorium active? │                    │
    │                │────────────────────►                    │
    │                │ generate_pre_emi_  │                    │
    │                │ bill(disbursements,│                    │
    │                │  billing_month,    │                    │
    │                │  rate)             │                    │
    │                │────────────────────►                    │
    │                │  For each tranche: │                    │
    │                │   days in period   │                    │
    │                │   interest += P×r×d/365               │
    │                │◄── PreEmiBill ─────│                    │
    │                │ append to bills    │                    │
    │                │────────────────────────────────────────►│
    │                │ EventLog(PRE_EMI_BILL)                  │
    │                │────────────────────────────────────────►│
```

### 8.3 Rate Reset (BR-21)

```
Command File     LoanEngine      emi_schedule.py      LoanAccount
    │ BENCHMARK_   │                  │                   │
    │ CHANGE       │                  │                   │
    │─────────────►│                  │                   │
    │              │ store new rate,  │                   │
    │              │ effective 1st    │                   │
    │              │ next month       │                   │
    │              │                  │                   │
    │ MONTHLY_JOB  │                  │                   │
    │ (reset month)│                  │                   │
    │─────────────►│                  │                   │
    │              │ apply_rate_      │                   │
    │              │ reset(loan,      │                   │
    │              │  new_rate, date) │                   │
    │              │─────────────────►│                   │
    │              │  P = outstanding │                   │
    │              │  r = new monthly │                   │
    │              │  n = ceil(−log(1−│                   │
    │              │   rP/E)/log(1+r))│                   │
    │              │  if n > age cap: │                   │
    │              │    E = PMT(P,r,n_│                   │
    │              │    cap)          │                   │
    │              │  regenerate      │                   │
    │              │  schedule        │                   │
    │              │◄── new schedule ─│                   │
    │              │ replace emi_     │                   │
    │              │ schedule         │                   │
    │              │─────────────────────────────────────►│
```

---

## 9. Test Coverage Summary

### Phase 1 — 46 tests (`tests/test_phase1.py`)

| Test class | Count | Coverage |
|---|---|---|
| `TestLTVCalculation` | 5 | BR-01 boundary values (30L, 75L, below, above, exact) |
| `TestEligibility` | 6 | Income caps, co-applicant spouse vs other, combined NMI |
| `TestRateCalculation` | 4 | Credit score bands, women discount, combined |
| `TestTenureCap` | 3 | Age-70 cap, max 30 years, minimum of both |
| `TestProcessingFee` | 4 | Min, max, clamp, GST |
| `TestSanctionProcess` | 10 | Full sanction, insufficient income, LTV-limited, tenure-capped, lapsed, fee split |
| `TestBusinessRules` | 8 | Individual BR validators |
| `TestParsers` | 6 | JSON parsing, malformed input, missing fields |

### Phase 2 — 58 tests (`tests/test_phase2.py`)

| Test class | Count | Coverage |
|---|---|---|
| `TestPreEmiAccrual` | 6 | Daily rate, multi-tranche, boundary months, zero days |
| `TestEmiSchedule` | 8 | PMT formula, generate schedule, amortisation identity |
| `TestRateReset` | 5 | Constant EMI, age-cap override, benchmark on 1st |
| `TestPrepayment` | 6 | Part (reduce tenure), part (reduce EMI), full, during pre-EMI |
| `TestTrancheRelease` | 10 | BR-26 all 5 checks, partial release at cap, 90-day cert boundary |
| `TestEdgeCases` | 8 | All 8 specified edge cases (EC-03, EC-04, EC-05, EC-06, EC-07, EC-08, EC-09, EC-10) |
| `TestDelinquency` | 5 | Grace period, penal calc, 3-missed freeze, freeze lifted |
| `TestIntegration` | 10 | Full lifecycle, interest certificate totals, event log audit |

**Total: 104 tests.  All pass.**

---

## 10. Assumptions & Limitations

1. **Holiday calendar:** No holiday calendar is available.  Sanction expiry dates
   are used as-is (see DL-015).

2. **Stamp duty exclusion:** The system excludes stamp duty/registration from the
   LTV base per BR-01.  The agreement value in the input file is assumed to be
   the property value *excluding* stamp duty and registration.

3. **Own contribution amount:** The system only checks that an OWN_CONTRIBUTION
   event was recorded (binary gate), not that the amount equals the required
   contribution.  See DL-006.

4. **Co-applicant age:** Co-applicant age does not affect tenure calculations.
   Only the primary applicant's age-70 constraint applies.

5. **Benchmark change on command date:** The benchmark rate in the command file
   is the *initial* benchmark.  BENCHMARK_CHANGE events update it from the 1st
   of the following month.

6. **Interest certificate deductibility:** The certificate outputs are for
   borrower record-keeping.  Tax deductibility claims are the borrower's
   responsibility.

7. **Hidden test cases:** The system uses no hardcoded values.  All outputs are
   derived algorithmically from the business rules.

8. **Stretch goals:** Balance transfer and top-up loan are **not implemented**
   (optional extra-credit items).

---

*Document prepared by Team T026 for the 10 SECONDS Capstone Project evaluation.*
