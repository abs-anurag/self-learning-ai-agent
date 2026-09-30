/**
 * Integration tests for src/store/agentStore.js
 *
 * Tests exercise the real Zustand store actions using mocked taskApi calls.
 * They do NOT mock away store logic — they test the store's state transitions.
 *
 * Coverage:
 *  - Initial state values
 *  - receiveEvent() adds events and updates latestSequence
 *  - receiveEvent() silently drops duplicate (sequence == latestSequence)
 *  - receiveEvent() silently drops stale event (sequence < latestSequence)
 *  - setConnectionStatus() updates connectionStatus and reconnecting
 *  - setReconnecting() updates flag independently
 *  - clearEvents() resets events and sequence
 *  - fetchTasks() populates tasks and pagination
 *  - fetchTasks() sets error on failure
 *  - createTask() prepends task stub to list
 *  - fetchTaskResult() handles _notComplete sentinel
 *  - submitFeedback() stores result
 *  - Error propagation — error normalized to plain object
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiError } from '../api/http.js';

// ---------------------------------------------------------------------------
// Mock taskApi — we test store logic, not API calls
// ---------------------------------------------------------------------------

vi.mock('../api/taskApi.js', () => ({
  taskApi: {
    listTasks: vi.fn(),
    getTask: vi.fn(),
    getTaskResult: vi.fn(),
    createTask: vi.fn(),
    getRecipes: vi.fn(),
    getMetrics: vi.fn(),
    getHealth: vi.fn(),
    submitFeedback: vi.fn(),
    getTaskEvents: vi.fn(),
  },
  default: {
    listTasks: vi.fn(),
    getTask: vi.fn(),
    getTaskResult: vi.fn(),
    createTask: vi.fn(),
    getRecipes: vi.fn(),
    getMetrics: vi.fn(),
    getHealth: vi.fn(),
    submitFeedback: vi.fn(),
    getTaskEvents: vi.fn(),
  },
}));

import { taskApi } from '../api/taskApi.js';

// Reset Zustand store between tests by re-importing fresh instance
// We use getState/setState to isolate test state
let useAgentStore;

beforeEach(async () => {
  vi.clearAllMocks();
  // Re-import store to get a fresh Zustand instance
  vi.resetModules();
  const mod = await import('../store/agentStore.js');
  useAgentStore = mod.useAgentStore;
  // Reset to initial state
  useAgentStore.getState().clearEvents();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('agentStore.js — eventSlice', () => {

  describe('Initial state', () => {
    it('starts with empty events array', () => {
      expect(useAgentStore.getState().events).toEqual([]);
    });

    it('starts with latestSequence = 0', () => {
      expect(useAgentStore.getState().latestSequence).toBe(0);
    });

    it('starts with connectionStatus = "disconnected"', () => {
      expect(useAgentStore.getState().connectionStatus).toBe('disconnected');
    });

    it('starts with reconnecting = false', () => {
      expect(useAgentStore.getState().reconnecting).toBe(false);
    });
  });

  describe('receiveEvent()', () => {
    function makeEnvelope(sequence) {
      return {
        event_id: `evt-${sequence}`,
        task_id: 'task-001',
        run_id: 'run-001',
        user_id: 'user-001',
        sequence,
        schema_version: '1.0',
        timestamp: new Date().toISOString(),
        event_type: 'task_started',
        status: 'running',
        metadata: {},
      };
    }

    it('adds valid event to events array', () => {
      useAgentStore.getState().receiveEvent(makeEnvelope(1));
      expect(useAgentStore.getState().events).toHaveLength(1);
      expect(useAgentStore.getState().events[0].sequence).toBe(1);
    });

    it('updates latestSequence on new event', () => {
      [1, 2, 3, 4, 5].forEach((sequence) => useAgentStore.getState().receiveEvent(makeEnvelope(sequence)));
      expect(useAgentStore.getState().latestSequence).toBe(5);
    });

    it('drops duplicate event (sequence == latestSequence)', () => {
      useAgentStore.getState().receiveEvent(makeEnvelope(1));
      useAgentStore.getState().receiveEvent(makeEnvelope(2));
      useAgentStore.getState().receiveEvent(makeEnvelope(3));
      useAgentStore.getState().receiveEvent(makeEnvelope(3)); // duplicate
      expect(useAgentStore.getState().events).toHaveLength(3);
    });

    it('does not advance latestSequence on duplicate', () => {
      [1, 2, 3].forEach((sequence) => useAgentStore.getState().receiveEvent(makeEnvelope(sequence)));
      const seqBefore = useAgentStore.getState().latestSequence;
      useAgentStore.getState().receiveEvent(makeEnvelope(3));
      expect(useAgentStore.getState().latestSequence).toBe(seqBefore);
    });

    it('drops stale event (sequence < latestSequence)', () => {
      for (let sequence = 1; sequence <= 10; sequence += 1) {
        useAgentStore.getState().receiveEvent(makeEnvelope(sequence));
      }
      useAgentStore.getState().receiveEvent(makeEnvelope(7)); // stale
      expect(useAgentStore.getState().events).toHaveLength(10);
      expect(useAgentStore.getState().latestSequence).toBe(10);
    });

    it('rejects gaps without advancing the replay cursor', () => {
      useAgentStore.getState().receiveEvent(makeEnvelope(1));
      const applied = useAgentStore.getState().receiveEvent(makeEnvelope(3));

      expect(applied).toBe(false);
      expect(useAgentStore.getState().events.map((event) => event.sequence)).toEqual([1]);
      expect(useAgentStore.getState().latestSequence).toBe(1);
    });

    it('accepts and appends multiple sequential events', () => {
      [1, 2, 3].forEach((seq) => useAgentStore.getState().receiveEvent(makeEnvelope(seq)));
      expect(useAgentStore.getState().events).toHaveLength(3);
      expect(useAgentStore.getState().latestSequence).toBe(3);
    });

    it('synchronizes current task status from lifecycle events', () => {
      useAgentStore.getState().setCurrentTask({ task_id: 'task-001', status: 'pending' });
      useAgentStore.getState().receiveEvent({ ...makeEnvelope(1), event_type: 'task_started' });
      useAgentStore.getState().receiveEvent({ ...makeEnvelope(2), event_type: 'task_completed', status: 'succeeded' });

      expect(useAgentStore.getState().currentTask.status).toBe('succeeded');
    });

    it('synchronizes task failure status from task_failed', () => {
      useAgentStore.getState().setCurrentTask({ task_id: 'task-001', status: 'running' });
      useAgentStore.getState().receiveEvent({ ...makeEnvelope(1), event_type: 'task_failed', status: 'failed' });

      expect(useAgentStore.getState().currentTask.status).toBe('failed');
    });

    it('ignores event with non-numeric sequence', () => {
      useAgentStore.getState().receiveEvent({ sequence: 'bad', event_type: 'task_started' });
      expect(useAgentStore.getState().events).toHaveLength(0);
    });
  });

  describe('setConnectionStatus()', () => {
    it('updates connectionStatus', () => {
      useAgentStore.getState().setConnectionStatus('connected');
      expect(useAgentStore.getState().connectionStatus).toBe('connected');
    });

    it('sets reconnecting = true when status is "reconnecting"', () => {
      useAgentStore.getState().setConnectionStatus('reconnecting');
      expect(useAgentStore.getState().reconnecting).toBe(true);
    });

    it('sets reconnecting = false when status is "connected"', () => {
      useAgentStore.getState().setConnectionStatus('reconnecting');
      useAgentStore.getState().setConnectionStatus('connected');
      expect(useAgentStore.getState().reconnecting).toBe(false);
    });
  });

  describe('setReconnecting()', () => {
    it('updates reconnecting flag', () => {
      useAgentStore.getState().setReconnecting(true);
      expect(useAgentStore.getState().reconnecting).toBe(true);
      useAgentStore.getState().setReconnecting(false);
      expect(useAgentStore.getState().reconnecting).toBe(false);
    });
  });

  describe('clearEvents()', () => {
    it('resets events to empty array', () => {
      useAgentStore.getState().receiveEvent({ sequence: 1, event_type: 'task_started', metadata: {} });
      useAgentStore.getState().clearEvents();
      expect(useAgentStore.getState().events).toEqual([]);
    });

    it('resets latestSequence to 0', () => {
      useAgentStore.getState().receiveEvent({ sequence: 1, event_type: 'task_started', metadata: {} });
      useAgentStore.getState().clearEvents();
      expect(useAgentStore.getState().latestSequence).toBe(0);
    });

    it('resets connectionStatus to disconnected', () => {
      useAgentStore.getState().setConnectionStatus('connected');
      useAgentStore.getState().clearEvents();
      expect(useAgentStore.getState().connectionStatus).toBe('disconnected');
    });
  });
});

describe('agentStore.js — taskSlice', () => {
  it('fetchTasks() populates tasks and pagination', async () => {
    taskApi.listTasks.mockResolvedValue({
      items: [{ task_id: 'abc', goal: 'Test', status: 'succeeded' }],
      page: 1,
      page_size: 20,
      total: 1,
    });

    await useAgentStore.getState().fetchTasks();

    expect(useAgentStore.getState().tasks).toHaveLength(1);
    expect(useAgentStore.getState().tasks[0].task_id).toBe('abc');
    expect(useAgentStore.getState().tasksPagination.total).toBe(1);
    expect(useAgentStore.getState().tasksLoading).toBe(false);
  });

  it('fetchTasks() sets tasksError on API failure', async () => {
    taskApi.listTasks.mockRejectedValue(
      new ApiError('INTERNAL_SERVER_ERROR', 'Server error.', 500)
    );

    await useAgentStore.getState().fetchTasks();

    expect(useAgentStore.getState().tasksError).toBeTruthy();
    expect(useAgentStore.getState().tasksError.code).toBe('INTERNAL_SERVER_ERROR');
    expect(useAgentStore.getState().tasksLoading).toBe(false);
  });

  it('createTask() prepends task stub to tasks list', async () => {
    taskApi.createTask.mockResolvedValue({ task_id: 'new-task', run_id: 'new-run', status: 'pending' });

    await useAgentStore.getState().createTask('My new goal');

    const tasks = useAgentStore.getState().tasks;
    expect(tasks[0].task_id).toBe('new-task');
    expect(tasks[0].status).toBe('pending');
    expect(tasks[0].goal).toBe('My new goal');
  });
});

describe('agentStore.js — resultSlice', () => {
  it('fetchTaskResult() stores result on success', async () => {
    taskApi.getTaskResult.mockResolvedValue({
      task_id: 'abc',
      run_id: 'xyz',
      status: 'succeeded',
      final_response: 'The answer is 42.',
    });

    await useAgentStore.getState().fetchTaskResult('abc');

    expect(useAgentStore.getState().taskResult?.final_response).toBe('The answer is 42.');
    expect(useAgentStore.getState().taskResultLoading).toBe(false);
  });

  it('fetchTaskResult() leaves taskResult null on _notComplete sentinel', async () => {
    taskApi.getTaskResult.mockResolvedValue({ _notComplete: true });

    await useAgentStore.getState().fetchTaskResult('abc');

    expect(useAgentStore.getState().taskResult).toBeNull();
  });
});

describe('agentStore.js — metricsSlice', () => {
  it('fetchMetrics() populates metrics', async () => {
    taskApi.getMetrics.mockResolvedValue({
      total_tasks: 10,
      success_rate: 0.9,
      improvement_rate: 0.5,
    });

    await useAgentStore.getState().fetchMetrics();

    expect(useAgentStore.getState().metrics?.total_tasks).toBe(10);
    expect(useAgentStore.getState().metricsLoading).toBe(false);
  });

  it('fetchMetrics() sets metricsError on failure', async () => {
    taskApi.getMetrics.mockRejectedValue(new ApiError('UNAUTHORIZED', 'Bad key.', 401));

    await useAgentStore.getState().fetchMetrics();

    expect(useAgentStore.getState().metricsError?.status).toBe(401);
  });
});

describe('agentStore.js — feedbackSlice', () => {
  it('submitFeedback() stores result', async () => {
    taskApi.submitFeedback.mockResolvedValue({ feedback_id: 'fb-001', status: 'recorded' });

    await useAgentStore.getState().submitFeedback('task-001', 5, 'Great!');

    expect(useAgentStore.getState().feedbackResult?.status).toBe('recorded');
    expect(useAgentStore.getState().feedbackLoading).toBe(false);
  });

  it('submitFeedback() sets feedbackError on failure', async () => {
    taskApi.submitFeedback.mockRejectedValue(new ApiError('NOT_FOUND', 'Task not found.', 404));

    await expect(useAgentStore.getState().submitFeedback('task-x', 3)).rejects.toThrow();
    expect(useAgentStore.getState().feedbackError?.status).toBe(404);
  });
});
