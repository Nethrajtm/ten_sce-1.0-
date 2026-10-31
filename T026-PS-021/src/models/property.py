"""
src/models/property.py
Dataclasses for Property and StageItem entities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List


@dataclass
class StageItem:
    """Represents a single construction stage and its disbursement percentage."""
    stage_name: str
    percentage: Decimal  # percentage of total loan amount

    def __post_init__(self):
        if not isinstance(self.percentage, Decimal):
            self.percentage = Decimal(str(self.percentage))


@dataclass
class Property:
    """Represents the property being purchased / constructed."""
    property_id: str
    agreement_value: Decimal
    builder_name: str
    stages: List[StageItem] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.agreement_value, Decimal):
            self.agreement_value = Decimal(str(self.agreement_value))

    def validate_stages(self) -> bool:
        """Return True if the stage percentages sum to exactly 100."""
        total = sum(s.percentage for s in self.stages)
        return total == Decimal('100')
