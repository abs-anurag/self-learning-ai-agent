/**
 * Integration tests for src/api/taskApi.js
 *
 * Tests exercise the real taskApi.js module logic using mocked http.js functions.
 * They verify that taskApi calls the correct endpoints with correct parameters.
 *
 * Coverage:
 *  - createTask sends correct goal body
 *  - listTasks sends pagination query params
 *  - getTask calls correct endpoint
 *  - getTaskResult returns sentinel { _notComplete: true } on 409
 *  - getTaskResult propagates other errors
 *  - getTaskEvents sends after_sequence and limit params
 *  - getRecipes sends pagination params
 *  - submitFeedback sends rating + comment
 *  - getMetrics calls /metrics
 *  - getHealth calls /health
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiError } from '../api/http.js';

// ---------------------------------------------------------------------------
// Mock the http.js module — we test taskApi's usage of http, not http itself
// (http.js is tested separately in http.test.js)
// ---------------------------------------------------------------------------

vi.mock('../api/http.js', async (importOriginal) => {
  const original = await importOriginal();
  return {
    ...original,
    get: vi.fn(),
    post: vi.fn(),
    ApiError: original.ApiError,
  };
});

import { get, post } from '../api/http.js';
import {
  createTask,
  listTasks,
  getTask,
  getTaskResult,
  getTaskEvents,
  getRecipes,
  submitFeedback,
  getMetrics,
  getHealth,
} from '../api/taskApi.js';

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('taskApi.js', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ---- createTask ----------------------------------------------------------

  describe('createTask()', () => {
    it('calls POST /tasks with correct goal body', async () => {
      post.mockResolvedValue({ task_id: 'abc', run_id: 'def', status: 'pending' });

      const result = await createTask('Calculate compound interest');

      expect(post).toHaveBeenCalledOnce();
      expect(post).toHaveBeenCalledWith('/tasks', { goal: 'Calculate compound interest' });
      expect(result.status).toBe('pending');
    });

    it('propagates ApiError from http.js', async () => {
      post.mockRejectedValue(new ApiError('RATE_LIMIT_EXCEEDED', 'Rate limited.', 429));

      await expect(createTask('test')).rejects.toThrow(ApiError);
    });
  });

  // ---- listTasks -----------------------------------------------------------

  describe('listTasks()', () => {
    it('calls GET /tasks with default pagination params', async () => {
      get.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });

      await listTasks();

      expect(get).toHaveBeenCalledOnce();
      const [url] = get.mock.calls[0];
      expect(url).toContain('page=1');
      expect(url).toContain('page_size=20');
    });

    it('calls GET /tasks with custom pagination params', async () => {
      get.mockResolvedValue({ items: [], page: 3, page_size: 50, total: 120 });

      await listTasks(3, 50);

      const [url] = get.mock.calls[0];
      expect(url).toContain('page=3');
      expect(url).toContain('page_size=50');
    });
  });

  // ---- getTask -------------------------------------------------------------

  describe('getTask()', () => {
    it('calls GET /tasks/{id} with the task ID', async () => {
      const taskData = { task_id: 'task-xyz', goal: 'test', status: 'succeeded', runs: [] };
      get.mockResolvedValue(taskData);

      const result = await getTask('task-xyz');

      expect(get).toHaveBeenCalledWith('/tasks/task-xyz');
      expect(result.task_id).toBe('task-xyz');
    });
  });

  // ---- getTaskResult -------------------------------------------------------

  describe('getTaskResult()', () => {
    it('returns result data on 200 OK', async () => {
      const resultData = {
        task_id: 'task-abc',
        run_id: 'run-abc',
        status: 'succeeded',
        final_response: 'The answer is 42.',
        evaluation: { task_success: true, judge_score: 9.0 },
      };
      get.mockResolvedValue(resultData);

      const result = await getTaskResult('task-abc');
      expect(result.status).toBe('succeeded');
      expect(result.final_response).toBe('The answer is 42.');
    });

    it('returns sentinel { _notComplete: true } on 409 TASK_NOT_COMPLETE', async () => {
      get.mockRejectedValue(new ApiError('TASK_NOT_COMPLETE', 'Not done.', 409));

      const result = await getTaskResult('task-pending');

      // Should NOT throw — returns sentinel instead
      expect(result._notComplete).toBe(true);
      expect(result.code).toBe('TASK_NOT_COMPLETE');
    });

    it('propagates non-409 ApiError', async () => {
      get.mockRejectedValue(new ApiError('TASK_NOT_FOUND', 'Task not found.', 404));

      await expect(getTaskResult('task-nonexistent')).rejects.toThrow(ApiError);
    });

    it('calls GET /tasks/{id}/result', async () => {
      get.mockResolvedValue({ task_id: 'x', status: 'succeeded' });
      await getTaskResult('my-task-id');
      expect(get).toHaveBeenCalledWith('/tasks/my-task-id/result');
    });
  });

  // ---- getTaskEvents -------------------------------------------------------

  describe('getTaskEvents()', () => {
    it('calls GET /tasks/{id}/events with default params', async () => {
      get.mockResolvedValue([]);

      await getTaskEvents('task-789');

      const [url] = get.mock.calls[0];
      expect(url).toContain('/tasks/task-789/events');
      expect(url).toContain('after_sequence=0');
      expect(url).toContain('limit=500');
    });

    it('sends custom after_sequence and limit', async () => {
      get.mockResolvedValue([]);

      await getTaskEvents('task-789', 42, 100);

      const [url] = get.mock.calls[0];
      expect(url).toContain('after_sequence=42');
      expect(url).toContain('limit=100');
    });
  });

  // ---- getRecipes ----------------------------------------------------------

  describe('getRecipes()', () => {
    it('calls GET /memory/recipes with pagination', async () => {
      get.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });

      await getRecipes(2, 10);

      const [url] = get.mock.calls[0];
      expect(url).toContain('/memory/recipes');
      expect(url).toContain('page=2');
      expect(url).toContain('page_size=10');
    });
  });

  // ---- submitFeedback ------------------------------------------------------

  describe('submitFeedback()', () => {
    it('calls POST /tasks/{id}/feedback with rating', async () => {
      post.mockResolvedValue({ feedback_id: 'fb-001', status: 'recorded' });

      await submitFeedback('task-001', 5, 'Great!');

      expect(post).toHaveBeenCalledWith('/tasks/task-001/feedback', {
        rating: 5,
        comment: 'Great!',
      });
    });

    it('omits comment when null', async () => {
      post.mockResolvedValue({ feedback_id: 'fb-002', status: 'recorded' });

      await submitFeedback('task-001', 4, null);

      const [, body] = post.mock.calls[0];
      expect(body).not.toHaveProperty('comment');
      expect(body.rating).toBe(4);
    });
  });

  // ---- getMetrics ----------------------------------------------------------

  describe('getMetrics()', () => {
    it('calls GET /metrics', async () => {
      get.mockResolvedValue({ total_tasks: 5, success_rate: 0.8 });

      const result = await getMetrics();

      expect(get).toHaveBeenCalledWith('/metrics');
      expect(result.total_tasks).toBe(5);
    });
  });

  // ---- getHealth -----------------------------------------------------------

  describe('getHealth()', () => {
    it('calls GET /health and returns status', async () => {
      get.mockResolvedValue({ status: 'ok', database: 'connected', redis: 'connected' });

      const result = await getHealth();

      expect(get).toHaveBeenCalledWith('/health');
      expect(result.status).toBe('ok');
      expect(result.database).toBe('connected');
    });
  });
});
