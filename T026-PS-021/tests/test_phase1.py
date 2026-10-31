"""
tests/test_phase1.py
Comprehensive unit tests for Phase 1 of T026-PS-021.
Run with: py -m unittest tests/test_phase1.py -v
"""
from __future__ import annotations

import sys
import os
import unittest
from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

getcontext().prec = 28

from src.models.borrower import Borrower, CoApplicant
from src.models.property import Property, StageItem
from src.models.loan import SanctionResult
from src.rules.business_rules import BusinessRules
from src.calculations.eligibility import (
    calculate_combined_income,
    calculate_ltv_limit,
    calculate_max_tenure,
    calculate_interest_rate,
    calculate_eligibility_limit,
)
from src.calculations.fees import calculate_processing_fee
from src.calculations.sanction import process_sanction, _add_months
from src.output.sanction_letter import generate_sanction_letter


# ─────────────────────────────────────────────────────────────────────────────
# Helper factories
# ─────────────────────────────────────────────────────────────────────────────

def _make_borrower(
    borrower_id="B001",
    name="Test User",
    dob=date(1985, 3, 15),
    gender="M",
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
    agreement_value=5500000,
    builder_name="Test Builder",
    stages=None,
) -> Property:
    if stages is None:
        stages = [
            StageItem("Foundation", Decimal("30")),
            StageItem("Structure",  Decimal("40")),
            StageItem("Finishing",  Decimal("30")),
        ]
    return Property(
        property_id=property_id,
        agreement_value=Decimal(str(agreement_value)),
        builder_name=builder_name,
        stages=stages,
    )


# ─────────────────────────────────────────────────────────────────────────────
# BR-01: LTV tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLTV(unittest.TestCase):

    def test_ltv_below_30_lakh(self):
        """Values below 30 L → 90 %."""
        ltv, rule = calculate_ltv_limit(Decimal('2500000'))
        self.assertEqual(rule, "BR-01")
        self.assertEqual(ltv, Decimal('2250000'))

    def test_ltv_30_lakh_boundary(self):
        """Exactly 30 L → 90 %."""
        ltv, rule = calculate_ltv_limit(Decimal('3000000'))
        self.assertEqual(rule, "BR-01")
        self.assertEqual(ltv, Decimal('2700000'))

    def test_ltv_30_lakh_plus_one_rupee(self):
        """30 L + 1 → 80 %."""
        ltv, rule = calculate_ltv_limit(Decimal('3000001'))
        self.assertEqual(rule, "BR-01")
        self.assertEqual(ltv, Decimal('2400001'))   # 3000001 * 0.80 = 2400000.8 → rounds to 2400001

    def test_ltv_75_lakh_boundary(self):
        """Exactly 75 L → 80 %."""
        ltv, rule = calculate_ltv_limit(Decimal('7500000'))
        self.assertEqual(rule, "BR-01")
        self.assertEqual(ltv, Decimal('6000000'))

    def test_ltv_75_lakh_plus_one_rupee(self):
        """75 L + 1 → 75 %."""
        ltv, rule = calculate_ltv_limit(Decimal('7500001'))
        self.assertEqual(rule, "BR-01")
        # 7500001 * 0.75 = 5625000.75 → rounds to 5625001
        self.assertEqual(ltv, Decimal('5625001'))

    def test_ltv_above_75_lakh(self):
        """90 L → 75 %."""
        ltv, rule = calculate_ltv_limit(Decimal('9000000'))
        self.assertEqual(rule, "BR-01")
        self.assertEqual(ltv, Decimal('6750000'))


