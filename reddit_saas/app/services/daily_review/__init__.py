"""Daily Operations Review — service package.

Architecture (per engineering guidelines):
    SignalCollector (SQL only)
    → ReviewAnalysisEngine (rules + optional LLM)
    → DecisionTracker
    → IntelligenceReportGenerator

Phase 1: SignalCollector + snapshot creation only.
"""
