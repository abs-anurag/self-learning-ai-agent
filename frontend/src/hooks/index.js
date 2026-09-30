/**
 * Hooks barrel export — single import point for Frontend Member 1.
 *
 * Usage:
 *   import { useTask, useTaskEvents, useTaskList } from '../hooks'
 *
 * All hooks source their data from the Zustand store (agentStore.js)
 * which is backed by the REST API client (taskApi.js) and WebSocket
 * client (ws.js).
 *
 * Available hooks:
 *   useTask(taskId)           — Single task detail (GET /tasks/{id})
 *   useTaskList(options)      — Paginated task list (GET /tasks)
 *   useTaskResult(taskId)     — Terminal result (GET /tasks/{id}/result)
 *   useTaskEvents(taskId)     — Real-time events (WS /ws/tasks/{id})
 *   useRecipes(options)       — Trusted recipe list (GET /memory/recipes)
 *   useMetrics(options)       — Aggregate metrics (GET /metrics)
 *   useHealth(options)        — Health check (GET /health)
 *   useFeedback(taskId)       — Feedback submission (POST /tasks/{id}/feedback)
 */

export { useTask } from './useTask.js';
export { useTaskList, useTaskList as useTasks } from './useTaskList.js';
export { useTaskResult } from './useTaskResult.js';
export { useTaskEvents } from './useTaskEvents.js';
export { useRecipes } from './useRecipes.js';
export { useMetrics } from './useMetrics.js';
export { useHealth } from './useHealth.js';
export { useFeedback, useTaskFeedback } from './useFeedback.js';
