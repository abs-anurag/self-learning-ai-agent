"""
Quality Gate evaluation for candidate recipe promotion.

Source of truth: BLUEPRINT.md §3, §7, §11, §12, §22.

Promotion Gate Criteria (§7):
Trusted Recipe Promotion Threshold: LLM-as-judge >= 8.5 / 10.
Promotion requires ALL of:
1. task_success == True (canonical: deterministic pass, tool success, judge score >= 6.0, final answer present)
2. LLM judge score >= 8.5
3. deterministic_pass == True
4. tool_success == True
5. generalizable == True
6. Recipe schema validation passes and lesson/strategy are non-empty
7. Recipe is not a duplicate (similarity < RECIPE_DUPLICATE_THRESHOLD, default 0.90)

Learning Decisions (§7, §11):
- "promoted": passes all criteria and not a duplicate -> store in task_recipes & emit learning_saved.
- "skip": duplicate recipe (similarity >= RECIPE_DUPLICATE_THRESHOLD) or trivial run -> no trusted recipe stored.
- "candidate_only": gate checks fail -> preserve in recipe_candidates with status = 'rejected'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import RecipeCandidate, TaskRecipe
from backend.memory.embeddings import cosine_similarity

logger = get_logger(__name__)

PROMOTION_SCORE_THRESHOLD: Decimal = Decimal("8.5")


@dataclass
class QualityGateResult:
    """Outcome of Quality Gate validation."""
    passed: bool
    is_duplicate: bool
    learning_decision: str  # "promoted" | "candidate_only" | "skip"
    rejection_reasons: list[str] = field(default_factory=list)
    duplicate_recipe_id: Optional[str] = None
    similarity: float = 0.0


def evaluate_quality_gate(
    candidate: Union[RecipeCandidate, dict[str, Any]],
    *,
    task_success: bool,
    judge_score: Union[float, Decimal, int],
    deterministic_pass: bool,
    tool_success: bool,
    generalizable: bool,
    final_answer: Optional[str] = None,
    candidate_embedding: Optional[list[float]] = None,
    existing_recipes: Optional[list[TaskRecipe]] = None,
    duplicate_threshold: Optional[float] = None,
) -> QualityGateResult:
    """
    Evaluate candidate recipe against the 7 Promotion Gate Criteria (§7).
    """
    threshold = (
        duplicate_threshold
        if duplicate_threshold is not None
        else settings.RECIPE_DUPLICATE_THRESHOLD
    )
    reasons: list[str] = []

    # Score conversion to Decimal for precise comparison
    score_dec = (
        Decimal(str(judge_score))
        if not isinstance(judge_score, Decimal)
        else judge_score
    )

    # 1. Canonical task_success check (§7, §12)
    # task_success = deterministic_pass and tool_success and judge_score >= 6.0 and bool(final_answer)
    if not task_success:
        reasons.append("task_success is False")

    # 2. Judge score >= 8.5 threshold (§7, §11)
    if score_dec < PROMOTION_SCORE_THRESHOLD:
        reasons.append(f"judge_score {score_dec} is below promotion threshold {PROMOTION_SCORE_THRESHOLD}")

    # 3. Deterministic pass (§7)
    if not deterministic_pass:
        reasons.append("deterministic_pass is False")

    # 4. Tool success (§7)
    if not tool_success:
        reasons.append("tool_success is False")

    # 5. Generalizable (§7)
    if not generalizable:
        reasons.append("generalizable is False")

    # 6. Recipe schema validation (lesson and recommended_strategy non-empty)
    if isinstance(candidate, RecipeCandidate):
        lesson = candidate.lesson
        strategy = candidate.recommended_strategy
        problem_pattern = candidate.problem_pattern
    else:
        lesson = candidate.get("lesson", "")
        strategy = candidate.get("recommended_strategy", "")
        problem_pattern = candidate.get("problem_pattern", "")

    if not (lesson and lesson.strip()):
        reasons.append("Recipe schema validation failed: lesson is empty")
    if not (strategy and strategy.strip()):
        reasons.append("Recipe schema validation failed: recommended_strategy is empty")
    if not (problem_pattern and problem_pattern.strip()):
        reasons.append("Recipe schema validation failed: problem_pattern is empty")

    # Check if any of criteria 1-6 failed
    if reasons:
        logger.info("Quality gate rejected candidate: %s", ", ".join(reasons))
        return QualityGateResult(
            passed=False,
            is_duplicate=False,
            learning_decision="candidate_only",
            rejection_reasons=reasons,
        )

    # 7. Duplicate suppression check (§7, §10, §11)
    # Check against existing trusted recipes
    is_dup = False
    dup_id = None
    max_sim = 0.0

    if candidate_embedding is not None and existing_recipes:
        for ex_rec in existing_recipes:
            sim = cosine_similarity(ex_rec.embedding, candidate_embedding)
            if sim > max_sim:
                max_sim = sim
            if sim >= threshold:
                is_dup = True
                dup_id = str(ex_rec.id)
                break

    if is_dup:
        logger.info(
            "Quality gate suppressed duplicate recipe: similarity %.4f >= threshold %.2f (matches %s)",
            max_sim,
            threshold,
            dup_id,
        )
        return QualityGateResult(
            passed=True,
            is_duplicate=True,
            learning_decision="skip",
            rejection_reasons=[f"Duplicate recipe detected with similarity {max_sim:.4f} >= {threshold}"],
            duplicate_recipe_id=dup_id,
            similarity=max_sim,
        )

    logger.info("Quality gate approved candidate for promotion (score=%s)", score_dec)
    return QualityGateResult(
        passed=True,
        is_duplicate=False,
        learning_decision="promoted",
        rejection_reasons=[],
        similarity=max_sim,
    )
