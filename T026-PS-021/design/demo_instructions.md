# T026-PS-021 — 5-Minute Demo Script

**Team:** T026 · Nethraj T M / Niranjan / Palak Raj  
**Section:** CSDS A  
**Problem:** PS-021 · Home Loan with Construction-Linked Disbursement Tranches and Pre-EMI

---

## Prerequisites

```powershell
# Python 3.10+ required (tested on 3.14.7)
py --version

# Clone and enter the repo
git clone https://github.com/<your-org>/T026-PS-021.git
Set-Location T026-PS-021
```

No `pip install` required — standard library only.

---

## Minute 1 — Project Structure & Tests (0:00 – 1:00)

```powershell
# Show project layout
Get-ChildItem -Recurse -Name | Where-Object { $_ -notmatch "__pycache__|\.pyc|output_files" }
```

Point out:
- `src/models/` — data classes (Borrower, Property, LoanAccount …)
- `src/calculations/` — pure-function modules (eligibility, fees, pre_emi, emi_schedule …)
- `src/rules/business_rules.py` — all 26 BR-xx rules in one place
- `src/engine/loan_engine.py` — event dispatcher
- `src/output/` — formatted output generators
- `tests/` — 104 automated tests (46 Phase 1 + 58 Phase 2)

```powershell
# Run the full test suite
py -m unittest tests/test_phase1.py tests/test_phase2.py -v 2>&1 | Select-String "OK|FAIL|ERROR|Ran"
```

**Expected:** `Ran 104 tests in ~0.04s — OK`

---

## Minute 2 — Sanction Engine (Phase 1) (1:00 – 2:00)

```powershell
py main.py `
  --borrowers  data/sample/borrowers.json `
  --properties data/sample/properties.json `
  --commands   data/sample/commands.json `
  --output     output_files/
```

Open `output_files/LN2024001_sanction_letter.txt`:

```
SANCTION LETTER
───────────────
Loan ID       : LN2024001
Borrower      : Priya Sharma   (F, SPOUSE co-applicant)
Agreement Val : ₹ 55,00,000
LTV %         : 80.00%    → BR-01 (30–75L bracket)
Eligible Loan : ₹ 44,00,000
Rate          : 8.85%     → BR-05 (credit 750 → spread 0.9%) − 0.05% women
Tenure        : 240 months
Processing Fee: ₹ 22,000 + GST  → BR-08
```

**Viva points to mention:** LTV bands (BR-01), eligibility cap 60% (BR-02),
women borrower discount (BR-05), fee cap ₹25,000 (BR-08).

---

## Minute 3 — Disbursement, Pre-EMI and EMI (Phase 2) (2:00 – 3:00)

```powershell
py main.py `
  --borrowers  data/sample/borrowers.json `
  --properties data/sample/properties.json `
  --commands   data/sample/commands_phase2.json `
  --output     output_files/ `
  --fy-year    2024
```

While it runs, narrate the event lifecycle:
1. `OWN_CONTRIBUTION` — BR-11 gate cleared
2. `STAGE_CERTIFIED` — valuer certifies Foundation (20%)
3. `DEMAND` — builder demands tranche; BR-26 precedence check passes → released
4. `MONTHLY_JOB` — pre-EMI bill generated on the 5th (BR-17)
5. Later `MONTHLY_JOB` calls trigger conversion after final disbursement

---

## Minute 4 — Disbursement Ledger (3:00 – 4:00)

```powershell
Get-Content output_files/LN2024001_disbursement_ledger.txt
```

Walk through:
```
DISBURSEMENT LEDGER — LN2024001
────────────────────────────────────────────────────────────────────────
Date        Stage           Demanded     Released     Reason / BR
2024-02-10  Foundation      8,80,000     8,80,000     Released · BR-12 BR-13 BR-14 BR-26
2024-04-15  Slab            6,60,000     6,60,000     Released · BR-12 BR-26
...
TOTAL DISBURSED: ₹ 35,20,000
UNDISBURSED    : ₹  8,80,000  (lapsed at month 36 — BR-25)
```

Highlight the REJECTED row (second demand without new cert → BR-12 fails).

---

## Minute 5 — Amortisation Schedule & Interest Certificate (4:00 – 5:00)

```powershell
Get-Content output_files/LN2024001_amortisation_schedule.txt
```

Show:
- **Pre-EMI section** — interest-only, one row per billing cycle, per-tranche accrual
- **Post-conversion EMI table** — EMI#, Date, Principal, Interest, Balance
- Rate-reset row (benchmark change, BR-20 / BR-21)
- Prepayment row (BR-19)

```powershell
Get-Content output_files/LN2024001_interest_cert_FY2024.txt
```

```
INTEREST CERTIFICATE — FY 2024-25 — LN2024001
────────────────────────────────────────────────
Section A — Principal Repaid (EMI)     :  ₹  1,23,456
Section B — Pre-Construction Interest  :  ₹  24,680    (not principal repayment)
Section C — EMI Interest               :  ₹  3,10,200
Total Interest (B + C)                 :  ₹  3,34,880
```

Close with: "All calculations use `Decimal` with `ROUND_HALF_UP`, no floats.
No hardcoded outputs — every number is derived from the business rules."

---

## CLI Reference (for viva)

```powershell
# Full usage
py main.py --help

# Phase 1 only (sanction)
py main.py --borrowers <file> --properties <file> --commands <file> --output <dir>

# Phase 2 (all events + reports)
py main.py --borrowers <file> --properties <file> --commands <file> --output <dir> --fy-year <YYYY>

# Run all 104 tests
py -m unittest tests/test_phase1.py tests/test_phase2.py -v
```

---

## Common Viva Questions

| Question | Key answer |
|---|---|
| How is pre-EMI accrued per tranche? | `interest = principal × (rate/100/365) × actual_days` — each tranche tracked from release date |
| How does rate reset work? | New n = `ceil(−log(1−r·P/EMI)/log(1+r))`; if n > age cap → recompute EMI for capped n |
| Why Decimal? | Float IEEE-754 rounding would give wrong rupee amounts; `Decimal` is exact |
| What is the BR-26 precedence order? | Sanction validity → own contribution → stage cert freshness → sanction cap → delinquency freeze |
| How are three missed EMIs detected? | Iterate forward in schedule; count consecutive OVERDUE from first unpaid; reset counter at any PAID |
