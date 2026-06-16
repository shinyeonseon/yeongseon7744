"""Track and score past recommendations — does the system actually add alpha?

Records each run's recommendations to an append-only ledger, then scores them
against subsequent prices (forward returns at several horizons). No external
data: it reuses the candles the pipeline already fetches.
"""
