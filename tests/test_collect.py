"""check collection ordering and batch recovery without browser or aws calls."""

import json
from unittest.mock import Mock

import pytest

from fundflow import collect
from fundflow.funds import FUNDS


def test_download_failure_prevents_upload(monkeypatch, tmp_path):
    fund_page = Mock()
    fund_page.download_holdings.side_effect = RuntimeError("download failed")
    monkeypatch.setattr(collect, "FundPage", Mock(return_value=fund_page))
    upload = Mock()
    monkeypatch.setattr(collect, "upload_report", upload)
    with pytest.raises(RuntimeError, match="download failed"):
        collect.collect_fund(Mock(), Mock(), FUNDS[0], "bucket", "run-1", tmp_path)
    upload.assert_not_called()


def test_download_precedes_upload(monkeypatch, tmp_path):
    fund_page = Mock()
    def download(path):
        path.write_bytes(b"original report")
    fund_page.download_holdings.side_effect = download
    monkeypatch.setattr(collect, "FundPage", Mock(return_value=fund_page))
    def upload(client, **kwargs):
        assert kwargs["path"].read_bytes() == b"original report"
        assert kwargs["fund_id"] == FUNDS[0].fund_id
        assert kwargs["source_url"] == FUNDS[0].url
        assert kwargs["retrieved_at"].utcoffset() is not None
        return {"key": "saved-key"}
    monkeypatch.setattr(collect, "upload_report", upload)
    assert collect.collect_fund(Mock(), Mock(), FUNDS[0], "bucket", "run-1", tmp_path) == {
        "key": "saved-key"
    }


def test_batch_continues_after_failure_and_saves_summary(monkeypatch, tmp_path):
    browser = Mock()
    contexts = [Mock(), Mock()]
    browser.new_context.side_effect = contexts
    worker = Mock(side_effect=[RuntimeError("upload failed"), {"key": "second-file"}])
    monkeypatch.setattr(collect, "collect_fund", worker)
    summary = collect.collect_batch(browser, Mock(), FUNDS[:2], "bucket", tmp_path)
    assert [r["status"] for r in summary["results"]] == ["FAILED", "STORED"]
    assert summary["results"][1]["source"] == {"key": "second-file"}
    # two distinct run ids
    assert len({r["run_id"] for r in summary["results"]}) == 2
    for context in contexts:
        context.close.assert_called_once()
    saved = tmp_path / summary["batch_id"] / "summary.json"
    assert json.loads(saved.read_text()) == summary
