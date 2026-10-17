"""Read a downloaded holdings CSV without opening a browser."""

import csv
from pathlib import Path


def parse_holdings(path: Path):
    """Return the report date and holdings, preserving source values as strings.

    Raise ValueError for missing metadata or inconsistent row widths.
    Date and numeric value validation belong to a later processing step.
    """
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))

    header_index = None
    for index, row in enumerate(rows):
        if row and {"Ticker", "Name", "Market Value"}.issubset(row):
            header_index = index
            break

    if header_index is None:
        raise ValueError("Holdings column header not found")

    report_date = None
    for row in rows[:header_index]:
        if len(row) >= 2 and row[0] == "Fund Holdings as of":
            report_date = row[1].strip()
            break

    if not report_date:
        raise ValueError("Report date not found")

    # turn holding rows into dictionaries
    headers = rows[header_index]

    holdings = []
    for line_number, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not row:
            continue

        if len(headers) != len(row):
            raise ValueError(
                f"CSV row {line_number}: expected {len(headers)} cells, got {len(row)}"
            )

        holdings.append(dict(zip(headers, row)))

    if not holdings:
        raise ValueError("No holdings rows found")

    return {
        "report_date": report_date,
        "holdings": holdings,
    }


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description="Inspect a saved holdings CSV.")
    cli.add_argument("path", type=Path, help="Path to the downloaded CSV")
    args = cli.parse_args()
    report = parse_holdings(args.path)
    print(f"Report date: {report['report_date']}")
    print(f"Holdings: {len(report['holdings'])}")
