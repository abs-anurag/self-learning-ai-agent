import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/taskApi.js', () => ({
  taskApi: {
    listTasks: vi.fn(),
    getTask: vi.fn(),
    getTaskResult: vi.fn(),
    createTask: vi.fn(),
    getTaskEvents: vi.fn(),
    getRecipes: vi.fn(),
    submitFeedback: vi.fn(),
    getMetrics: vi.fn(),
    getHealth: vi.fn(),
  },
  default: {},
}));

vi.mock('../api/ws.js', () => ({
  createWebSocketConnection: vi.fn(() => ({ disconnect: vi.fn() })),
}));

import { useTask } from '../hooks/useTask.js';
import { useTaskEvents } from '../hooks/useTaskEvents.js';
import { taskApi } from '../api/taskApi.js';
import { useAgentStore } from '../store/agentStore.js';

describe('React data hooks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentStore.getState().clearEvents();
  });

  it('does not rerender a task hook for unrelated store updates', () => {
    let renderCount = 0;
    renderHook(() => {
      renderCount += 1;
      return useTask(null);
    });

    const initialRenderCount = renderCount;
    act(() => useAgentStore.setState({ metricsLoading: true }));

    expect(renderCount).toBe(initialRenderCount);
  });

  it('creates a task through the task hook and updates shared task state', async () => {
    taskApi.createTask.mockResolvedValue({ task_id: 'task-created', run_id: 'run-created', status: 'pending' });
    const { result } = renderHook(() => useTask(null));

    await act(async () => {
      await result.current.create('Calculate 2 + 2');
    });

    expect(useAgentStore.getState().currentTask).toMatchObject({
      task_id: 'task-created',
      run_id: 'run-created',
      goal: 'Calculate 2 + 2',
      status: 'pending',
    });
  });

  it('replays durable task events in order through the REST fallback', async () => {
    taskApi.getTaskEvents.mockResolvedValue([
      {
        event_id: 'event-1',
        task_id: 'task-1',
        run_id: 'run-1',
        user_id: 'user-1',
        sequence: 1,
        schema_version: '1.0',
        timestamp: '2026-09-30T00:00:00Z',
        event_type: 'task_started',
        status: 'running',
        metadata: {},
      },
    ]);

    const { result } = renderHook(() => useTaskEvents('task-1'));
    let replaySucceeded;
    await act(async () => {
      replaySucceeded = await result.current.replayEvents();
    });

    expect(replaySucceeded).toBe(true);
    expect(taskApi.getTaskEvents).toHaveBeenCalledWith('task-1', 0, 1000);
    expect(useAgentStore.getState().events.map((event) => event.sequence)).toEqual([1]);
    expect(result.current.latestSequence).toBe(1);
    expect(result.current.error).toMatchObject({ code: 'MISSING_API_KEY' });
    expect(result.current.replayLoading).toBe(false);

    act(() => useAgentStore.getState().setWsError({ code: 'WS_ERROR', message: 'Connection failed.' }));
    expect(result.current.error).toEqual({ code: 'WS_ERROR', message: 'Connection failed.' });
  });
});