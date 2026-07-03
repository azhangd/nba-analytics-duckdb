import json

import pytest

from nba_duckdb.exceptions import LiveEndpointUnavailableError

pytest.importorskip("nba_api")


def test_play_by_play_falls_back_to_stats_v3(monkeypatch):
    from nba_duckdb.utils import nba_client

    calls = []

    def fail_live(*_args, **_kwargs):
        calls.append("live")
        raise json.JSONDecodeError("Expecting value", "", 0)

    def fake_stats(endpoint_cls, *, result_validator, **_kwargs):
        calls.append(endpoint_cls.__name__)
        payload = {"game": {"actions": [{"actionNumber": 1}]}}
        assert result_validator(payload)
        return payload

    monkeypatch.setattr(nba_client, "_call_live_endpoint", fail_live)
    monkeypatch.setattr(nba_client, "_call_with_rate_limit", fake_stats)

    payload, source = nba_client.get_play_by_play_with_source("0029900001")
    assert payload == {"game": {"actions": [{"actionNumber": 1}]}}
    assert source == "stats_v3"
    assert calls == ["live", "PlayByPlayV3"]

    calls.clear()
    assert nba_client.get_play_by_play("0029900001") == {
        "game": {"actions": [{"actionNumber": 1}]}
    }
    assert calls == ["live", "PlayByPlayV3"]


def test_play_by_play_records_live_source(monkeypatch):
    from nba_duckdb.utils import nba_client

    def fake_live(_endpoint_cls, *, result_validator, **_kwargs):
        payload = {"game": {"actions": [{"actionNumber": 1}]}}
        assert result_validator(payload)
        return payload

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("stats fallback should not be called")

    monkeypatch.setattr(nba_client, "_call_live_endpoint", fake_live)
    monkeypatch.setattr(nba_client, "_call_with_rate_limit", fail_if_called)

    payload, source = nba_client.get_play_by_play_with_source("0029900001")

    assert payload == {"game": {"actions": [{"actionNumber": 1}]}}
    assert source == "live_cdn"


def test_play_by_play_raises_typed_error_when_both_sources_fail(monkeypatch):
    from nba_duckdb.utils import nba_client

    def fail_live(*_args, **_kwargs):
        raise json.JSONDecodeError("Expecting value", "", 0)

    def fail_stats(*_args, **_kwargs):
        raise RuntimeError("stats unavailable")

    monkeypatch.setattr(nba_client, "_call_live_endpoint", fail_live)
    monkeypatch.setattr(nba_client, "_call_with_rate_limit", fail_stats)

    with pytest.raises(LiveEndpointUnavailableError, match="live CDN and stats"):
        nba_client.get_play_by_play("0029900001")


def test_play_by_play_rejects_empty_actions_from_fallback(monkeypatch):
    from nba_duckdb.utils import nba_client

    def fail_live(*_args, **_kwargs):
        raise json.JSONDecodeError("Expecting value", "", 0)

    def fake_stats(_endpoint_cls, *, result_validator, **_kwargs):
        payload = {"game": {"actions": []}}
        if not result_validator(payload):
            raise ValueError("Incomplete response from PlayByPlayV3")
        return payload

    monkeypatch.setattr(nba_client, "_call_live_endpoint", fail_live)
    monkeypatch.setattr(nba_client, "_call_with_rate_limit", fake_stats)

    with pytest.raises(LiveEndpointUnavailableError, match="PlayByPlayV3"):
        nba_client.get_play_by_play("0029900001")