# ─────────────────────────────────────────────────────────────────────────────
# BR-02: Tenure tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTenure(unittest.TestCase):

    def test_tenure_age_cap(self):
        """Born 1975-01-01, sanction 2024-01-15 → age 49 → cap = 252 months."""
        borrower = _make_borrower(dob=date(1975, 1, 1))
        tenure, rule = calculate_max_tenure(borrower, date(2024, 1, 15))
        self.assertEqual(rule, "BR-02")
        # age = 49 (birthday Jan 1 has passed by Jan 15)
        # months to 70 = 21 * 12 = 252
        self.assertEqual(tenure, 252)

    def test_tenure_30_year_cap(self):
        """Young borrower (born 2000-01-01) → 360-month cap applies."""
        borrower = _make_borrower(dob=date(2000, 1, 1))
        tenure, rule = calculate_max_tenure(borrower, date(2024, 1, 15))
        self.assertEqual(rule, "BR-02")
        # age = 24 → months to 70 = 46 * 12 = 552 > 360 → cap at 360
        self.assertEqual(tenure, 360)

    def test_tenure_boundary_age(self):
        """Borrower just turned 40 → months to 70 = 360 → both caps equal."""
        borrower = _make_borrower(dob=date(1984, 1, 15))
        tenure, rule = calculate_max_tenure(borrower, date(2024, 1, 15))
        self.assertEqual(rule, "BR-02")
        # age exactly 40 → months to 70 = 30 * 12 = 360 = max tenure → 360
        self.assertEqual(tenure, 360)

    def test_tenure_age_not_yet_birthday(self):
        """Borrower born March 15, sanction Jan 15 → birthday not yet occurred."""
        borrower = _make_borrower(dob=date(1975, 3, 15))
        tenure, rule = calculate_max_tenure(borrower, date(2024, 1, 15))
        # age = 48 (birthday in March hasn't occurred by Jan 15)
        # months to 70 = 22 * 12 = 264
        self.assertEqual(tenure, 264)


# ─────────────────────────────────────────────────────────────────────────────
# BR-03 / BR-04: Eligibility / income tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEligibility(unittest.TestCase):

    def test_income_ratio_below_1_lakh(self):
        """Income ₹80,000 → ratio 55%."""
        ratio = BusinessRules.emi_income_ratio(Decimal('80000'))
        self.assertEqual(ratio, Decimal('0.55'))

    def test_income_ratio_at_1_lakh(self):
        """Income exactly ₹1,00,000 → ratio 55%."""
        ratio = BusinessRules.emi_income_ratio(Decimal('100000'))
        self.assertEqual(ratio, Decimal('0.55'))

    def test_income_ratio_above_1_lakh(self):
        """Income ₹1,50,000 → ratio 60%."""
        ratio = BusinessRules.emi_income_ratio(Decimal('150000'))
        self.assertEqual(ratio, Decimal('0.60'))

    def test_coapplicant_spouse_full_income(self):
        """SPOUSE co-applicant → 100% income counted."""
        coa = CoApplicant("Spouse", Decimal('80000'), "SPOUSE")
        borrower = _make_borrower(net_income_monthly=150000, coapplicant=coa)
        combined = calculate_combined_income(borrower)
        self.assertEqual(combined, Decimal('230000'))

    def test_coapplicant_other_half_income(self):
        """OTHER co-applicant → 50% income counted."""
        coa = CoApplicant("Other", Decimal('80000'), "OTHER")
        borrower = _make_borrower(net_income_monthly=150000, coapplicant=coa)
        combined = calculate_combined_income(borrower)
        self.assertEqual(combined, Decimal('190000'))  # 150000 + 40000

    def test_no_coapplicant(self):
        """No co-applicant → only borrower income."""
        borrower = _make_borrower(net_income_monthly=150000)
        combined = calculate_combined_income(borrower)
        self.assertEqual(combined, Decimal('150000'))


