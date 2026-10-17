"""Validate values extracted from holdings reports."""

from datetime import date, datetime
from decimal import Decimal
import re


_NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?")


def parse_report_date(raw_date: str) -> date:
    """Parse a date in a string; raise ValueError if invalid."""
    try:
        return datetime.strptime(raw_date.strip(), "%b %d, %Y").date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid report date {raw_date!r}; expected a date like 'Oct 15, 2026'"
        ) from exc


def parse_decimal(raw_value: str) -> Decimal:
    """Parse signed numbers with optional thousands commas and decimal places.

    Blank strings and '-' mean missing, not zero. Currency symbols, percent
    signs, exponents, and parentheses are outside the supported CSV syntax.
    Weights remain in the source's percentage units: '2.50' becomes Decimal('2.50').
    """
    value = raw_value.strip()
    if value in {"", "-"}:
        raise ValueError("Missing numeric value")
    if not _NUMBER_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid numeric value: {raw_value!r}")
    return Decimal(value.replace(",", ""))
