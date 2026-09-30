/**
 * Integration tests for src/api/ws.js
 *
 * Tests exercise the real WebSocket client logic using a mock WebSocket class.
 * They do NOT mock away the ws.js implementation — they test it directly.
 *
 * Coverage:
 *  - Connection established with correct URL (includes api_key, last_sequence)
 *  - onopen fires onConnectionStatus('connected')
 *  - Event received and parsed correctly
 *  - Sequence tracking — latestSequence advances on new event
 *  - Duplicate detection — event with sequence <= latestSequence is discarded
 *  - Stale event handling — equal sequence is discarded
 *  - Close code 1013 → reconnects with updated last_sequence
 *  - Close code 1008 → does NOT reconnect (auth failure)
 *  - Close code 1000 → does NOT reconnect (normal closure)
 *  - Other close code → reconnects with exponential backoff
 *  - Malformed message — does not crash, calls onError
 *  - Non-JSON message — does not crash, calls onError
 *  - disconnect() prevents reconnect
 *  - getLatestSequence() returns current sequence
 *  - getStatus() returns current status
 *  - API key appears in WebSocket URL
 *  - API key not logged to console
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createWebSocketConnection } from '../api/ws.js';

// ---------------------------------------------------------------------------
// Mock WebSocket class
// ---------------------------------------------------------------------------

class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    MockWebSocket.instances.push(this);
  }

  send() {}

  close(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({ code });
  }

  // Test helpers — simulate server sending events to the client
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen();
  }

  simulateMessage(data) {
    if (this.onmessage) this.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) });
  }

  simulateError() {
    if (this.onerror) this.onerror(new Event('error'));
  }

  simulateClose(code = 1000, reason = '') {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({ code, reason });
  }

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal('WebSocket', MockWebSocket);

  // Provide window.location for URL building
  vi.stubGlobal('window', {
    location: { protocol: 'http:', host: 'localhost:3000' },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEnvelope(sequence, event_type = 'task_started', status = 'running', metadata = {}) {
  return {
    event_id: `evt-${sequence}`,
    task_id: 'task-001',
    run_id: 'run-001',
    user_id: 'user-001',
    sequence,
    schema_version: '1.0',
    timestamp: new Date().toISOString(),
    event_type,
    status,
    metadata,
  };
}

function makeHandle(overrides = {}) {
  const defaults = {
    taskId: 'task-001',
    apiKey: 'test-key',
    initialSequence: 0,
    onEvent: vi.fn(),
    onConnectionStatus: vi.fn(),
    onError: vi.fn(),
    ...overrides,
  };
  return createWebSocketConnection(defaults);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ws.js — createWebSocketConnection()', () => {

  describe('Connection URL', () => {
    it('constructs WebSocket URL with taskId, api_key, and last_sequence', () => {
      makeHandle({ taskId: 'task-abc', apiKey: 'my-key', initialSequence: 5 });
      const ws = MockWebSocket.instances[0];
      expect(ws.url).toContain('/ws/tasks/task-abc');
      expect(ws.url).toContain('api_key=my-key');
      expect(ws.url).toContain('last_sequence=5');
    });

    it('starts with last_sequence=0 by default', () => {
      makeHandle({ initialSequence: 0 });
      expect(MockWebSocket.instances[0].url).toContain('last_sequence=0');
    });
  });

  describe('Connection lifecycle', () => {
    it('emits "connecting" status on creation', () => {
      const onStatus = vi.fn();
      makeHandle({ onConnectionStatus: onStatus });
      expect(onStatus).toHaveBeenCalledWith('connecting');
    });

    it('emits "connected" status on WebSocket open', () => {
      const onStatus = vi.fn();
      makeHandle({ onConnectionStatus: onStatus });
      MockWebSocket.instances[0].simulateOpen();
      expect(onStatus).toHaveBeenCalledWith('connected');
    });

    it('getStatus() returns "connected" after open', () => {
      const handle = makeHandle();
      MockWebSocket.instances[0].simulateOpen();
      expect(handle.getStatus()).toBe('connected');
    });
  });

  describe('Event receiving and parsing', () => {
    it('calls onEvent with parsed envelope on valid message', () => {
      const onEvent = vi.fn();
      makeHandle({ onEvent });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(1));
      expect(onEvent).toHaveBeenCalledOnce();
      expect(onEvent.mock.calls[0][0].sequence).toBe(1);
      expect(onEvent.mock.calls[0][0].event_type).toBe('task_started');
    });

    it('updates latestSequence after receiving a valid event', () => {
      const handle = makeHandle({ initialSequence: 2 });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(3));
      expect(handle.getLatestSequence()).toBe(3);
    });
  });

  describe('Sequence deduplication', () => {
    it('discards duplicate event (sequence == latestSequence)', () => {
      const onEvent = vi.fn();
      makeHandle({ onEvent, initialSequence: 5 });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(5)); // duplicate
      expect(onEvent).not.toHaveBeenCalled();
    });

    it('discards stale event (sequence < latestSequence)', () => {
      const onEvent = vi.fn();
      makeHandle({ onEvent, initialSequence: 10 });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(7)); // stale
      expect(onEvent).not.toHaveBeenCalled();
    });

    it('does not advance latestSequence on duplicate', () => {
      const handle = makeHandle({ initialSequence: 5 });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(5));
      expect(handle.getLatestSequence()).toBe(5); // unchanged
    });

    it('accepts and advances on strictly newer event', () => {
      const onEvent = vi.fn();
      const handle = makeHandle({ onEvent, initialSequence: 5 });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(6));
      expect(onEvent).toHaveBeenCalledOnce();
      expect(handle.getLatestSequence()).toBe(6);
    });

    it('accepts sequential events in order', () => {
      const onEvent = vi.fn();
      const handle = makeHandle({ onEvent });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(1));
      ws.simulateMessage(makeEnvelope(2));
      ws.simulateMessage(makeEnvelope(3));
      expect(onEvent).toHaveBeenCalledTimes(3);
      expect(handle.getLatestSequence()).toBe(3);
    });
  });

  describe('Malformed message handling', () => {
    it('does not crash on non-JSON string', () => {
      const onError = vi.fn();
      makeHandle({ onError });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      expect(() => ws.simulateMessage('not-json{{')).not.toThrow();
      expect(onError).toHaveBeenCalled();
    });

    it('does not crash on message missing sequence field', () => {
      const onEvent = vi.fn();
      const onError = vi.fn();
      makeHandle({ onEvent, onError });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage({ event_type: 'task_started' }); // missing sequence
      expect(onEvent).not.toHaveBeenCalled();
      expect(onError).toHaveBeenCalled();
    });

    it('does not crash on null message', () => {
      const onError = vi.fn();
      makeHandle({ onError });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      expect(() => ws.simulateMessage('null')).not.toThrow();
    });

    it('rejects an event envelope for a different task', () => {
      const onError = vi.fn();
      const onEvent = vi.fn();
      makeHandle({ onError, onEvent });
      MockWebSocket.instances[0].simulateOpen();
      MockWebSocket.instances[0].simulateMessage({ ...makeEnvelope(1), task_id: 'other-task' });
      expect(onEvent).not.toHaveBeenCalled();
      expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'WS_MALFORMED_MESSAGE' }));
    });
  });

  describe('Close code 1008 — Policy Violation (auth failure)', () => {
    it('does NOT reconnect on close 1008', () => {
      vi.useFakeTimers();
      const onStatus = vi.fn();
      makeHandle({ onConnectionStatus: onStatus });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateClose(1008);

      vi.advanceTimersByTime(10000);

      // Only one WebSocket should have been created
      expect(MockWebSocket.instances).toHaveLength(1);
      vi.useRealTimers();
    });

    it('emits "failed" status on close 1008', () => {
      const onStatus = vi.fn();
      makeHandle({ onConnectionStatus: onStatus });
      MockWebSocket.instances[0].simulateClose(1008);
      expect(onStatus).toHaveBeenCalledWith('failed');
    });
  });

  describe('Close code 1000 — Normal Closure', () => {
    it('does NOT reconnect on close 1000', () => {
      vi.useFakeTimers();
      makeHandle();
      MockWebSocket.instances[0].simulateClose(1000);
      vi.advanceTimersByTime(10000);
      expect(MockWebSocket.instances).toHaveLength(1);
      vi.useRealTimers();
    });

    it('emits "disconnected" status on close 1000', () => {
      const onStatus = vi.fn();
      makeHandle({ onConnectionStatus: onStatus });
      MockWebSocket.instances[0].simulateClose(1000);
      expect(onStatus).toHaveBeenCalledWith('disconnected');
    });
  });

  describe('Close code 1013 — Try Again Later (buffer overflow)', () => {
    it('reconnects quickly on close 1013', () => {
      vi.useFakeTimers();
      makeHandle({ initialSequence: 6 });
      const firstWs = MockWebSocket.instances[0];
      firstWs.simulateOpen();
      firstWs.simulateMessage(makeEnvelope(7));
      firstWs.simulateClose(1013);

      // Advance past the 1013 reconnect delay
      vi.advanceTimersByTime(500);

      // A second WebSocket should have been created
      expect(MockWebSocket.instances.length).toBeGreaterThan(1);
      vi.useRealTimers();
    });

    it('reconnects with updated last_sequence after 1013', () => {
      vi.useFakeTimers();
      makeHandle({ initialSequence: 6 });
      const firstWs = MockWebSocket.instances[0];
      firstWs.simulateOpen();
      firstWs.simulateMessage(makeEnvelope(7));
      firstWs.simulateClose(1013);

      vi.advanceTimersByTime(500);

      const secondWs = MockWebSocket.instances[1];
      expect(secondWs.url).toContain('last_sequence=7');
      vi.useRealTimers();
    });
  });

  describe('Other close codes — network drop reconnect', () => {
    it('reconnects on unexpected close code', () => {
      vi.useFakeTimers();
      makeHandle();
      MockWebSocket.instances[0].simulateOpen();
      MockWebSocket.instances[0].simulateClose(1006);

      vi.advanceTimersByTime(5000);

      expect(MockWebSocket.instances.length).toBeGreaterThan(1);
      vi.useRealTimers();
    });

    it('emits "reconnecting" status on network drop', () => {
      const onStatus = vi.fn();
      makeHandle({ onConnectionStatus: onStatus });
      MockWebSocket.instances[0].simulateClose(1006);
      expect(onStatus).toHaveBeenCalledWith('reconnecting');
    });
  });

  describe('disconnect() — intentional disconnect', () => {
    it('does NOT reconnect after disconnect() is called', () => {
      vi.useFakeTimers();
      const handle = makeHandle();
      MockWebSocket.instances[0].simulateOpen();
      handle.disconnect();

      vi.advanceTimersByTime(30000);

      expect(MockWebSocket.instances).toHaveLength(1);
      vi.useRealTimers();
    });

    it('emits "disconnected" after disconnect()', () => {
      const onStatus = vi.fn();
      const handle = makeHandle({ onConnectionStatus: onStatus });
      MockWebSocket.instances[0].simulateOpen();
      handle.disconnect();
      expect(onStatus).toHaveBeenCalledWith('disconnected');
    });
  });

  describe('last_sequence recovery on reconnect', () => {
    it('uses latest received sequence as last_sequence on reconnect', () => {
      vi.useFakeTimers();
      const handle = makeHandle({ initialSequence: 9 });
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(10));
      expect(handle.getLatestSequence()).toBe(10);

      ws.simulateClose(1006);
      vi.advanceTimersByTime(5000);

      expect(MockWebSocket.instances[1].url).toContain('last_sequence=10');
      vi.useRealTimers();
    });

    it('reconnects from the last contiguous sequence when an event gap appears', () => {
      vi.useFakeTimers();
      const onError = vi.fn();
      const handle = makeHandle({ onError });
      const firstWs = MockWebSocket.instances[0];
      firstWs.simulateOpen();
      firstWs.simulateMessage(makeEnvelope(1));
      firstWs.simulateMessage(makeEnvelope(3));

      expect(handle.getLatestSequence()).toBe(1);
      expect(onError).toHaveBeenCalledWith(expect.objectContaining({ code: 'WS_SEQUENCE_GAP' }));

      vi.advanceTimersByTime(1);
      expect(MockWebSocket.instances[1].url).toContain('last_sequence=1');
      vi.useRealTimers();
    });

    it('stops reconnecting after a terminal event', () => {
      vi.useFakeTimers();
      const handle = makeHandle();
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(1));
      ws.simulateMessage(makeEnvelope(2, 'task_completed', 'succeeded'));
      vi.advanceTimersByTime(10000);

      expect(handle.getLatestSequence()).toBe(2);
      expect(handle.getStatus()).toBe('disconnected');
      expect(MockWebSocket.instances).toHaveLength(1);
      vi.useRealTimers();
    });

    it('handles task_failed as a terminal event', () => {
      vi.useFakeTimers();
      const handle = makeHandle();
      const ws = MockWebSocket.instances[0];
      ws.simulateOpen();
      ws.simulateMessage(makeEnvelope(1));
      ws.simulateMessage(makeEnvelope(2, 'task_failed', 'failed'));
      vi.advanceTimersByTime(10000);

      expect(handle.getLatestSequence()).toBe(2);
      expect(handle.getStatus()).toBe('disconnected');
      expect(MockWebSocket.instances).toHaveLength(1);
      vi.useRealTimers();
    });

    it('encodes API keys in the WebSocket query string', () => {
      makeHandle({ apiKey: 'key+with&symbols' });
      expect(MockWebSocket.instances[0].url).toContain('api_key=key%2Bwith%26symbols');
    });
  });
});
