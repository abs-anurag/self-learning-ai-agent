/**
 * WebSocket Live Event Streaming Client.
 * Member 2 Integration Boundary.
 *
 * Source of truth: BLUEPRINT.md §14, §16.
 *
 * Requirements:
 * - Connect to: /ws/tasks/{id}?api_key={key}&last_sequence={seq}
 * - Enforce monotonic sequence deduplication: discard any event where sequence <= last_seen_sequence.
 * - Code 1013 (Try Again Later): Buffer overflow during replay. Reconnect immediately with current last_seen_sequence.
 * - Code 1008 (Policy Violation): Missing/invalid API key or unowned task. Terminate connection without reconnect.
 * - Network disconnect: Exponential backoff reconnect.
 */

export function connectWebSocket({
	taskId,
	apiKey,
	initialSequence = 0,
	onEvent,
	onError,
	onClose,
}) {
	let lastSeenSequence = initialSequence
	let ws = null
	let reconnectTimer = null
	let backoffMs = 1000
	let isClosedIntentionally = false

	function connect() {
		if (isClosedIntentionally) return

		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
		const host = window.location.host
		const url = `${protocol}//${host}/ws/tasks/${taskId}?api_key=${encodeURIComponent(apiKey)}&last_sequence=${lastSeenSequence}`

		ws = new WebSocket(url)

		ws.onopen = () => {
			backoffMs = 1000
		}

		ws.onmessage = (message) => {
			try {
				const event = JSON.parse(message.data)
				// Enforce sequence deduplication per BLUEPRINT §14
				if (typeof event.sequence === 'number') {
					if (event.sequence <= lastSeenSequence) {
						return
					}
					lastSeenSequence = event.sequence
				}
				onEvent?.(event)
			} catch (err) {
				console.error('Failed to parse WebSocket event frame:', err)
			}
		}

		ws.onerror = (err) => {
			onError?.(err)
		}

		ws.onclose = (event) => {
			onClose?.(event)
			if (isClosedIntentionally) return

			if (event.code === 1013) {
				// Buffer overflow during replay: reconnect immediately with current lastSeenSequence
				reconnectTimer = setTimeout(connect, 500)
			} else if (event.code === 1008) {
				// Policy violation (unauthorized): do not retry
				console.warn('WebSocket connection terminated: Policy Violation (1008)')
			} else if (event.code !== 1000) {
				// Unexpected network drop: exponential backoff reconnect
				reconnectTimer = setTimeout(connect, backoffMs)
				backoffMs = Math.min(backoffMs * 2, 10000)
			}
		}
	}

	connect()

	return {
		close: () => {
			isClosedIntentionally = true
			if (reconnectTimer) clearTimeout(reconnectTimer)
			if (ws) ws.close(1000, 'Closed by user')
		},
		getLastSeenSequence: () => lastSeenSequence,
	}
}