# ─────────────────────────────────────────────────────────────────────────────
# BR-05 / BR-06: Interest rate tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRate(unittest.TestCase):

    BENCHMARK = Decimal('8.5')

    def test_spread_high_credit(self):
        """Score 780 (≥775) → +0.50%."""
        spread = BusinessRules.credit_spread(780)
        self.assertEqual(spread, Decimal('0.50'))

    def test_spread_boundary_high(self):
        """Score exactly 775 → +0.50%."""
        spread = BusinessRules.credit_spread(775)
        self.assertEqual(spread, Decimal('0.50'))

    def test_spread_mid_credit(self):
        """Score 750 (725–774) → +0.90%."""
        spread = BusinessRules.credit_spread(750)
        self.assertEqual(spread, Decimal('0.90'))

    def test_spread_boundary_mid_low(self):
        """Score exactly 725 → +0.90%."""
        spread = BusinessRules.credit_spread(725)
        self.assertEqual(spread, Decimal('0.90'))

    def test_spread_low_credit(self):
        """Score 700 (<725) → +1.40%."""
        spread = BusinessRules.credit_spread(700)
        self.assertEqual(spread, Decimal('1.40'))

    def test_women_concession(self):
        """Female borrower → -0.05%."""
        rate, rules = calculate_interest_rate(self.BENCHMARK, 780, "F")
        self.assertIn("BR-06", rules)
        # 8.5 + 0.50 - 0.05 = 8.95
        self.assertEqual(rate, Decimal('8.95'))

    def test_no_women_concession_for_male(self):
        """Male borrower → no concession."""
        rate, rules = calculate_interest_rate(self.BENCHMARK, 780, "M")
        self.assertNotIn("BR-06", rules)
        self.assertEqual(rate, Decimal('9.00'))

    def test_benchmark_plus_spread_high(self):
        """Benchmark 8.5 + spread 0.50 = 9.00%."""
        rate, _ = calculate_interest_rate(self.BENCHMARK, 780, "M")
        self.assertEqual(rate, Decimal('9.00'))

    def test_benchmark_plus_spread_mid(self):
        """Benchmark 8.5 + spread 0.90 = 9.40%."""
        rate, _ = calculate_interest_rate(self.BENCHMARK, 750, "M")
        self.assertEqual(rate, Decimal('9.40'))

    def test_benchmark_plus_spread_low(self):
        """Benchmark 8.5 + spread 1.40 = 9.90%."""
        rate, _ = calculate_interest_rate(self.BENCHMARK, 700, "M")
        self.assertEqual(rate, Decimal('9.90'))


# ─────────────────────────────────────────────────────────────────────────────
# BR-08: Processing fee tests
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessingFee(unittest.TestCase):

    def test_fee_minimum(self):
        """Small loan (₹10 L) → 0.5% = 5000 < min 10000 → floor at 10000 + GST."""
        result = calculate_processing_fee(Decimal('1000000'))
        self.assertEqual(result["gross_fee"], Decimal('10000.00'))
        self.assertEqual(result["gst"], Decimal('1800.00'))
        self.assertEqual(result["total_fee"], Decimal('11800.00'))
        self.assertEqual(result["rule_id"], "BR-08")

    def test_fee_maximum(self):
        """Large loan (₹1 Cr) → 0.5% = 50000 > max 25000 → cap at 25000 + GST."""
        result = calculate_processing_fee(Decimal('10000000'))
        self.assertEqual(result["gross_fee"], Decimal('25000.00'))
        self.assertEqual(result["gst"], Decimal('4500.00'))
        self.assertEqual(result["total_fee"], Decimal('29500.00'))

    def test_fee_normal(self):
        """Mid loan (₹50 L) → 0.5% = 25000 which is exactly max → 25000 + GST."""
        result = calculate_processing_fee(Decimal('5000000'))
        self.assertEqual(result["gross_fee"], Decimal('25000.00'))
        self.assertEqual(result["total_fee"], Decimal('29500.00'))

    def test_fee_normal_within_range(self):
        """₹30 L → 0.5% = 15000 (within range) → 15000 + 18% GST."""
        result = calculate_processing_fee(Decimal('3000000'))
        self.assertEqual(result["gross_fee"], Decimal('15000.00'))
        self.assertEqual(result["gst"], Decimal('2700.00'))
        self.assertEqual(result["total_fee"], Decimal('17700.00'))

    def test_fee_split_50_50(self):
        """at_sanction + at_first_disbursal == total_fee."""
        result = calculate_processing_fee(Decimal('3000000'))
        self.assertEqual(
            result["at_sanction"] + result["at_first_disbursal"],
            result["total_fee"],
        )

    def test_fee_split_equal(self):
        """Both halves are equal."""
        result = calculate_processing_fee(Decimal('3000000'))
        self.assertEqual(result["at_sanction"], result["at_first_disbursal"])


