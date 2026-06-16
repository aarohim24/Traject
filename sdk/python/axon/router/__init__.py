"""Adaptive model router for heuristic-based task classification and model selection.

Provides rule-based routing that classifies incoming LLM messages by task type,
estimates complexity, and maps each (task_type, complexity_tier) pair to the
cheapest qualifying model tier. Supports deterministic A/B traffic splitting
via ``ABTestConfig`` and integrates with the Axon instrumentor through the
``configure()`` entry point. No network calls are made; all routing decisions
are computed in-process in under 1 ms.
"""
