# T026-PS-021 · Home Loan with Construction-Linked Disbursement Tranches and Pre-EMI

**Team T026 · Section CSDS-A**

| Member | Roll No | Email |
|--------|---------|-------|
| Nethraj T M | 1AT24CD052 | nethrajt@gmail.com |
| Niranjan | 1AT24CD053 | ushaniranjan03@gmail.com |
| Palak Raj | 1AT24CD054 | palaktina1@gmail.com |

---

## Overview

A complete mortgage-servicing engine for under-construction property loans.  
Backend only, command-file driven, no UI.

**Capabilities:**
- Borrower & property registration
- Loan sanction with eligibility, LTV, rate and fee calculation
- Construction-linked tranche disbursement with precedence enforcement
- Pre-EMI interest billing (daily actual/365 per tranche)
- Full EMI schedule, rate resets and prepayments
- Disbursement ledger, amortisation schedule and FY interest certificates
- Deterministic event log with rule IDs for every decision

---

## Technology Stack

| Item | Choice |
|------|--------|
| Language | Python 3.10+ |
| Arithmetic | `decimal.Decimal` (ROUND_HALF_UP, prec=28) |
| Date logic | `datetime.date`, `calendar` |
| I/O | `json`, `csv`, `pathlib` |
| CLI | `argparse` |
| Tests | `unittest` (built-in) |
| External packages | **None** |

---

## Project Structure

```
T026-PS-021/
│
├── main.py                         ← CLI entry point (Phase 1 + Phase 2)
├── README.md
│
├── data/
│   └── sample/
│       ├── borrowers.json          ← 3 sample borrowers
│       ├── properties.json         ← 3 properties (₹30L / ₹55L / ₹90L)
│       ├── commands.json           ← Phase 1: SANCTION commands only
│       └── commands_phase2.json    ← Phase 2: full lifecycle events
│
├── design/
│   └── design_document.md         ← Design document (convert to PDF for submission)
│
├── src/
│   ├── models/
│   │   ├── borrower.py             ← Borrower, CoApplicant
│   │   ├── property.py             ← Property, StageItem
│   │   └── loan.py                 ← SanctionResult, LoanAccount,
│   │                                  DisburseRecord, PreEmiBill,
│   │                                  EmiRecord, EventLog
│   ├── rules/
│   │   └── business_rules.py       ← BusinessRules class (BR-01 → BR-26)
│   ├── calculations/
│   │   ├── eligibility.py          ← LTV, tenure, rate, eligibility
│   │   ├── fees.py                 ← Processing fee + GST
│   │   ├── sanction.py             ← process_sanction() orchestrator
│   │   ├── disbursement.py         ← Tranche release checks (BR-26)
│   │   ├── pre_emi.py              ← Daily accrual, monthly bills (BR-17)
│   │   └── emi_schedule.py         ← Full EMI, rate reset, prepayment
│   ├── engine/
│   │   └── loan_engine.py          ← Stateful event processor (LoanEngine)
│   ├── parsers/
│   │   └── input_parser.py         ← JSON file parsers
│   └── output/
│       ├── sanction_letter.py      ← Formatted sanction letter
│       ├── report_writer.py        ← File writers
│       └── ledger_writer.py        ← Ledger, schedule, FY certificate, event log
│
├── tests/
│   ├── test_phase1.py              ← 46 Phase 1 unit tests
│   └── test_phase2.py              ← 58 Phase 2 unit + integration tests
│
└── output_files/                   ← All generated outputs (git-ignored in real use)
```

---

## Setup

No installation required. Uses Python standard library only.

```powershell
# Verify Python
py --version          # must be 3.10 or higher

# Clone / navigate to project
cd "path\to\T026-PS-021"
```

---

## Running the Engine

### Phase 1 — Sanction only

```powershell
py main.py `
  --borrowers  data/sample/borrowers.json `
  --properties data/sample/properties.json `
  --commands   data/sample/commands.json `
  --output     output_files/
```

### Phase 2 — Full lifecycle (sanctions + events)

```powershell
py main.py `
  --borrowers  data/sample/borrowers.json `
  --properties data/sample/properties.json `
  --commands   data/sample/commands_phase2.json `
  --output     output_files/ `
  --fy-year    2024
```

### Running Tests

```powershell
# All tests (Phase 1 + Phase 2)
py -m unittest tests/test_phase1.py tests/test_phase2.py -v

# Phase 1 only
py -m unittest tests/test_phase1.py -v

