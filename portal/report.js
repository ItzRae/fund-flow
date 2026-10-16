/**
 * Displays synthetic fund metrics in the sample report table.
 * Each record represents one metric for a fund and reporting period, with
 * monetary values kept as strings to preserve their original formatting.
 * A one-second delay simulates a portal loading data after the page opens,
 * so the future Playwright collector must wait for the rows before reading them.
 */
const reports = [
    {
        fund_id: "FUND-001",
        reporting_period: "2026-06-30",
        metric: "net_asset_value",
        raw_value: "$1,250,000.00",
        currency: "USD"
    },
    {
        fund_id: "FUND-001",
        reporting_period: "2026-06-30",
        metric: "distributions",
        raw_value: "$25,000.00",
        currency: "USD"
    },
];

const tableBody = document.querySelector("#report-rows");
const status = document.querySelector("#report-status");

function displayReports() {
  for (const report of reports) {
    const row = document.createElement("tr");

    const values = [
      report.fund_id,
      report.reporting_period,
      report.metric,
      report.raw_value,
      report.currency,
    ];

    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }

    tableBody.appendChild(row);
  }

  status.textContent = "Report loaded.";
}

status.textContent = "Loading report...";
setTimeout(displayReports, 1000);
