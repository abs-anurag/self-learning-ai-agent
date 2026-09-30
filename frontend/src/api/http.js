/**
 * Core HTTP client for the Self-Learning AI Agent API.
 *
 * Source of truth: BLUEPRINT.md §15 (Endpoint Specifications),
 *                  §17 (Security — X-API-Key, never log credentials).
 *
 * Design rules:
 * - Authentication via X-API-Key header on every request.
 * - API key read from import.meta.env.VITE_API_KEY — never hard-coded.
 * - The API key is NEVER logged in any console output.
 * - Base URL from import.meta.env.VITE_API_BASE_URL (defaults to '/api',
 *   which the Vite and production Nginx proxies rewrite to the bare API routes).
 * - All errors are normalised to ApiError instances with code, message,
 *   status, and requestId fields matching BLUEPRINT.md §15 error format.
 * - Network failures and malformed JSON are both surfaced as ApiError.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * API base URL.  In dev the Vite proxy rewrites /api → http://localhost:8000.
 * In production the Nginx container serves the built assets and proxies /api.
 * Override by setting VITE_API_BASE_URL in your .env.local.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '');

/**
 * Retrieve the API key from environment.
 * The plaintext key is never stored in code or committed to source control.
 * Set VITE_API_KEY in .env.local (gitignored).
 */
export function getApiKey() {
  return import.meta.env.VITE_API_KEY ?? '';
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/**
 * Structured error surfaced from every failed API call.
 * Matches BLUEPRINT.md §15 Standard API Error Response Format.
 */
export class ApiError extends Error {
  /**
   * @param {string} code     — Machine-readable error code (e.g. "TASK_NOT_FOUND")
   * @param {string} message  — Human-readable description
   * @param {number} status   — HTTP status code (0 = network failure)
   * @param {string} requestId — Server-assigned request tracing ID (may be '')
   */
  constructor(code, message, status, requestId = '') {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }

  /** Returns true for 409 TASK_NOT_COMPLETE — callers may handle this specially. */
  isTaskNotComplete() {
    return this.status === 409 && this.code === 'TASK_NOT_COMPLETE';
  }

  /** Returns true for any 4xx client error. */
  isClientError() {
    return this.status >= 400 && this.status < 500;
  }

  /** Returns true for any 5xx server error. */
  isServerError() {
    return this.status >= 500;
  }

  /** Returns true for network failures (status 0). */
  isNetworkError() {
    return this.status === 0;
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Parse a response body attempting JSON first.
 * If the body is not valid JSON returns null without throwing.
 *
 * @param {Response} response
 * @returns {Promise<object|null>}
 */
async function tryParseJson(response) {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Build an ApiError from a non-2xx Response.
 * Attempts to extract the BLUEPRINT.md §15 error envelope:
 *   { "error": { "code": str, "message": str, "request_id": str } }
 *
 * @param {Response} response
 * @returns {Promise<ApiError>}
 */
async function buildApiError(response) {
  const body = await tryParseJson(response);

  if (body && body.error && typeof body.error === 'object') {
    const { code = 'UNKNOWN_ERROR', message = 'An error occurred.', request_id = '' } = body.error;
    return new ApiError(String(code), String(message), response.status, String(request_id));
  }

  // Fallback for non-standard error shapes
  const fallbackMessage = body?.detail
    ? String(body.detail)
    : `HTTP ${response.status} ${response.statusText}`;

  const codeMap = {
    400: 'BAD_REQUEST',
    401: 'UNAUTHORIZED',
    403: 'FORBIDDEN',
    404: 'NOT_FOUND',
    409: 'CONFLICT',
    422: 'VALIDATION_ERROR',
    429: 'RATE_LIMIT_EXCEEDED',
    500: 'INTERNAL_SERVER_ERROR',
  };
  const code = codeMap[response.status] ?? 'HTTP_ERROR';
  return new ApiError(code, fallbackMessage, response.status);
}

// ---------------------------------------------------------------------------
// Core request function
// ---------------------------------------------------------------------------

/**
 * Perform an authenticated HTTP request to the backend API.
 *
 * @param {'GET'|'POST'|'PUT'|'PATCH'|'DELETE'} method
 * @param {string} path        — URL path, e.g. '/tasks' or '/tasks/123/result'
 * @param {object|null} [body] — JSON-serialisable request body (optional)
 * @param {object} [options]   — Extra fetch options (e.g. signal for AbortController)
 * @returns {Promise<object>}  — Parsed JSON response body
 * @throws {ApiError}          — On HTTP errors, network failures, or malformed JSON
 */
export async function request(method, path, body = null, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  const apiKey = getApiKey();

  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  };

  // Attach API key header if present.
  // SECURITY: never log apiKey.
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }

  const fetchOptions = {
    ...options,
    method,
    headers: { ...options.headers, ...headers },
  };

  if (body !== null && body !== undefined) {
    fetchOptions.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, fetchOptions);
  } catch (networkError) {
    // Covers DNS failures, connection refused, etc.
    throw new ApiError(
      'NETWORK_ERROR',
      'Network request failed. Check your connection and try again.',
      0
    );
  }

  if (!response.ok) {
    throw await buildApiError(response);
  }

  // Parse successful JSON response
  const data = await tryParseJson(response);
  if (data === null && response.status !== 204) {
    // Response was 2xx but body is not JSON — surface a structured error
    throw new ApiError(
      'MALFORMED_RESPONSE',
      'Server returned a non-JSON response.',
      response.status
    );
  }

  return data ?? {};
}

// ---------------------------------------------------------------------------
// Convenience method shortcuts
// ---------------------------------------------------------------------------

/** Authenticated GET request. */
export const get = (path, options) => request('GET', path, null, options);

/** Authenticated POST request with JSON body. */
export const post = (path, body, options) => request('POST', path, body, options);

/** Authenticated PATCH request with JSON body. */
export const patch = (path, body, options) => request('PATCH', path, body, options);

/** Authenticated DELETE request. */
export const del = (path, options) => request('DELETE', path, null, options);
