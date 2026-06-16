"""Market context layer: macro calendar/indicators, per-symbol news headlines,
and next earnings date. All sources are lazy-imported and fail soft (degrade to
empty), so the core pipeline never depends on them being reachable.
"""
