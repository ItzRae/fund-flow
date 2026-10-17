"""Shared browser workflow for configured iShares fund pages."""

from pathlib import Path

from playwright.sync_api import Page

from fundflow.funds import FundConfig


class FundPage:
    def __init__(self, page: Page, fund: FundConfig):
        self.page = page
        self.fund = fund

    def open(self) -> None:
        """Open the configured fund page."""
        self.page.goto(self.fund.url, wait_until="domcontentloaded")

    def download_holdings(self, destination: Path) -> Path:
        """ Download the holdings CSV and save it to the destination. """
        with self.page.expect_download() as download_info:
            self.page.locator(
                'a[data-id="holdings-document-download"]'
            ).click()

        # get the download object
        download = download_info.value
        download.save_as(destination)
        return destination
