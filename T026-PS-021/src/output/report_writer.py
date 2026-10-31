"""
src/output/report_writer.py
Utility functions for writing output files.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that converts Decimal values to strings."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def write_sanction_letter(letter: str, output_dir: Path, loan_id: str) -> Path:
    """
    Write a sanction letter to a .txt file.

    File is saved as: <output_dir>/<loan_id>_sanction_letter.txt

    Parameters
    ----------
    letter     : The formatted letter string.
    output_dir : Directory to write into (created if it doesn't exist).
    loan_id    : Used to construct the filename.

    Returns
    -------
    Path of the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{loan_id}_sanction_letter.txt"
    filepath.write_text(letter, encoding="utf-8")
    return filepath


def write_json_output(data: dict, output_dir: Path, filename: str) -> Path:
    """
    Write a dict to a JSON file.

    Parameters
    ----------
    data       : Dictionary to serialise.
    output_dir : Directory to write into (created if it doesn't exist).
    filename   : Output filename (e.g. "summary.json").

    Returns
    -------
    Path of the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / filename
    filepath.write_text(
        json.dumps(data, indent=2, cls=_DecimalEncoder, default=str),
        encoding="utf-8",
    )
    return filepath
