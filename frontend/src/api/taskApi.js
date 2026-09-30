/**
 * Task API — all REST operations for the Self-Learning AI Agent.
 *
 * Source of truth: BLUEPRINT.md §15 Endpoint Specifications.
 *
 * Endpoints implemented:
 *   POST   /tasks                        createTask
 *   GET    /tasks                        listTasks
 *   GET    /tasks/{id}                   getTask
 *   GET    /tasks/{id}/result            getTaskResult
 *   GET    /tasks/{id}/events            getTaskEvents
 *   GET    /memory/recipes               getRecipes
 *   POST   /tasks/{id}/feedback          submitFeedback
 *   GET    /metrics                      getMetrics
 *   GET    /health                       getHealth
 *
 * All functions return plain JS objects matching the BLUEPRINT.md response
 * schemas.  Errors are thrown as ApiError instances from http.js.
 *
 * Design rules:
 * - No fetch calls inside UI components; all API calls go through this module.
 * - No endpoint invention — only the 9 endpoints defined in BLUEPRINT.md §15.
 * - 409 on getTaskResult is NOT re-thrown — callers receive {_notComplete: true}.
 * - Do not log or expose API keys.
 */

import { get, post, ApiError } from './http.js';

// ---------------------------------------------------------------------------
// Task Operations
// ---------------------------------------------------------------------------

/**
 * Create a new agent task.
 *
 * @param {string} goal — The goal description for the agent.
 * @returns {Promise<{task_id: string, run_id: string, status: string}>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 POST /tasks
 * Request:  { goal: string }
 * Response: { task_id, run_id, status: "pending" }
 */
export async function createTask(goal) {
  return post('/tasks', { goal });
}

/**
 * List tasks owned by the authenticated user (paginated).
 *
 * @param {number} [page=1]         — Page number (1-based)
 * @param {number} [pageSize=20]    — Items per page (max 100)
 * @returns {Promise<{items: Array, page: number, page_size: number, total: number}>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 GET /tasks
 */
export async function listTasks(page = 1, pageSize = 20) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return get(`/tasks?${params}`);
}

/**
 * Get full task detail including run summaries.
 *
 * @param {string} taskId — UUID of the task
 * @returns {Promise<{task_id, goal, status, created_at, updated_at, runs: Array}>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 GET /tasks/{id}
 */
export async function getTask(taskId) {
  return get(`/tasks/${taskId}`);
}

/**
 * Get the terminal result for a completed task.
 *
 * Returns a special sentinel object when the task is not yet in a terminal
 * state (HTTP 409) rather than throwing, since callers commonly poll and
 * need to distinguish "not done yet" from genuine errors.
 *
 * @param {string} taskId — UUID of the task
 * @returns {Promise<
 *   | {task_id, run_id, status, final_response, evaluation}
 *   | {_notComplete: true, code: string, message: string}
 * >}
 * @throws {ApiError} — For any error other than 409 TASK_NOT_COMPLETE
 *
 * BLUEPRINT.md §15 GET /tasks/{id}/result
 * 409 Conflict is returned when task status is 'pending' or 'running'.
 */
export async function getTaskResult(taskId) {
  try {
    return await get(`/tasks/${taskId}/result`);
  } catch (err) {
    if (err instanceof ApiError && err.isTaskNotComplete()) {
      // Caller can check ._notComplete to distinguish "poll again" from error
      return {
        _notComplete: true,
        code: err.code,
        message: err.message,
      };
    }
    throw err;
  }
}

/**
 * Fetch historical events for a task run (HTTP replay fallback).
 *
 * Used as the fallback replay source when WebSocket reconnects or is
 * unavailable.  Events are ordered by sequence ASC.
 *
 * @param {string} taskId             — UUID of the task
 * @param {number} [afterSequence=0]  — Return only events with sequence > this value
 * @param {number} [limit=500]        — Max events to return (backend cap: 1000)
 * @returns {Promise<Array<EventEnvelope>>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 GET /tasks/{id}/events
 */
export async function getTaskEvents(taskId, afterSequence = 0, limit = 500) {
  const params = new URLSearchParams({
    after_sequence: String(afterSequence),
    limit: String(limit),
  });
  return get(`/tasks/${taskId}/events?${params}`);
}

// ---------------------------------------------------------------------------
// Memory / Recipe Operations
// ---------------------------------------------------------------------------

/**
 * List trusted recipes owned by the authenticated user (paginated).
 *
 * @param {number} [page=1]
 * @param {number} [pageSize=20]
 * @returns {Promise<{items: Array<RecipeItem>, page, page_size, total}>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 GET /memory/recipes
 */
export async function getRecipes(page = 1, pageSize = 20) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return get(`/memory/recipes?${params}`);
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

/**
 * Submit user feedback for a completed task.
 *
 * @param {string} taskId          — UUID of the task
 * @param {number} rating          — Integer 1–5
 * @param {string|null} [comment]  — Optional comment (max 2000 chars)
 * @returns {Promise<{feedback_id: string, status: string}>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 POST /tasks/{id}/feedback
 */
export async function submitFeedback(taskId, rating, comment = null) {
  const body = { rating };
  if (comment !== null && comment !== undefined) {
    body.comment = comment;
  }
  return post(`/tasks/${taskId}/feedback`, body);
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

/**
 * Get aggregate performance metrics for the authenticated user.
 *
 * @returns {Promise<MetricsResponse>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 GET /metrics
 * Fields: total_tasks, successful_tasks, failed_tasks, success_rate,
 *         average_iterations, average_tool_calls, recipes_promoted,
 *         recipe_retrieval_count, successful_reuses, average_judge_score,
 *         improvement_rate
 */
export async function getMetrics() {
  return get('/metrics');
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

/**
 * Check API and dependency health.
 *
 * @returns {Promise<{status: string, database: string, redis: string}>}
 * @throws {ApiError}
 *
 * BLUEPRINT.md §15 GET /health
 */
export async function getHealth() {
  return get('/health');
}

// ---------------------------------------------------------------------------
// Named export bundle (for convenience imports)
// ---------------------------------------------------------------------------

export const taskApi = {
  createTask,
  listTasks,
  getTask,
  getTaskResult,
  getTaskEvents,
  getRecipes,
  submitFeedback,
  getMetrics,
  getHealth,
};

export default taskApi;