# Phase 2 only
py -m unittest tests/test_phase2.py -v
```

Expected: **104 tests, 0 failures**

---

## Input File Formats

### `borrowers.json`

```json
{
  "borrowers": [
    {
      "borrower_id": "B001",
      "name": "Meera Iyer",
      "dob": "1990-06-20",
      "gender": "F",
      "net_income_monthly": 150000,
      "credit_score": 780,
      "coapplicant": {
        "name": "Arjun Iyer",
        "income_monthly": 120000,
        "relationship": "SPOUSE"
      }
    }
  ]
}
```

**Fields:** `gender` = `"M"` or `"F"` · `relationship` = `"SPOUSE"` or `"OTHER"`

---

### `properties.json`

```json
{
  "properties": [
    {
      "property_id": "P001",
      "agreement_value": 3000000,
      "builder_name": "Prestige Constructions",
      "stages": [
        {"stage_name": "Foundation",    "percentage": 20},
        {"stage_name": "Superstructure","percentage": 30},
        {"stage_name": "Brickwork",     "percentage": 25},
        {"stage_name": "Finishing",     "percentage": 25}
      ]
    }
  ]
}
```

**Note:** `stages[*].percentage` must sum to 100.

---

### `commands.json` (Phase 2 event file)

```json
{
  "benchmark_rate": 8.5,
  "commands": [
    {"command": "SANCTION",          "date": "2024-01-15", "borrower_id": "B001", "property_id": "P001"},
    {"command": "OWN_CONTRIBUTION",  "date": "2024-01-20", "loan_id": "LN2024001", "amount": 300000},
    {"command": "STAGE_CERTIFIED",   "date": "2024-02-01", "loan_id": "LN2024001",
                                     "stage_name": "Foundation", "certification_date": "2024-02-01"},
    {"command": "DEMAND",            "date": "2024-02-10", "loan_id": "LN2024001",
                                     "demand_amount": 540000, "stage_name": "Foundation", "demand_pct": 20},
    {"command": "MONTHLY_JOB",       "date": "2024-03-05", "loan_id": "LN2024001"},
    {"command": "BENCHMARK_CHANGE",  "date": "2024-06-01", "new_benchmark": 9.0},
    {"command": "RECORD_EMI",        "date": "2024-09-10", "loan_id": "LN2024001", "emi_no": 1, "amount": 25000},
    {"command": "PREPAYMENT_PART",   "date": "2024-10-15", "loan_id": "LN2024001", "amount": 100000, "reduce_tenure": true},
    {"command": "PREPAYMENT_FULL",   "date": "2025-01-01", "loan_id": "LN2024001", "amount": 2500000}
  ]
}
```

#### All command types

| Command | Required fields |
|---------|----------------|
| `SANCTION` | `borrower_id`, `property_id` |
| `OWN_CONTRIBUTION` | `loan_id`, `amount` |
| `STAGE_CERTIFIED` | `loan_id`, `stage_name`, `certification_date` |
| `DEMAND` | `loan_id`, `demand_amount`, `stage_name`, `demand_pct` |
| `MONTHLY_JOB` | `loan_id` |
| `BENCHMARK_CHANGE` | `new_benchmark` (applies to all active loans) |
| `RECORD_EMI` | `loan_id`, `emi_no`, `amount` |
| `PREPAYMENT_PART` | `loan_id`, `amount`, `reduce_tenure` (bool, default `true`) |
| `PREPAYMENT_FULL` | `loan_id`, `amount` |

---

## Output Files

All files are written to `--output` directory:

| File | Description |
|------|-------------|
| `{LOAN_ID}_sanction_letter.txt` | Formatted sanction letter with all BR IDs |
| `{LOAN_ID}_summary.json` | Sanction amounts, rate, expiry in JSON |
| `{LOAN_ID}_disbursement_ledger.txt` | All tranche decisions (RELEASED/REJECTED/PARTIAL) with reasons |
| `{LOAN_ID}_amortisation_schedule.txt` | Pre-EMI bills + full EMI table post-conversion |
| `{LOAN_ID}_interest_cert_FY{YEAR}.txt` | FY-wise interest certificate (pre-EMI separate) |
| `{LOAN_ID}_event_log.txt` | Human-readable audit log |
| `{LOAN_ID}_event_log.json` | Machine-readable event log |
| `run_summary.json` | Aggregate run statistics |

---

## Business Rules Reference

### Phase 1 — Sanction

| ID | Rule |
|----|------|
| **BR-01** | LTV: ≤₹30L → 90%, ₹30–75L → 80%, >₹75L → 75% of agreement value |
| **BR-02** | Max tenure: min(30 years, years until borrower turns 70) |
| **BR-03** | EMI/income ratio: ≤55% if income ≤₹1L/month; ≤60% above |
| **BR-04** | Co-applicant income: SPOUSE = 100%, OTHER = 50% |
| **BR-05** | Spread: score ≥775 → +0.50%; 725–774 → +0.90%; <725 → +1.40% |
| **BR-06** | Women primary applicant: −0.05% concession |
| **BR-07** | Sanction = min(LTV limit, eligibility limit) |
| **BR-08** | Processing fee: 0.5% of sanction, min ₹10,000, max ₹25,000 + 18% GST; 50% at sanction, 50% at first disbursal |
| **BR-09** | Sanction validity: 6 months; lapse forfeits first half of fee |
| **BR-10** | Eligibility via PMT formula on combined income |

### Phase 2 — Disbursement & Servicing

| ID | Rule |
|----|------|
| **BR-11** | Own contribution fully paid before first tranche |
| **BR-12** | Cumulative certified % ≥ cumulative demanded % |
| **BR-13** | Tranche capped at remaining sanctioned amount; excess lapses |
| **BR-14** | 3 consecutive missed EMIs → tranche release frozen |
| **BR-15** | Release within 7 days of later of demand/certification date |
| **BR-16** | Certification valid for ≤90 days; older requires fresh cert |
| **BR-17** | Pre-EMI: principal × (rate/100/365) × actual days per tranche |
| **BR-18** | Moratorium: pre-EMI until final disbursement or 36 months |
| **BR-19** | Full EMI from 1st of month after final tranche or month 37 |
| **BR-20** | EMI computed on total **disbursed** (not sanctioned) principal |
| **BR-21** | Rate reset: keep EMI constant, adjust tenure; if tenure > age-70 cap → increase EMI instead |
| **BR-22** | Part prepayment: min ₹50,000; no charge; default reduces tenure |
| **BR-23** | Full prepayment closes loan; no foreclosure charge |
| **BR-24** | Penal: 2%/month on overdue EMI after 15-day grace period |
| **BR-25** | Undisbursed sanction lapses at month 36; conversion triggered on disbursed amount |
| **BR-26** | Tranche precedence: BR-09 → BR-11 → BR-12/BR-16 → BR-13 → BR-14 |

---

## Edge Cases Tested

All eight specified edge cases have automated tests in `tests/test_phase2.py`:

| Edge Case | Test Method | Class |
|-----------|-------------|-------|
| Agreement value exactly ₹30L | `test_ltv_30_lakh_boundary` | `TestLTV` |
| Agreement value exactly ₹75L | `test_ltv_75_lakh_boundary` | `TestLTV` |
| Demand 20% when certified = 20% exactly | `test_accept_cert_exactly_90_days` | `TestDisburseChecks` |
| Second demand with no new certification → REJECT | `test_reject_second_demand_without_new_cert` | `TestDisburseChecks` |
| Benchmark change on 1st of month | `test_benchmark_change_effective_next_month` | `TestEMISchedule` |
| Final tranche on last day of month 36 | `test_final_tranche_last_day_month36` | `TestEMISchedule` / `TestEdgeCases` |
| Prepayment on tranche-release date | `test_prepayment_on_tranche_release_date` | `TestEdgeCases` |
| Rate reset past age-70 cap | `test_rate_reset_exceeds_age_cap` | `TestEMISchedule` |
| Certification exactly 90 days old | `test_accept_cert_exactly_90_days` | `TestDisburseChecks` |
| Certification 91 days old → REJECT | `test_reject_cert_over_90_days` | `TestDisburseChecks` |

---

## Arithmetic Notes

- All monetary values use `decimal.Decimal` with `ROUND_HALF_UP` to 2 decimal places
- `getcontext().prec = 28` set globally
- Pre-EMI: interest accrued without intermediate rounding; only final per-bill total is rounded
- PMT formula: `EMI = P × r × (1+r)^n / ((1+r)^n − 1)` where `r = annual_rate / 1200`
- Month arithmetic uses `calendar.monthrange` to clamp end-of-month dates (e.g., Aug 31 + 6M = Feb 28/29)
- Actual/365 day count for pre-EMI (no day-count adjustment for leap years in denominator)

---

## Documented Ambiguities

See `design/decision_log.md` for all design decisions and ambiguities.

---

## Viva Preparation

Key concepts to explain:

1. **Pre-EMI accrual per tranche** — Each tranche accrues separately from its release date. Monthly bill sums all tranches: `Σ (amount_i × rate/100/365 × days_i)` where `days_i = period_to − max(release_date_i, period_from)`.

2. **Rate-reset with constant EMI** — Use the formula `n = ⌈−log(1 − r·P/EMI) / log(1+r)⌉` to find the new tenure. If that exceeds the age-70 cap, recompute EMI with capped tenure instead.

3. **Tranche precedence (BR-26)** — Checks are short-circuit: the first failing rule's ID is reported and processing stops. This ensures the reason code always maps to exactly one rule.