# ─────────────────────────────────────────────────────────────────────────────
# BR-09: Sanction expiry tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSanctionExpiry(unittest.TestCase):

    def test_expiry_6_months_normal(self):
        """Jan 15 + 6 months = Jul 15."""
        result = _add_months(date(2024, 1, 15), 6)
        self.assertEqual(result, date(2024, 7, 15))

    def test_expiry_end_of_month(self):
        """Jan 31 + 6 months = Jul 31 (July has 31 days)."""
        result = _add_months(date(2024, 1, 31), 6)
        self.assertEqual(result, date(2024, 7, 31))

    def test_expiry_end_of_month_clamp(self):
        """Aug 31 + 6 months = Feb 29 (2024 is leap year)."""
        result = _add_months(date(2024, 8, 31), 6)
        self.assertEqual(result, date(2025, 2, 28))

    def test_expiry_year_rollover(self):
        """Sep 30 + 6 months = Mar 30."""
        result = _add_months(date(2024, 9, 30), 6)
        self.assertEqual(result, date(2025, 3, 30))

    def test_sanction_expiry_via_process(self):
        """Full process_sanction sets expiry 6 months out."""
        borrower = _make_borrower(dob=date(1985, 1, 1))
        prop = _make_property(agreement_value=5000000)
        result = process_sanction(borrower, prop, Decimal('8.5'), date(2024, 1, 15))
        self.assertEqual(result.expiry_date, date(2024, 7, 15))


# ─────────────────────────────────────────────────────────────────────────────
# BR-07: Sanction amount tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSanctionAmount(unittest.TestCase):

    def test_sanction_ltv_binding(self):
        """When LTV < eligibility, sanctioned amount = LTV limit."""
        ltv = Decimal('2000000')
        elig = Decimal('3000000')
        self.assertEqual(BusinessRules.sanctioned_amount(ltv, elig), ltv)

    def test_sanction_eligibility_binding(self):
        """When eligibility < LTV, sanctioned amount = eligibility limit."""
        ltv = Decimal('3000000')
        elig = Decimal('2000000')
        self.assertEqual(BusinessRules.sanctioned_amount(ltv, elig), elig)

    def test_sanction_equal(self):
        """When both equal, sanctioned amount = either."""
        amount = Decimal('2500000')
        self.assertEqual(BusinessRules.sanctioned_amount(amount, amount), amount)

    def test_sanction_amount_in_result(self):
        """process_sanction produces min(ltv, eligibility) as sanctioned_amount."""
        borrower = _make_borrower(
            dob=date(1985, 3, 15),
            net_income_monthly=150000,
            credit_score=780,
        )
        prop = _make_property(agreement_value=9000000)  # LTV 75% = 67.5L
        result = process_sanction(borrower, prop, Decimal('8.5'), date(2024, 1, 15))
        self.assertLessEqual(result.sanctioned_amount, result.ltv_limit)
        self.assertLessEqual(result.sanctioned_amount, result.eligibility_limit)


