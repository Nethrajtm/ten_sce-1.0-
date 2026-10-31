"""
src/models/borrower.py
Dataclasses for Borrower and CoApplicant entities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass
class CoApplicant:
    """Represents a co-applicant on the home loan."""
    name: str
    income_monthly: Decimal
    relationship: str  # "SPOUSE" or "OTHER"

    def __post_init__(self):
        if self.relationship not in ("SPOUSE", "OTHER"):
            raise ValueError(f"Invalid relationship '{self.relationship}'. Must be 'SPOUSE' or 'OTHER'.")
        if not isinstance(self.income_monthly, Decimal):
            self.income_monthly = Decimal(str(self.income_monthly))


@dataclass
class Borrower:
    """Represents the primary borrower on the home loan."""
    borrower_id: str
    name: str
    dob: date
    gender: str          # "M" or "F"
    net_income_monthly: Decimal
    credit_score: int
    coapplicant: Optional[CoApplicant] = field(default=None)

    def __post_init__(self):
        if not isinstance(self.net_income_monthly, Decimal):
            self.net_income_monthly = Decimal(str(self.net_income_monthly))
        if self.gender not in ("M", "F"):
            raise ValueError(f"Invalid gender '{self.gender}'. Must be 'M' or 'F'.")

    def age_at_date(self, d: date) -> int:
        """Return the borrower's age in completed years on a given date."""
        years = d.year - self.dob.year
        # Subtract 1 if anniversary hasn't occurred yet in the target year
        if (d.month, d.day) < (self.dob.month, self.dob.day):
            years -= 1
        return years
