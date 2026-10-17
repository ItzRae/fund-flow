"""Page object for the IVV holdings download workflow."""

from playwright.sync_api import Page

IVV_URL = "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf"


class FundPage:
    def __init__(self, page: Page):
        self.page = page

    def open(self):
        """ Open IVV fund page """
        self.page.goto(IVV_URL, wait_until="domcontentloaded")

        # with self.page.expect_download() as download_info:
        #     self.page.get_by_role("button", name="Data Download").click()

        # # get the download object
        # download = download_info.value
