"""HTTP clients for quantum random number services, with automatic
failover between an ordered list of sources.

Primary source: LfD OTH Regensburg (ID Quantique Quantis PCIe photon
detector exposed over plain HTTP; libqrng, SoftwareX 2024).

Fallback source: NIST Randomness Beacon v2.0 (PML photon-detection
QRNG plus Bell-test generator, hashed and Ed25519-signed).
"""

from __future__ import annotations

import binascii
import logging
import struct
from datetime import datetime

import requests

log = logging.getLogger("pg_purr.qrng_client")

LFD_API_URL = "https://lfdr.de/qrng_api/qrng"
LFD_MAX_BYTES_PER_REQUEST = 65_536

NIST_BEACON_LAST = "https://beacon.nist.gov/beacon/2.0/pulse/last"
NIST_BEACON_PREVIOUS = "https://beacon.nist.gov/beacon/2.0/pulse/time/previous/{ts_ms}"
NIST_BYTES_PER_PULSE = 64  # 512-bit outputValue
NIST_PULSE_PERIOD_MS = 60_000

VALID_DATA_TYPES = {"uint8", "uint16", "hex16"}
_BYTES_PER_VALUE = {"uint8": 1, "uint16": 2, "hex16": 2}


class QRNGSourceError(RuntimeError):
    """A single QRNG source returned an unexpected response or declined
    to serve the request. Triggers fallback in `fetch_quantum_random`.
    """


def _decode_values(raw: bytes, data_type: str) -> list[int]:
    if data_type == "uint16":
        n = len(raw) // 2
        return list(struct.unpack(f"<{n}H", raw))
    return list(raw)


def _fetch_from_lfd(total_bytes: int, timeout: int) -> bytes:
    out = bytearray()
    remaining = total_bytes
    while remaining > 0:
        batch = min(remaining, LFD_MAX_BYTES_PER_REQUEST)
        r = requests.get(
            LFD_API_URL,
            params={"length": batch, "format": "HEX"},
            timeout=timeout,
        )
        r.raise_for_status()
        payload = r.json()
        qrn_hex = payload.get("qrn")
        if not isinstance(qrn_hex, str) or len(qrn_hex) != batch * 2:
            raise QRNGSourceError("LfD: unexpected response shape")
        raw = binascii.unhexlify(qrn_hex)
        if len(raw) != batch:
            raise QRNGSourceError(f"LfD: decoded {len(raw)} bytes, expected {batch}")
        out.extend(raw)
        remaining -= batch
    return bytes(out)


def _parse_nist_timestamp_ms(ts: str) -> int:
    # "2026-04-20T06:58:00.000Z"
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def _extract_nist_entropy(pulse: dict) -> tuple[bytes, int]:
    out_value = pulse.get("outputValue")
    ts = pulse.get("timeStamp")
    if (
        not isinstance(out_value, str)
        or len(out_value) != NIST_BYTES_PER_PULSE * 2
        or not isinstance(ts, str)
    ):
        raise QRNGSourceError("NIST: unexpected response shape")
    return binascii.unhexlify(out_value), _parse_nist_timestamp_ms(ts)


def _fetch_from_nist(total_bytes: int, timeout: int) -> bytes:
    r = requests.get(NIST_BEACON_LAST, timeout=timeout)
    r.raise_for_status()
    pulse = r.json().get("pulse") or {}
    entropy, ts_ms = _extract_nist_entropy(pulse)

    out = bytearray(entropy)
    while len(out) < total_bytes:
        # /pulse/time/previous/{ts} returns the pulse strictly earlier
        # than `ts`; step by one millisecond to land on the immediately
        # preceding pulse rather than skipping a full period.
        prev_url = NIST_BEACON_PREVIOUS.format(ts_ms=ts_ms - 1)
        r = requests.get(prev_url, timeout=timeout)
        r.raise_for_status()
        pulse = r.json().get("pulse") or {}
        entropy, ts_ms = _extract_nist_entropy(pulse)
        out.extend(entropy)

    return bytes(out[:total_bytes])


SOURCES = (
    ("lfd", _fetch_from_lfd),
    ("nist", _fetch_from_nist),
)


def fetch_quantum_random(
    count: int = 1,
    data_type: str = "uint16",
    timeout: int = 10,
) -> list[int]:
    """Fetch quantum random integers, trying each source in order.

    On any exception from a source, logs a warning and falls back to
    the next. Raises `RuntimeError` only when every source has failed.

    Args:
        count: Number of values to return (>= 1).
        data_type: One of 'uint8' (0..255), 'uint16' (0..65535),
            'hex16' (returned as integer bytes, same range as uint8).
        timeout: HTTP request timeout, seconds.

    Returns:
        List of integers of length `count` in the range implied by
        `data_type`.

    Raises:
        ValueError: if `count` or `data_type` are invalid.
        RuntimeError: if all sources fail.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    if data_type not in VALID_DATA_TYPES:
        raise ValueError(f"unsupported data_type: {data_type!r}")

    bytes_per_value = _BYTES_PER_VALUE[data_type]
    total_bytes = count * bytes_per_value

    errors: list[tuple[str, str]] = []
    for source_name, fetcher in SOURCES:
        try:
            raw = fetcher(total_bytes, timeout)
        except Exception as e:
            errors.append((source_name, repr(e)))
            log.warning("QRNG source %r failed: %s", source_name, e)
            continue
        if source_name != SOURCES[0][0]:
            log.warning("QRNG: served from fallback source %r", source_name)
        return _decode_values(raw, data_type)[:count]

    raise RuntimeError(
        "all QRNG sources failed: " + "; ".join(f"{name}={err}" for name, err in errors)
    )
