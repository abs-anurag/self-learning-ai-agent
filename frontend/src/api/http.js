/**
 * HTTP Client Interface for FastAPI Backend.
 * Member 2 Integration Boundary.
 *
 * Source of truth: BLUEPRINT.md §14, §15, §17.
 * Endpoints:
 * - POST /tasks: Submit goal, returns { task_id, run_id, status: 'pending' }
 * - GET /tasks: Paginated task summaries
 * - GET /tasks/{id}: Task details and run history
 * - GET /tasks/{id}/result: 409 Conflict if pending/running; 200 OK with evaluation if terminal
 * - GET /tasks/{id}/events: HTTP replay fallback
 * - GET /memory/recipes: Paginated trusted recipes
 * - POST /tasks/{id}/feedback: Submit rating (1-5) and comment
 * - GET /metrics: 11-field closed-loop analytics
 * - GET /health: Operational readiness check
 */

const BASE_URL = ''

/**
 * Standard fetch wrapper attaching X-API-Key and parsing standard error format.
 */
export async function apiRequest(path, options = {}) {
	const apiKey = options.apiKey || localStorage.getItem('agent_api_key') || 'demo_key'
	const headers = {
		'Content-Type': 'application/json',
		'X-API-Key': apiKey,
		...(options.headers || {}),
	}

	const response = await fetch(`${BASE_URL}${path}`, {
		...options,
		headers,
	})

	if (!response.ok) {
		let errorPayload = null
		try {
			errorPayload = await response.json()
		} catch {
			errorPayload = { error: { code: 'HTTP_ERROR', message: response.statusText } }
		}
		throw errorPayload
	}

	return response.json()
}

export async function submitTask(goal, apiKey) {
	return apiRequest('/tasks', {
		method: 'POST',
		body: JSON.stringify({ goal }),
		apiKey,
	})
}

export async function getTasks(page = 1, pageSize = 20, apiKey) {
	return apiRequest(`/tasks?page=${page}&page_size=${pageSize}`, { apiKey })
}

export async function getTaskDetails(taskId, apiKey) {
	return apiRequest(`/tasks/${taskId}`, { apiKey })
}

export async function getTaskResult(taskId, apiKey) {
	return apiRequest(`/tasks/${taskId}/result`, { apiKey })
}

export async function getTaskEvents(taskId, afterSequence = 0, limit = 500, apiKey) {
	return apiRequest(`/tasks/${taskId}/events?after_sequence=${afterSequence}&limit=${limit}`, { apiKey })
}

export async function getRecipes(page = 1, pageSize = 20, apiKey) {
	return apiRequest(`/memory/recipes?page=${page}&page_size=${pageSize}`, { apiKey })
}

export async function submitFeedback(taskId, rating, comment, apiKey) {
	return apiRequest(`/tasks/${taskId}/feedback`, {
		method: 'POST',
		body: JSON.stringify({ rating, comment }),
		apiKey,
	})
}

export async function getMetrics(apiKey) {
	return apiRequest('/metrics', { apiKey })
}

export async function getHealth() {
	return apiRequest('/health')
}
