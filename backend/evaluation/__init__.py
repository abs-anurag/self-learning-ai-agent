"""
Evaluation package for scoring and metrics aggregation.

Source of truth: BLUEPRINT.md §12, §15, §18.
"""

from backend.evaluation.metrics import compute_user_metrics

__all__ = [
    "compute_user_metrics",
]