# ─────────────────────────────────────────────────────────────────────────────
# Integration test
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegration(unittest.TestCase):

    def setUp(self):
        """Set up a realistic borrower / property pair."""
        self.coa = CoApplicant("Priya Sharma", Decimal('80000'), "SPOUSE")
        self.borrower = Borrower(
            borrower_id="B001",
            name="Aarav Sharma",
            dob=date(1985, 3, 15),
            gender="M",
            net_income_monthly=Decimal('150000'),
            credit_score=780,
            coapplicant=self.coa,
        )
        self.property_ = Property(
            property_id="P001",
            agreement_value=Decimal('7500000'),
            builder_name="ABC Builders",
            stages=[
                StageItem("Foundation", Decimal('20')),
                StageItem("Structure",  Decimal('30')),
                StageItem("Finishing",  Decimal('50')),
            ],
        )
        self.sanction_date = date(2024, 1, 15)
        self.benchmark_rate = Decimal('8.5')

    def test_full_sanction_flow(self):
        """End-to-end: process_sanction returns a fully populated SanctionResult."""
        result = process_sanction(
            self.borrower,
            self.property_,
            self.benchmark_rate,
            self.sanction_date,
        )
        self.assertIsInstance(result, SanctionResult)
        self.assertEqual(result.status, "SANCTIONED")
        self.assertTrue(result.loan_id.startswith("LN2024"))
        self.assertEqual(result.sanction_date, self.sanction_date)
        self.assertEqual(result.expiry_date, date(2024, 7, 15))
        self.assertGreater(result.sanctioned_amount, Decimal('0'))
        self.assertIn("BR-01", result.rule_ids_applied)
        self.assertIn("BR-07", result.rule_ids_applied)
        self.assertIn("BR-08", result.rule_ids_applied)
        self.assertIn("BR-09", result.rule_ids_applied)

    def test_sanction_letter_generated(self):
        """Sanction letter is a non-empty string containing key fields."""
        result = process_sanction(
            self.borrower,
            self.property_,
            self.benchmark_rate,
            self.sanction_date,
        )
        letter = generate_sanction_letter(result, self.borrower, self.property_)
        self.assertIsInstance(letter, str)
        self.assertIn(result.loan_id, letter)
        self.assertIn(self.borrower.name, letter)
        self.assertIn(self.property_.builder_name, letter)
        self.assertIn("SANCTIONED", letter)

    def test_parse_and_sanction(self):
        """Parse sample files and produce a sanction result without errors."""
        from src.parsers.input_parser import (
            parse_borrower_file,
            parse_property_file,
            parse_command_file,
        )
        project_root = Path(__file__).resolve().parent.parent
        borrowers = {b.borrower_id: b for b in parse_borrower_file(
            project_root / "data" / "sample" / "borrowers.json"
        )}
        properties = {p.property_id: p for p in parse_property_file(
            project_root / "data" / "sample" / "properties.json"
        )}
        commands = parse_command_file(
            project_root / "data" / "sample" / "commands.json"
        )
        self.assertGreater(len(borrowers), 0)
        self.assertGreater(len(properties), 0)
        self.assertGreater(len(commands), 0)

        # Process first SANCTION command
        cmd = next(c for c in commands if c["command"] == "SANCTION")
        result = process_sanction(
            borrowers[cmd["borrower_id"]],
            properties[cmd["property_id"]],
            cmd["benchmark_rate"],
            cmd["date"],
        )
        self.assertIsInstance(result, SanctionResult)
        self.assertGreater(result.sanctioned_amount, Decimal('0'))

    def test_women_borrower_rate_concession(self):
        """Female borrower gets -0.05% rate concession."""
        female_borrower = _make_borrower(gender="F", credit_score=780)
        male_borrower = _make_borrower(gender="M", credit_score=780)
        prop = _make_property(agreement_value=5000000)
        r_female = process_sanction(female_borrower, prop, Decimal('8.5'), date(2024, 1, 15))
        r_male = process_sanction(male_borrower, prop, Decimal('8.5'), date(2024, 1, 15))
        self.assertEqual(r_female.interest_rate, r_male.interest_rate - Decimal('0.05'))

    def test_processing_fee_in_result(self):
        """SanctionResult contains a complete processing_fee breakdown."""
        result = process_sanction(
            self.borrower, self.property_, self.benchmark_rate, self.sanction_date
        )
        fee = result.processing_fee
        self.assertIn("gross_fee", fee)
        self.assertIn("gst", fee)
        self.assertIn("total_fee", fee)
        self.assertIn("at_sanction", fee)
        self.assertIn("at_first_disbursal", fee)
        self.assertEqual(fee["at_sanction"] + fee["at_first_disbursal"], fee["total_fee"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
