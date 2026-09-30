/**
 * Integration tests for src/mocks/mockEventStream.js
 *
 * Tests verify:
 *  - All 11 event types present across mock fixtures
 *  - Events are ordered by sequence (ascending)
 *  - Schema matches EventEnvelope structure (10 required fields)
 *  - Status vocabulary: only 'pending', 'running', 'succeeded', 'failed'
 *    (never 'completed')
 *  - playMockEvents() calls onEvent for each event in sequence order
 *  - stopMockEvents() halts playback before completion
 *  - isMockPlaybackActive() reflects playback state
 *  - Mock IDs are consistent (not real credentials)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  MOCK_EVENTS_RUN_A,
  MOCK_EVENTS_RUN_B,
  MOCK_EVENTS_FAILED,
  playMockEvents,
  stopMockEvents,
  isMockPlaybackActive,
  MOCK_TASK_IDS,
  MOCK_RUN_IDS,
} from '../mocks/mockEventStream.js';

// All 11 event types per BLUEPRINT.md §14
const ALL_EVENT_TYPES = [
  'task_started',
  'planning_started',
  'memory_retrieved',
  'tool_started',
  'tool_completed',
  'evaluation_completed',
  'reflection_completed',
  'learning_candidate_created',
  'learning_saved',
  'task_completed',
  'task_failed',
];

const VALID_STATUSES = new Set(['pending', 'running', 'succeeded', 'failed']);

// Required fields per BLUEPRINT.md §18 EventEnvelope
const REQUIRED_FIELDS = [
  'event_id',
  'task_id',
  'run_id',
  'user_id',
  'sequence',
  'schema_version',
  'timestamp',
  'event_type',
  'status',
  'metadata',
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getEventTypes(events) {
  return events.map((e) => e.event_type);
}

function isSortedBySequence(events) {
  for (let i = 1; i < events.length; i++) {
    if (events[i].sequence <= events[i - 1].sequence) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('mockEventStream.js — MOCK_EVENTS_RUN_A', () => {
  it('has at least one event', () => {
    expect(MOCK_EVENTS_RUN_A.length).toBeGreaterThan(0);
  });

  it('events are ordered by sequence (ascending)', () => {
    expect(isSortedBySequence(MOCK_EVENTS_RUN_A)).toBe(true);
  });

  it('all events have the 10 required EventEnvelope fields', () => {
    for (const evt of MOCK_EVENTS_RUN_A) {
      for (const field of REQUIRED_FIELDS) {
        expect(evt, `Event seq=${evt.sequence} missing field: ${field}`).toHaveProperty(field);
      }
    }
  });

  it('all event statuses are from the valid vocabulary (no "completed")', () => {
    for (const evt of MOCK_EVENTS_RUN_A) {
      expect(VALID_STATUSES.has(evt.status), `Invalid status "${evt.status}" in event seq=${evt.sequence}`).toBe(true);
    }
  });

  it('all event sequences are positive integers', () => {
    for (const evt of MOCK_EVENTS_RUN_A) {
      expect(Number.isInteger(evt.sequence)).toBe(true);
      expect(evt.sequence).toBeGreaterThan(0);
    }
  });

  it('sequences are unique', () => {
    const seqs = MOCK_EVENTS_RUN_A.map((e) => e.sequence);
    expect(new Set(seqs).size).toBe(seqs.length);
  });

  it('all events share the same task_id', () => {
    const ids = new Set(MOCK_EVENTS_RUN_A.map((e) => e.task_id));
    expect(ids.size).toBe(1);
  });

  it('contains task_started as the first event', () => {
    expect(MOCK_EVENTS_RUN_A[0].event_type).toBe('task_started');
  });

  it('contains task_completed as the last event', () => {
    const last = MOCK_EVENTS_RUN_A[MOCK_EVENTS_RUN_A.length - 1];
    expect(last.event_type).toBe('task_completed');
  });

  it('contains memory_retrieved event', () => {
    const types = getEventTypes(MOCK_EVENTS_RUN_A);
    expect(types).toContain('memory_retrieved');
  });

  it('contains learning_saved event (recipe promoted)', () => {
    const types = getEventTypes(MOCK_EVENTS_RUN_A);
    expect(types).toContain('learning_saved');
  });

  it('contains learning_candidate_created event', () => {
    const types = getEventTypes(MOCK_EVENTS_RUN_A);
    expect(types).toContain('learning_candidate_created');
  });

  it('contains reflection_completed event (multi-iteration run)', () => {
    const types = getEventTypes(MOCK_EVENTS_RUN_A);
    expect(types).toContain('reflection_completed');
  });
});

describe('mockEventStream.js — MOCK_EVENTS_RUN_B', () => {
  it('is ordered by sequence', () => {
    expect(isSortedBySequence(MOCK_EVENTS_RUN_B)).toBe(true);
  });

  it('all events have required fields', () => {
    for (const evt of MOCK_EVENTS_RUN_B) {
      for (const field of REQUIRED_FIELDS) {
        expect(evt).toHaveProperty(field);
      }
    }
  });

  it('memory_retrieved has hits = 1 (recipe retrieved)', () => {
    const memEvt = MOCK_EVENTS_RUN_B.find((e) => e.event_type === 'memory_retrieved');
    expect(memEvt).toBeDefined();
    expect(memEvt.metadata.hits).toBe(1);
  });

  it('does NOT contain learning_saved (duplicate recipe suppressed)', () => {
    const types = getEventTypes(MOCK_EVENTS_RUN_B);
    expect(types).not.toContain('learning_saved');
  });

  it('has a different task_id from Run A', () => {
    const runAId = MOCK_EVENTS_RUN_A[0].task_id;
    const runBId = MOCK_EVENTS_RUN_B[0].task_id;
    expect(runAId).not.toBe(runBId);
  });
});

describe('mockEventStream.js — MOCK_EVENTS_FAILED', () => {
  it('contains task_failed as the last event', () => {
    const last = MOCK_EVENTS_FAILED[MOCK_EVENTS_FAILED.length - 1];
    expect(last.event_type).toBe('task_failed');
  });

  it('last event has status "failed"', () => {
    const last = MOCK_EVENTS_FAILED[MOCK_EVENTS_FAILED.length - 1];
    expect(last.status).toBe('failed');
  });

  it('does NOT contain "completed" as a status value', () => {
    for (const evt of MOCK_EVENTS_FAILED) {
      expect(evt.status).not.toBe('completed');
    }
  });
});

describe('mockEventStream.js — all event types coverage', () => {
  it('collectively covers all 11 BLUEPRINT.md event types', () => {
    const allEvents = [...MOCK_EVENTS_RUN_A, ...MOCK_EVENTS_RUN_B, ...MOCK_EVENTS_FAILED];
    const presentTypes = new Set(allEvents.map((e) => e.event_type));
    for (const eventType of ALL_EVENT_TYPES) {
      expect(presentTypes.has(eventType), `Missing event type: ${eventType}`).toBe(true);
    }
  });
});

describe('mockEventStream.js — playMockEvents()', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    stopMockEvents();
  });

  afterEach(() => {
    stopMockEvents();
    vi.useRealTimers();
  });

  it('calls onEvent for each event in sequence order', async () => {
    const received = [];
    const testEvents = MOCK_EVENTS_RUN_A.slice(0, 3);

    playMockEvents({
      events: testEvents,
      intervalMs: 50,
      onEvent: (evt) => received.push(evt),
    });

    // Advance time past all events
    await vi.advanceTimersByTimeAsync(1000);

    expect(received).toHaveLength(3);
    // Verify sequence order
    expect(received[0].sequence).toBeLessThan(received[1].sequence);
    expect(received[1].sequence).toBeLessThan(received[2].sequence);
  });

  it('calls onComplete when all events have been delivered', async () => {
    const onComplete = vi.fn();
    const testEvents = MOCK_EVENTS_RUN_A.slice(0, 2);

    playMockEvents({
      events: testEvents,
      intervalMs: 50,
      onEvent: () => {},
      onComplete,
    });

    await vi.advanceTimersByTimeAsync(1000);
    expect(onComplete).toHaveBeenCalledOnce();
  });

  it('emits "connecting" then "connected" connection status', async () => {
    const statuses = [];

    playMockEvents({
      events: MOCK_EVENTS_RUN_A.slice(0, 1),
      intervalMs: 50,
      onEvent: () => {},
      onConnectionStatus: (s) => statuses.push(s),
    });

    await vi.advanceTimersByTimeAsync(500);
    expect(statuses).toContain('connecting');
    expect(statuses).toContain('connected');
  });

  it('isMockPlaybackActive() is true during playback and false after', async () => {
    playMockEvents({
      events: MOCK_EVENTS_RUN_A.slice(0, 2),
      intervalMs: 100,
      onEvent: () => {},
    });

    // Initially active
    expect(isMockPlaybackActive()).toBe(true);

    await vi.advanceTimersByTimeAsync(2000);

    // After completion
    expect(isMockPlaybackActive()).toBe(false);
  });
});

describe('mockEventStream.js — stopMockEvents()', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    stopMockEvents();
    vi.useRealTimers();
  });

  it('halts delivery before all events are sent', async () => {
    const received = [];
    const testEvents = MOCK_EVENTS_RUN_A.slice(0, 5);

    playMockEvents({
      events: testEvents,
      intervalMs: 200,
      onEvent: (evt) => received.push(evt),
    });

    // Advance enough for ~2 events, then stop
    await vi.advanceTimersByTimeAsync(500);
    stopMockEvents();

    const countAfterStop = received.length;
    await vi.advanceTimersByTimeAsync(5000); // Advance more — no new events should arrive

    expect(received.length).toBe(countAfterStop);
    expect(received.length).toBeLessThan(5);
  });

  it('isMockPlaybackActive() is false after stopMockEvents()', () => {
    playMockEvents({ events: MOCK_EVENTS_RUN_A, intervalMs: 100, onEvent: () => {} });
    stopMockEvents();
    expect(isMockPlaybackActive()).toBe(false);
  });
});

describe('mockEventStream.js — MOCK_TASK_IDS and MOCK_RUN_IDS', () => {
  it('exports MOCK_TASK_IDS with runA, runB, failed keys', () => {
    expect(MOCK_TASK_IDS).toHaveProperty('runA');
    expect(MOCK_TASK_IDS).toHaveProperty('runB');
    expect(MOCK_TASK_IDS).toHaveProperty('failed');
  });

  it('exports MOCK_RUN_IDS with runA, runB, failed keys', () => {
    expect(MOCK_RUN_IDS).toHaveProperty('runA');
    expect(MOCK_RUN_IDS).toHaveProperty('runB');
    expect(MOCK_RUN_IDS).toHaveProperty('failed');
  });
});
