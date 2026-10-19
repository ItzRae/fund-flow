"""check the holdings query without connecting to atlas."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from bson.decimal128 import Decimal128

from fundflow.app import list_fund_holdings


def test_holdings_filters_sort_and_response():
    database = MagicMock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=database)))
    runs, snapshots, holdings = MagicMock(), MagicMock(), MagicMock()
    database.__getitem__.side_effect = {'processing_runs': runs, 'report_snapshots': snapshots, 'holdings': holdings}.__getitem__
    runs.find_one.return_value = {'snapshot_id': 'snapshot', 'rejected': 2}
    snapshots.find_one.return_value = {'report_date': '2026-10-15'}
    holdings.distinct.return_value = ['Equity', 'Cash']
    holdings.count_documents.return_value = 1
    holdings.find.return_value.sort.return_value.skip.return_value.limit.return_value = [{
        'name': 'A.B', 'asset_class': 'Equity', 'market_value': Decimal128('1234567890123456789.01'),
        'weight_percent': Decimal128('2.50'), 'raw': {'Currency': 'USD', 'Market Currency': 'EUR'},
    }]
    result = list_fund_holdings('IEFA', request, offset=0, limit=50, sort_by='weight_percent', direction='desc', asset_class='Equity', search='A.B')
    expected = {'snapshot_id': 'snapshot', 'asset_class': 'Equity', 'name': {'$regex': r'A\.B', '$options': 'i'}}
    holdings.find.assert_called_once_with(expected)
    holdings.count_documents.assert_called_once_with(expected)
    holdings.find.return_value.sort.assert_called_once_with([('weight_percent', -1), ('row_hash', 1)])
    assert result['holdings'][0]['market_value'] == '1234567890123456789.01'
    assert result['holdings'][0]['currency'] == 'USD'
    assert result['asset_classes'] == ['Cash', 'Equity']
    assert result['rejected'] == 2
