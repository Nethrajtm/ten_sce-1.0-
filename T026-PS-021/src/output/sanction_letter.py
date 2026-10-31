"""
src/output/sanction_letter.py
Generates a formatted sanction letter as a plain-text string.
"""
from __future__ import annotations

from src.models.borrower import Borrower
from src.models.property import Property
from src.models.loan import SanctionResult

_SEP = "=" * 72
_SEP_THIN = "-" * 72


def _fmt_inr(amount) -> str:
    """Format a Decimal as Indian-style currency string e.g. ₹12,50,000.00"""
    # Convert to string with 2 dp
    s = f"{float(amount):,.2f}"
    # Re-format integer part with Indian grouping (last 3, then groups of 2)
    parts = s.split(".")
    int_part = parts[0].replace(",", "")
    dec_part = parts[1]
    # Indian grouping
    if len(int_part) <= 3:
        formatted = int_part
    else:
        formatted = int_part[-3:]
        int_part = int_part[:-3]
        while len(int_part) > 2:
            formatted = int_part[-2:] + "," + formatted
            int_part = int_part[:-2]
        if int_part:
            formatted = int_part + "," + formatted
    return f"\u20b9{formatted}.{dec_part}"


def generate_sanction_letter(
    result: SanctionResult,
    borrower: Borrower,
    property_: Property,
) -> str:
    """
    Generate a formatted sanction letter for a home loan.

    Parameters
    ----------
    result    : Completed SanctionResult from process_sanction().
    borrower  : Primary borrower details.
    property_ : Property details.

    Returns
    -------
    str  Plain-text sanction letter.
    """
    fee = result.processing_fee

    # Co-applicant line
    coa_line = "None"
    if borrower.coapplicant:
        coa_line = (
            f"{borrower.coapplicant.name} "
            f"({borrower.coapplicant.relationship}) — "
            f"Income: {_fmt_inr(borrower.coapplicant.income_monthly)}/month"
        )

    # Build stage table
    stage_rows = ""
    for s in property_.stages:
        tranche = result.sanctioned_amount * s.percentage / 100
        stage_rows += (
            f"  {s.stage_name:<25} {s.percentage:>6}%   {_fmt_inr(tranche)}\n"
        )

    letter = f"""{_SEP}
             HOME LOAN SANCTION LETTER
             Team T026 — Project PS-021
{_SEP}

Loan ID        : {result.loan_id}
Sanction Date  : {result.sanction_date.strftime('%d %B %Y')}
Valid Until    : {result.expiry_date.strftime('%d %B %Y')}   [BR-09]
Status         : {result.status}

{_SEP_THIN}
BORROWER DETAILS
{_SEP_THIN}
Borrower ID    : {borrower.borrower_id}
Name           : {borrower.name}
Date of Birth  : {borrower.dob.strftime('%d %B %Y')}
Gender         : {'Female' if borrower.gender == 'F' else 'Male'}
Net Income     : {_fmt_inr(borrower.net_income_monthly)} / month
Credit Score   : {borrower.credit_score}
Co-Applicant   : {coa_line}

{_SEP_THIN}
PROPERTY DETAILS
{_SEP_THIN}
Property ID    : {property_.property_id}
Builder        : {property_.builder_name}
Agreement Value: {_fmt_inr(property_.agreement_value)}

{_SEP_THIN}
LTV CALCULATION  [BR-01]
{_SEP_THIN}
Agreement Value  : {_fmt_inr(property_.agreement_value)}
LTV Ratio Applied: {float(result.ltv_limit / property_.agreement_value * 100):.0f}%
LTV Limit        : {_fmt_inr(result.ltv_limit)}

{_SEP_THIN}
ELIGIBILITY CALCULATION  [BR-10, BR-03, BR-04]
{_SEP_THIN}
Eligibility Limit: {_fmt_inr(result.eligibility_limit)}

{_SEP_THIN}
SANCTION DETAILS  [BR-07]
{_SEP_THIN}
Sanctioned Amount: {_fmt_inr(result.sanctioned_amount)}
  (= min of LTV Limit {_fmt_inr(result.ltv_limit)} and
        Eligibility Limit {_fmt_inr(result.eligibility_limit)})
Tenure           : {result.tenure_months} months ({result.tenure_months // 12} years {result.tenure_months % 12} months)  [BR-02]
Annual Rate      : {result.interest_rate}%  [BR-05{'/BR-06' if borrower.gender == 'F' else ''}]

{_SEP_THIN}
CONSTRUCTION-LINKED DISBURSEMENT TRANCHES
{_SEP_THIN}
  {'Stage':<25} {'%':>6}   {'Tranche Amount':>18}
  {'-'*25} {'-'*6}   {'-'*18}
{stage_rows}
{_SEP_THIN}
PROCESSING FEE  [BR-08]
{_SEP_THIN}
Gross Fee (0.5%, min ₹10k, max ₹25k) : {_fmt_inr(fee['gross_fee'])}
GST @ 18%                             : {_fmt_inr(fee['gst'])}
Total Fee                             : {_fmt_inr(fee['total_fee'])}
  Payable at Sanction (50%)           : {_fmt_inr(fee['at_sanction'])}
  Payable at First Disbursal (50%)    : {_fmt_inr(fee['at_first_disbursal'])}

{_SEP_THIN}
BUSINESS RULES APPLIED
{_SEP_THIN}
{', '.join(result.rule_ids_applied)}

{_SEP}
This sanction letter is subject to the terms and conditions of the loan
agreement. The sanction will lapse on {result.expiry_date.strftime('%d %B %Y')} if not availed.
A lapsed sanction forfeits 50% of the processing fee paid at sanction.

                                            Authorised Signatory
                                            Home Loans Division
{_SEP}
"""
    return letter
