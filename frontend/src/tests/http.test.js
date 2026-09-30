/**
 * Integration tests for src/api/http.js
 *
 * Tests exercise the real http.js module logic using mocked fetch().
 * They do NOT mock away the http.js implementation — they test it directly.
 *
 * Coverage:
 *  - Request construction (method, URL, headers)
 *  - X-API-Key authentication header included
 *  - API key never logged (spy on console)
 *  - Successful JSON response parsing
 *  - 4xx error parsing (standard BLUEPRINT.md §15 error envelope)
 *  - 5xx error handling
 *  - Malformed JSON response handling
 *  - Network failure handling
 *  - ApiError properties (code, status, requestId, helpers)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { request, get, post, ApiError } from '../api/http.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetchResponse(status, body, contentType = 'application/json') {
  const bodyStr = typeof body === 'string' ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    headers: {
      get: (name) => (name.toLowerCase() === 'content-type' ? contentType : null),
    },
    json: async () => JSON.parse(bodyStr),
    text: async () => bodyStr,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('http.js — request()', () => {
  let consoleSpy;

  beforeEach(() => {
    // Spy on console to verify API key is never logged
    consoleSpy = {
      log: vi.spyOn(console, 'log').mockImplementation(() => {}),
      warn: vi.spyOn(console, 'warn').mockImplementation(() => {}),
      error: vi.spyOn(console, 'error').mockImplementation(() => {}),
    };
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- Request construction ------------------------------------------------

  it('sends GET request to the correct URL', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(200, { ok: true })
    );

    await get('/tasks');

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/tasks');
  });

  it('sends POST request with JSON body', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(201, { task_id: 'abc', run_id: 'def', status: 'pending' })
    );

    await post('/tasks', { goal: 'Test goal' });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.method).toBe('POST');
    expect(options.body).toBe(JSON.stringify({ goal: 'Test goal' }));
  });

  it('includes Content-Type: application/json header', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(200, {})
    );

    await get('/health');

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers['Content-Type']).toBe('application/json');
  });

  it('includes Accept: application/json header', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(200, {})
    );

    await get('/health');

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers['Accept']).toBe('application/json');
  });

  it('includes X-API-Key header when VITE_API_KEY is set', async () => {
    vi.stubEnv('VITE_API_KEY', 'test-api-key-value');
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(200, {})
    );

    await get('/tasks');

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers['X-API-Key']).toBe('test-api-key-value');
    vi.unstubAllEnvs();
  });

  it('preserves authentication when callers supply additional fetch headers', async () => {
    vi.stubEnv('VITE_API_KEY', 'test-api-key-value');
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(mockFetchResponse(200, {}));

    await get('/health', { headers: { 'X-Request-Tag': 'frontend' } });

    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({
      'X-API-Key': 'test-api-key-value',
      'X-Request-Tag': 'frontend',
    });
  });

  // ---- Security: API key must not be logged --------------------------------

  it('never logs the API key to console', async () => {
    vi.stubEnv('VITE_API_KEY', 'super-secret-key-12345');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(mockFetchResponse(200, {}));

    await get('/tasks');

    const loggedStrings = [
      ...consoleSpy.log.mock.calls.flat(),
      ...consoleSpy.warn.mock.calls.flat(),
      ...consoleSpy.error.mock.calls.flat(),
    ].map(String);

    for (const str of loggedStrings) {
      expect(str).not.toContain('super-secret-key-12345');
    }

    vi.unstubAllEnvs();
  });

  // ---- Successful response parsing ----------------------------------------

  it('parses and returns JSON on 200 OK', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(200, { task_id: 'abc-123', status: 'pending' })
    );

    const result = await get('/tasks/abc-123');
    expect(result).toEqual({ task_id: 'abc-123', status: 'pending' });
  });

  it('returns empty object for 204 No Content', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      headers: { get: () => null },
      json: async () => { throw new Error('No body'); },
      text: async () => '',
    });

    const result = await get('/something');
    expect(result).toEqual({});
  });

  // ---- HTTP error handling -------------------------------------------------

  it('throws ApiError with correct fields on 404', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(404, {
        error: {
          code: 'TASK_NOT_FOUND',
          message: 'Task not found.',
          request_id: 'req_abc123',
        },
      })
    );

    await expect(get('/tasks/nonexistent')).rejects.toThrow(ApiError);

    try {
      await get('/tasks/nonexistent');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.code).toBe('TASK_NOT_FOUND');
      expect(err.message).toBe('Task not found.');
      expect(err.status).toBe(404);
      expect(err.requestId).toBe('req_abc123');
      expect(err.isClientError()).toBe(true);
      expect(err.isServerError()).toBe(false);
      expect(err.isNetworkError()).toBe(false);
    }
  });

  it('throws ApiError on 401 Unauthorized', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(401, {
        error: { code: 'UNAUTHORIZED', message: 'Missing or invalid API key.', request_id: '' },
      })
    );

    await expect(get('/tasks')).rejects.toThrow(ApiError);
    try {
      await get('/tasks');
    } catch (err) {
      expect(err.status).toBe(401);
      expect(err.code).toBe('UNAUTHORIZED');
    }
  });

  it('throws ApiError on 409 TASK_NOT_COMPLETE with isTaskNotComplete() true', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(409, {
        error: {
          code: 'TASK_NOT_COMPLETE',
          message: 'The task has not reached a terminal state.',
          request_id: 'req_xyz',
        },
      })
    );

    try {
      await get('/tasks/abc/result');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.isTaskNotComplete()).toBe(true);
      expect(err.status).toBe(409);
    }
  });

  it('throws ApiError on 500 Internal Server Error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(500, {
        error: { code: 'INTERNAL_SERVER_ERROR', message: 'An unexpected error occurred.', request_id: '' },
      })
    );

    try {
      await get('/tasks');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(500);
      expect(err.isServerError()).toBe(true);
      expect(err.isClientError()).toBe(false);
    }
  });

  // ---- Malformed response --------------------------------------------------

  it('throws ApiError on malformed (non-JSON) 200 response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: { get: () => 'text/html' }, // Not JSON
      json: async () => { throw new Error('Not JSON'); },
      text: async () => '<html>Error</html>',
    });

    await expect(get('/tasks')).rejects.toThrow(ApiError);
    try {
      await get('/tasks');
    } catch (err) {
      expect(err.code).toBe('MALFORMED_RESPONSE');
    }
  });

  // ---- Network failure -----------------------------------------------------

  it('throws ApiError with NETWORK_ERROR on fetch() rejection', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(get('/tasks')).rejects.toThrow(ApiError);
    try {
      await get('/tasks');
    } catch (err) {
      expect(err.code).toBe('NETWORK_ERROR');
      expect(err.status).toBe(0);
      expect(err.isNetworkError()).toBe(true);
    }
  });

  it('throws ApiError with NETWORK_ERROR on connection refused', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('net::ERR_CONNECTION_REFUSED'));

    try {
      await get('/tasks');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.code).toBe('NETWORK_ERROR');
    }
  });

  // ---- Fallback error parsing ----------------------------------------------

  it('falls back to HTTP status-based error code when error envelope is missing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(403, { detail: 'Forbidden' })
    );

    try {
      await get('/tasks/other-user');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(403);
      // Falls back to code map
      expect(err.code).toBe('FORBIDDEN');
    }
  });
});
