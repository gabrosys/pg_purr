"""Unit tests for the QRNG client (LfD primary, NIST Beacon fallback)."""

from unittest.mock import MagicMock, patch

import pytest

from pg_purr.qrng.qrng_client import fetch_quantum_random


def _lfd_response(length_bytes: int, seed: int = 0) -> MagicMock:
    qrn_hex = "".join(f"{(seed + i) % 256:02x}" for i in range(length_bytes))
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"length": length_bytes, "qrn": qrn_hex}
    return resp


def _nist_response(seed: int = 0, ts: str = "2026-04-20T06:58:00.000Z") -> MagicMock:
    # 512-bit outputValue = 128 hex chars
    out_hex = "".join(f"{(seed + i) % 256:02x}" for i in range(64))
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"pulse": {"outputValue": out_hex, "timeStamp": ts}}
    return resp


def _routing_get(*, lfd_raises: bool = False, nist_raises: bool = False):
    """Return a fake `requests.get` that dispatches on URL."""

    def fake_get(url, **kwargs):
        if "lfdr.de" in url:
            if lfd_raises:
                raise ConnectionError("lfd unreachable")
            length = kwargs["params"]["length"]
            return _lfd_response(length)
        if "beacon.nist.gov" in url:
            if nist_raises:
                raise ConnectionError("nist unreachable")
            # Use a different seed per timestamp so bytes aren't identical.
            seed = sum(ord(c) for c in url) & 0xFF
            return _nist_response(seed=seed)
        raise AssertionError(f"unexpected URL: {url}")

    return fake_get


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_lfd_happy_path_uint16(mock_get):
    mock_get.side_effect = _routing_get()
    values = fetch_quantum_random(count=3, data_type="uint16")
    assert len(values) == 3
    assert all(0 <= v <= 0xFFFF for v in values)
    # Only LfD should have been contacted.
    assert all("lfdr.de" in c.args[0] for c in mock_get.call_args_list)


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_lfd_happy_path_uint8(mock_get):
    mock_get.side_effect = _routing_get()
    values = fetch_quantum_random(count=4, data_type="uint8")
    assert len(values) == 4
    assert all(0 <= v <= 0xFF for v in values)


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_lfd_passes_length_and_format(mock_get):
    mock_get.side_effect = _routing_get()
    fetch_quantum_random(count=4, data_type="uint16")
    lfd_calls = [c for c in mock_get.call_args_list if "lfdr.de" in c.args[0]]
    assert lfd_calls[0].kwargs["params"] == {"length": 8, "format": "HEX"}


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_lfd_batches_large_requests(mock_get):
    # 40_000 uint16 = 80_000 bytes; LFD cap is 65_536 → 2 calls.
    mock_get.side_effect = _routing_get()
    values = fetch_quantum_random(count=40_000, data_type="uint16")
    assert len(values) == 40_000
    lfd_calls = [c for c in mock_get.call_args_list if "lfdr.de" in c.args[0]]
    assert len(lfd_calls) == 2
    assert lfd_calls[0].kwargs["params"]["length"] == 65_536
    assert lfd_calls[1].kwargs["params"]["length"] == 14_464


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_falls_back_to_nist_when_lfd_fails(mock_get):
    mock_get.side_effect = _routing_get(lfd_raises=True)
    values = fetch_quantum_random(count=10, data_type="uint16")
    assert len(values) == 10
    urls = [c.args[0] for c in mock_get.call_args_list]
    assert any("lfdr.de" in u for u in urls)
    assert any("beacon.nist.gov" in u for u in urls)


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_nist_walks_history_for_large_requests(mock_get):
    # 2000 uint16 = 4000 bytes; NIST gives 64 bytes/pulse → 63 pulses.
    # Each /pulse/time/previous/{ts} request must use the previous
    # pulse's timestamp minus 1 ms — a stride of the full 60_000 ms
    # pulse period would skip every other pulse.
    from pg_purr.qrng.qrng_client import _parse_nist_timestamp_ms

    fake_ts = "2026-04-20T06:58:00.000Z"
    mock_get.side_effect = _routing_get(lfd_raises=True)
    values = fetch_quantum_random(count=2_000, data_type="uint16")
    assert len(values) == 2_000
    nist_calls = [c for c in mock_get.call_args_list if "beacon.nist.gov" in c.args[0]]
    # First /pulse/last, then 62 /pulse/time/previous/ calls.
    assert len(nist_calls) == 63
    assert "/pulse/last" in nist_calls[0].args[0]
    assert all("/pulse/time/previous/" in c.args[0] for c in nist_calls[1:])

    # The fake NIST response always echoes the same timestamp, so every
    # previous-walk request must ask for fake_ts - 1 ms.
    expected_ts = _parse_nist_timestamp_ms(fake_ts) - 1
    for call in nist_calls[1:]:
        ts_in_url = int(call.args[0].rsplit("/", 1)[-1])
        assert ts_in_url == expected_ts, (
            f"expected stride of -1 ms; got request for {ts_in_url}, expected {expected_ts}"
        )


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_raises_when_all_sources_fail(mock_get):
    mock_get.side_effect = _routing_get(lfd_raises=True, nist_raises=True)
    with pytest.raises(RuntimeError, match="all QRNG sources failed"):
        fetch_quantum_random(count=1, data_type="uint16")


@patch("pg_purr.qrng.qrng_client.requests.get")
def test_raises_on_malformed_lfd_payload_and_falls_back(mock_get):
    # LfD returns short hex → QRNGSourceError → fall back to NIST.
    def fake_get(url, **kwargs):
        if "lfdr.de" in url:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"length": 4, "qrn": "deadbeef"}
            return resp
        return _nist_response()

    mock_get.side_effect = fake_get
    values = fetch_quantum_random(count=8, data_type="uint16")
    assert len(values) == 8


def test_rejects_invalid_count():
    with pytest.raises(ValueError):
        fetch_quantum_random(count=0)


def test_rejects_invalid_data_type():
    with pytest.raises(ValueError):
        fetch_quantum_random(count=1, data_type="float32")
