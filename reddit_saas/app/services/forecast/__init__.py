"""Forecast & Reporting Layer — service package.

5-layer truth-separated architecture:
    Layer 1 — Observed Reality Collector (validated measurements)
    Layer 2 — Execution Intent Snapshot (planned actions)
    Layer 3 — Forecasting Engine (S-curve projection)
    Layer 4 — Report Composer (structured JSONB composition)
    Layer 5 — Business Impact Calculator (ROI framing)

Key invariant: Observed ≠ Projected. Never conflated.
"""
