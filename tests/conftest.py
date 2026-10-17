"""Shared fixtures for configured fund page tests."""

import pytest
from playwright.sync_api import Page

from fundflow.funds import FUNDS, FundConfig
from fundflow.pages.fund_page import FundPage


@pytest.fixture(params=FUNDS, ids=lambda fund: fund.fund_id)
def fund(request) -> FundConfig:
    """Run each dependent test once per configured fund."""
    return request.param


@pytest.fixture
def fund_page(page: Page, fund: FundConfig) -> FundPage:
    """Combine the plugin-managed browser page with a fund configuration."""
    return FundPage(page, fund)
