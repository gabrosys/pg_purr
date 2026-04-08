"""Unit tests for the entropy filler daemon."""

from unittest.mock import MagicMock, patch

import pytest

from pg_purr.qrng import entropy_filler


class FakeConn:
    def __init__(self, pool_size: int = 0):
        self._pool_size = pool_size
        self.inserted: list = []
        self.closed = False

    def cursor(self):
        cur = MagicMock()
        cur.fetchone.return_value = (self._pool_size,)
        return cur

    def commit(self):
        pass

    def close(self):
        self.closed = True


def test_fill_noop_when_above_threshold():
    conn = FakeConn(pool_size=1000)
    with patch("pg_purr.qrng.entropy_filler.fetch_quantum_random") as fetch:
        inserted = entropy_filler.fill_entropy_pool(conn, target=500, threshold=500)
    assert inserted == 0
    fetch.assert_not_called()


def test_fill_inserts_difference():
    conn = FakeConn(pool_size=100)
    with patch(
        "pg_purr.qrng.entropy_filler.fetch_quantum_random",
        return_value=list(range(400)),
    ):
        with patch("pg_purr.qrng.entropy_filler.execute_values") as execute:
            inserted = entropy_filler.fill_entropy_pool(conn, target=500, threshold=500)
    assert inserted == 400
    execute.assert_called_once()


def test_run_forever_backoff_on_error():
    sleeps: list[float] = []
    call_count = {"n": 0}

    def conn_factory():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RuntimeError("DB down")
        raise StopIteration()

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise SystemExit(0)

    with pytest.raises(SystemExit):
        entropy_filler.run_forever(
            conn_factory=conn_factory,
            poll_interval_s=1.0,
            backoff_max_s=8.0,
            sleep=fake_sleep,
        )

    # First failure sleeps at poll_interval_s, then doubles.
    assert sleeps[0] == 1.0
