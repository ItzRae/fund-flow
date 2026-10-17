"""Shared browser fixtures for fund page tests."""

import pytest
from playwright.sync_api import Page

from fundflow.pages.fund_page import FundPage

@pytest.fixture
def fund_page(page: Page) -> FundPage:
    """Wrap the plugin-managed browser page in our fund page object."""
    return FundPage(page)
