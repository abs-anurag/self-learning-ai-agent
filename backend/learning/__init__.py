"""
Learning subsystem for candidate extraction, quality gates, and recipe promotion.

Source of truth: BLUEPRINT.md §3, §7, §10, §11, §18.
"""

from backend.learning.candidate import (
    create_recipe_candidate,
    get_candidate_by_id,
    get_candidates_for_run,
    is_trivial_run,
    reject_candidate,
)
from backend.learning.quality_gate import (
    PROMOTION_SCORE_THRESHOLD,
    QualityGateResult,
    evaluate_quality_gate,
)
from backend.learning.recipes import (
    find_duplicate_recipe,
    get_recipe_by_id,
    get_trusted_recipes_for_user,
    promote_candidate,
    record_recipe_reuse_success,
)

__all__ = [
    "is_trivial_run",
    "create_recipe_candidate",
    "reject_candidate",
    "get_candidate_by_id",
    "get_candidates_for_run",
    "PROMOTION_SCORE_THRESHOLD",
    "QualityGateResult",
    "evaluate_quality_gate",
    "find_duplicate_recipe",
    "promote_candidate",
    "record_recipe_reuse_success",
    "get_trusted_recipes_for_user",
    "get_recipe_by_id",
]
