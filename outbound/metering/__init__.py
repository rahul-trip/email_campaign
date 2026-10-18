"""Metering: the cache, spend caps and cost ledger that every paid call passes through.

It sits above ``providers`` (it wraps their ports) and ``db`` (it records in the ledger) and
below ``stages``, which receive the wrapped providers and never see the ledger.
"""
