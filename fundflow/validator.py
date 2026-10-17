"""Validate values extracted from holdings reports."""

from datetime import date, datetime
from decimal import Decimal
import re


_NUMBER_PATTERN = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?")

def validate_report(report: dict) -> dict:
    """ validate the report date + seperate accepted and rejected holdings """

    report_date = parse_report_date(report["report_date"])
    accepted, rejected = [], []

    for holding_number, row in enumerate(report["holdings"], start=1):

        try:
            cleaned = validate_holding(row)
            accepted.append(cleaned)
        except ValueError as exc:
            rejected.append({
                "holding_number": holding_number,
                "raw": row.copy(),
                "reason": str(exc)
            })

    return {
        "report_date": report_date,
        "accepted": accepted,
        "rejected": rejected
    }



def validate_holding(row: dict) -> dict:
    """ check one holding and keep its original values alongside cleaned ones """

    # read and strip name and asset class
    name = row.get("Name", "").strip()
    asset_class = row.get("Asset Class", "").strip()

    if name in {"", "-"}:
        raise ValueError("Missing holding name")

    if asset_class in {"", "-"}:
        raise ValueError("Missing asset class")

    # include the column name so a rejection explains which value needs attention
    try:
        market_value = parse_decimal(row.get("Market Value", ""))
    except ValueError as exc:
        raise ValueError(f"Market Value: {exc}") from exc
    try:
        weight_percent = parse_decimal(row.get("Weight (%)", ""))
    except ValueError as exc:
        raise ValueError(f"Weight (%): {exc}") from exc

    return {
        "name": name,
        "asset_class": asset_class,
        "market_value": market_value,
        "weight_percent": weight_percent,
        "raw": row.copy()
    }

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
