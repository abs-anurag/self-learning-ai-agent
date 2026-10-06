import { useEffect, useRef, useState } from 'react'
import { MessageSquareText, Mic, MicOff, VolumeX } from 'lucide-react'
import metisLogo from '../assets/metis-logo.jpeg'
import ParticleTether from './originkit/ui/particle-tether'
import { useAgentStore } from '../store/agentStore'

const VOICE_STATE_LABELS = {
	IDLE: 'Ready',
	LISTENING: 'Listening...',
	PROCESSING: 'Processing...',
	THINKING: 'Thinking...',
	SPEAKING: 'Speaking...',
	SUCCESS: 'Response ready',
	ERROR: 'Voice unavailable',
}

const RECOGNITION_ERRORS = {
	'aborted': 'Voice recognition was stopped.',
	'audio-capture': 'No microphone was found.',
	'network': 'The voice recognition service is unavailable.',
	'no-speech': 'No speech detected. Tap the microphone to try again.',
	'not-allowed': 'Microphone access was denied.',
	'service-not-allowed': 'Microphone access was denied.',
}

function recognitionConstructor() {
	if (typeof window === 'undefined') return null
	return window.SpeechRecognition || window.webkitSpeechRecognition || null
}

function getAssistantMessageCount(task) {
	return task?.messages?.filter((message) => message.role === 'assistant').length || 0
}

