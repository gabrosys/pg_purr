"""pg_purr.qrng: Quantum Random Number Generator client and entropy pool filler.

Fetches quantum random numbers from an ordered chain of HTTP sources
(LfD OTH Regensburg primary, NIST Randomness Beacon fallback) and
manages a PostgreSQL-side entropy pool for high-throughput consumption.
"""
