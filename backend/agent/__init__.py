"""
Agent core package containing state schemas, runtime, graph, and LLM provider abstractions.

Source of truth: BLUEPRINT.md §8, §9, §15.
"""

from backend.agent.graph import (
    build_agent_graph,
    create_agent_graph,
)
from backend.agent.providers import (
    AnthropicProvider,
    FixtureProvider,
    LLMProvider,
)
from backend.agent.runtime import (
    AgentRuntime,
    get_current_runtime,
    get_llm_provider,
)
from backend.agent.state import (
    DEFAULT_MAX_OBSERVATION_CHARS,
    TERMINAL_REASONS,
    VALID_LEARNING_DECISIONS,
    VALID_STATUSES,
    VALID_TASK_TYPES,
    AgentState,
    create_initial_state,
    route_after_evaluate,
    sanitize_state_update,
    truncate_observation,
    validate_agent_state,
)

__all__ = [
    "AgentState",
    "create_initial_state",
    "validate_agent_state",
    "sanitize_state_update",
    "truncate_observation",
    "route_after_evaluate",
    "AgentRuntime",
    "get_current_runtime",
    "LLMProvider",
    "AnthropicProvider",
    "FixtureProvider",
    "get_llm_provider",
    "build_agent_graph",
    "create_agent_graph",
    "VALID_TASK_TYPES",
    "VALID_LEARNING_DECISIONS",
    "VALID_STATUSES",
    "TERMINAL_REASONS",
    "DEFAULT_MAX_OBSERVATION_CHARS",
]