export default function VoiceMode({ active, onExit, onSubmitTranscript, onTypeMessage }) {
	const { activeTask, playback, status, events } = useAgentStore()
	const [voiceState, setVoiceState] = useState('IDLE')
	const [transcript, setTranscript] = useState('')
	const [interimTranscript, setInterimTranscript] = useState('')
	const [response, setResponse] = useState('')
	const [voiceError, setVoiceError] = useState('')
	const [voices, setVoices] = useState([])
	const microphoneRef = useRef(null)
	const recognitionRef = useRef(null)
	const utteranceRef = useRef(null)
	const voiceStateRef = useRef('IDLE')
	const ignoreRecognitionRef = useRef(false)
	const submittedRecognitionRef = useRef(false)
	const awaitingResponseRef = useRef(false)
	const assistantBaselineRef = useRef(0)

	const recognitionSupported = Boolean(recognitionConstructor())
	const latestAssistantMessage = activeTask?.messages?.filter((message) => message.role === 'assistant').at(-1)
	const assistantMessageCount = getAssistantMessageCount(activeTask)

	const changeVoiceState = (nextState) => {
		voiceStateRef.current = nextState
		setVoiceState(nextState)
	}

	useEffect(() => {
		if (!active) return undefined
		const frame = window.requestAnimationFrame(() => microphoneRef.current?.focus())
		return () => window.cancelAnimationFrame(frame)
	}, [active])

	useEffect(() => {
		const synthesis = window.speechSynthesis
		if (!synthesis) return undefined

		const updateVoices = () => setVoices(synthesis.getVoices())
		updateVoices()
		if (typeof synthesis.addEventListener === 'function') {
			synthesis.addEventListener('voiceschanged', updateVoices)
			return () => synthesis.removeEventListener('voiceschanged', updateVoices)
		}

		const previousHandler = synthesis.onvoiceschanged
		synthesis.onvoiceschanged = updateVoices
		return () => {
			if (synthesis.onvoiceschanged === updateVoices) synthesis.onvoiceschanged = previousHandler
		}
	}, [])

	useEffect(() => {
		if (active && !recognitionSupported) {
			setVoiceError("Voice recognition isn't supported in this browser. Use Chrome/Edge or type your message instead.")
			changeVoiceState('ERROR')
		}
	}, [active, recognitionSupported])

	useEffect(() => {
		if (active && playback.active && !awaitingResponseRef.current) {
			changeVoiceState(events.some((event) => event.event_type === 'evaluation_completed') ? 'THINKING' : 'PROCESSING')
		}
	}, [active, playback.active, events])

	useEffect(() => {
		if (!active || !awaitingResponseRef.current) return
		if (playback.active) {
			changeVoiceState(events.some((event) => event.event_type === 'evaluation_completed') ? 'THINKING' : 'PROCESSING')
			return
		}
		if (assistantMessageCount <= assistantBaselineRef.current || !latestAssistantMessage?.content) return

		awaitingResponseRef.current = false
		setResponse(latestAssistantMessage.content)
		setInterimTranscript('')
		if (status === 'failed') {
			speakResponse(latestAssistantMessage.content)
			return
		}
		speakResponse(latestAssistantMessage.content)
	}, [active, assistantMessageCount, latestAssistantMessage?.content, playback.active, events, status])

	useEffect(() => {
		if (active) return undefined
		cancelVoiceWork()
		changeVoiceState('IDLE')
		return undefined
	}, [active])

	useEffect(() => () => cancelVoiceWork(), [])

	function speakResponse(text) {
		const synthesis = window.speechSynthesis
		if (!synthesis || typeof window.SpeechSynthesisUtterance !== 'function') {
			setVoiceError('Speech output is not available in this browser. The response is shown above.')
			changeVoiceState('SUCCESS')
			return
		}

		synthesis.cancel()
		const utterance = new window.SpeechSynthesisUtterance(text)
		const language = navigator.language || 'en-US'
		const languagePrefix = language.split('-')[0].toLowerCase()
		const matchingVoices = voices.filter((voice) => voice.lang?.toLowerCase().startsWith(languagePrefix))
		utterance.lang = language
		utterance.voice = matchingVoices.find((voice) => voice.default) || matchingVoices[0] || voices.find((voice) => voice.default) || voices[0] || null
		utterance.onstart = () => {
			if (utteranceRef.current !== utterance) return
			setVoiceError('')
			changeVoiceState('SPEAKING')
		}
		utterance.onend = () => {
			if (utteranceRef.current !== utterance) return
			utteranceRef.current = null
			changeVoiceState('IDLE')
		}
		utterance.onerror = () => {
			if (utteranceRef.current !== utterance) return
			utteranceRef.current = null
			setVoiceError('Speech output could not be played. You can read the response above.')
			changeVoiceState('ERROR')
		}
		utteranceRef.current = utterance
		synthesis.speak(utterance)
	}

	function cancelVoiceWork() {
		ignoreRecognitionRef.current = true
		const recognition = recognitionRef.current
		recognitionRef.current = null
		if (recognition) {
			try {
				recognition.abort()
			} catch {
				// Recognition may already have ended.
			}
		}

		const utterance = utteranceRef.current
		utteranceRef.current = null
		if (utterance && window.speechSynthesis) window.speechSynthesis.cancel()
		awaitingResponseRef.current = false
	}

	function stopListening() {
		ignoreRecognitionRef.current = true
		submittedRecognitionRef.current = true
		const recognition = recognitionRef.current
		recognitionRef.current = null
		if (recognition) {
			try {
				recognition.abort()
			} catch {
				// Recognition may already have ended.
			}
		}
		setInterimTranscript('')
		changeVoiceState('IDLE')
	}

	function stopSpeaking() {
		const utterance = utteranceRef.current
		utteranceRef.current = null
		if (utterance && window.speechSynthesis) window.speechSynthesis.cancel()
		changeVoiceState('IDLE')
	}

	function handleRecognitionError(error) {
		if (ignoreRecognitionRef.current || error === 'aborted') {
			changeVoiceState('IDLE')
			return
		}
		setVoiceError(RECOGNITION_ERRORS[error] || 'Voice recognition stopped unexpectedly. Tap the microphone to try again.')
		changeVoiceState('ERROR')
	}

	function startListening() {
		const Recognition = recognitionConstructor()
		if (!Recognition) {
			setVoiceError("Voice recognition isn't supported in this browser. Use Chrome/Edge or type your message instead.")
			changeVoiceState('ERROR')
			return
		}
		if (recognitionRef.current || playback.active) return

		setVoiceError('')
		setTranscript('')
		setInterimTranscript('')
		setResponse('')
		ignoreRecognitionRef.current = false
		submittedRecognitionRef.current = false

		let recognition
		try {
			recognition = new Recognition()
		} catch {
			setVoiceError("Voice recognition isn't available in this browser. Use Chrome/Edge or type your message instead.")
			changeVoiceState('ERROR')
			return
		}

		recognition.lang = navigator.language || 'en-US'
		recognition.continuous = false
		recognition.interimResults = true
		recognition.maxAlternatives = 1
		recognition.onstart = () => changeVoiceState('LISTENING')
		recognition.onresult = (event) => {
			if (ignoreRecognitionRef.current || submittedRecognitionRef.current) return
			const finalTranscript = Array.from(event.results)
				.filter((result) => result.isFinal)
				.map((result) => result[0]?.transcript || '')
				.join(' ')
				.trim()
			const interim = Array.from(event.results)
				.filter((result) => !result.isFinal)
				.map((result) => result[0]?.transcript || '')
				.join(' ')
				.trim()
			setInterimTranscript(interim)
			if (!finalTranscript) return

			submittedRecognitionRef.current = true
			setTranscript(finalTranscript)
			setInterimTranscript('')
			changeVoiceState('PROCESSING')
			assistantBaselineRef.current = getAssistantMessageCount(useAgentStore.getState().activeTask)
			awaitingResponseRef.current = true
			try {
				onSubmitTranscript(finalTranscript)
			} catch {
				awaitingResponseRef.current = false
				setVoiceError('METIS could not start this request. Please try again or type your message.')
				changeVoiceState('ERROR')
			}
			try {
				recognition.stop()
			} catch {
				// Recognition may already be stopping after its final result.
			}
		}
		recognition.onerror = (event) => {
			if (recognitionRef.current === recognition) recognitionRef.current = null
			handleRecognitionError(event.error)
		}
		recognition.onend = () => {
			if (recognitionRef.current === recognition) recognitionRef.current = null
			if (ignoreRecognitionRef.current || awaitingResponseRef.current || submittedRecognitionRef.current) return
			if (voiceStateRef.current !== 'LISTENING') return
			setVoiceError('Voice recognition stopped unexpectedly. Tap the microphone to try again.')
			changeVoiceState('ERROR')
		}
		recognitionRef.current = recognition
		changeVoiceState('LISTENING')
		try {
			recognition.start()
		} catch (error) {
			recognitionRef.current = null
			setVoiceError(error?.name === 'NotAllowedError'
				? 'Microphone access was denied.'
				: 'Voice recognition could not start. Check microphone access and try again.')
			changeVoiceState('ERROR')
		}
	}

	function handleMicrophoneClick() {
		if (voiceState === 'LISTENING') {
			stopListening()
			return
		}
		if (voiceState === 'SPEAKING') {
			stopSpeaking()
			return
		}
		startListening()
	}

	const statusLabel = VOICE_STATE_LABELS[voiceState] || VOICE_STATE_LABELS.IDLE
	const visibleTranscript = transcript || interimTranscript
	const microphoneLabel = voiceState === 'LISTENING'
		? 'Stop listening'
		: voiceState === 'SPEAKING'
			? 'Stop speaking'
			: 'Start voice input'

	return (
		<section
			className={`voice-stage ${active ? 'voice-stage--active' : ''}`}
			aria-label="METIS voice mode"
			aria-hidden={!active}
			aria-modal="true"
			role="dialog"
		>
			<header className="voice-stage-header">
				<div className="voice-brand">
					<img src={metisLogo} alt="" />
					<span>METIS</span>
				</div>
				<span className="voice-mode-label">VOICE MODE</span>
			</header>

			<div className={`voice-center voice-center--${voiceState.toLowerCase()}`}>
				<div className="voice-core-aura" aria-hidden="true" />
				<div className="voice-core-wrap">
					<ParticleTether
						dotColor="#d8d8d8"
						density={105}
						dotSize={72}
						speed={14}
						spinTurns={1}
						ball={{ spread: 80 }}
						pointer={{ drag: 0 }}
						style={{ width: '100%', height: '100%' }}
					/>
				</div>
				<div className="voice-state" aria-live="polite">
					<strong>{statusLabel}</strong>
					{voiceError && <span className="voice-feedback voice-feedback--error">{voiceError}</span>}
					{!voiceError && interimTranscript && <span className="voice-feedback">Hearing: {interimTranscript}</span>}
					{!voiceError && transcript && <span className="voice-feedback">You said: {transcript}</span>}
					{response && <span className="voice-feedback voice-response">METIS: {response}</span>}
					{!voiceError && !visibleTranscript && !response && <span className="voice-feedback">Tap the microphone to speak</span>}
				</div>
			</div>

			<footer className="voice-stage-footer">
				<div className="voice-controls">
					<button
						className={`voice-mic-button ${voiceState === 'LISTENING' ? 'voice-mic-button--active' : ''} ${voiceState === 'SPEAKING' ? 'voice-mic-button--speaking' : ''}`}
						ref={microphoneRef}
						type="button"
						aria-label={microphoneLabel}
						aria-pressed={voiceState === 'LISTENING' || voiceState === 'SPEAKING'}
						disabled={voiceState === 'PROCESSING' || voiceState === 'THINKING' || playback.active}
						onClick={handleMicrophoneClick}
					>
						{voiceState === 'SPEAKING' ? <VolumeX size={25} strokeWidth={1.7} /> : voiceState === 'LISTENING' ? <MicOff size={25} strokeWidth={1.7} /> : <Mic size={25} strokeWidth={1.7} />}
					</button>
					<button className="voice-exit-button" type="button" onClick={onExit}>Exit voice</button>
				</div>
				{(!recognitionSupported || voiceError) && (
					<button className="voice-type-button" type="button" onClick={onTypeMessage}>
						<MessageSquareText size={14} /> Type your message
					</button>
				)}
			</footer>
		</section>
	)
}
