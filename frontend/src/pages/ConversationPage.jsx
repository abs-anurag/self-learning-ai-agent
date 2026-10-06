import { Activity, Check, CircleDashed, LoaderCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import metisLogo from '../assets/metis-logo.jpeg'
import ErrorBanner from '../components/ErrorBanner'
import TaskInput from '../components/TaskInput'
import { useAgentStore } from '../store/agentStore'

export default function ConversationPage({ onOpenActivity, onEnterVoiceMode, voiceToggleRef }) {
	const {
		activeTask,
		status,
		events,
		playback,
		errorMessage,
		clearErrorMessage,
		continueTask,
	} = useAgentStore()
	const latestMessageRef = useRef(null)
	const goal = activeTask?.goal || 'Selected task'
	const hasSavedMessages = Array.isArray(activeTask?.messages)
	const messages = hasSavedMessages ? activeTask.messages : [{ role: 'user', content: goal }]
	const statusLabel = status === 'succeeded' ? 'Completed' : status === 'failed' ? 'Failed' : status === 'running' ? 'Working' : 'Ready'
	const hasStartedTools = events.some((event) => event.event_type === 'tool_started')
	const hasCompletedTools = events.some((event) => event.event_type === 'tool_completed')
	const hasCompletedEvaluation = events.some((event) => event.event_type === 'evaluation_completed')
	const activitySteps = [
		{ label: 'Planning', done: hasStartedTools, active: !hasStartedTools },
		{ label: 'Using tools', done: hasCompletedTools, active: hasStartedTools && !hasCompletedTools },
		{ label: 'Evaluating', done: hasCompletedEvaluation, active: hasCompletedTools && !hasCompletedEvaluation },
	]

	useEffect(() => {
		latestMessageRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
	}, [messages.length, playback.active])

	return (
		<div className="conversation-page page-enter">
			<div className="conversation-scroll-area">
				<ErrorBanner message={errorMessage} onDismiss={clearErrorMessage} />
				<header className="conversation-titlebar">
					<div>
						<span className="eyebrow eyebrow-accent">CONVERSATION</span>
						<h1>{goal}</h1>
					</div>
					<div className="conversation-title-actions">
						<span className="conversation-pill"><CircleDashed size={12} />{statusLabel}</span>
						<button className="ghost-button" type="button" onClick={onOpenActivity}>
							<Activity size={14} /> Activity
						</button>
					</div>
				</header>

				<div className="chat-messages" aria-live="polite">
					{messages.map((message, index) => (
						<article className={`chat-message chat-message--${message.role}`} key={`${message.role}-${message.created_at || index}-${index}`}>
							{message.role === 'assistant' ? (
								<div className="chat-avatar chat-avatar--metis"><img src={metisLogo} alt="METIS" /></div>
							) : (
							<div className="chat-avatar chat-avatar--user" aria-hidden="true">You</div>
							)}
							<div className="chat-message-content">
								<span className="chat-speaker">{message.role === 'assistant' ? 'METIS' : 'You'}</span>
								<p>{message.content}</p>
							</div>
						</article>
					))}

					{!hasSavedMessages && !playback.active && status !== 'running' && status !== 'pending' && (
						<article className="chat-message chat-message--assistant">
							<div className="chat-avatar chat-avatar--metis"><img src={metisLogo} alt="METIS" /></div>
							<div className="chat-message-content">
								<span className="chat-speaker">METIS</span>
								<p>No response recorded for this task.</p>
							</div>
						</article>
					)}

					{(playback.active || status === 'running' || status === 'pending') && (
						<div className="chat-activity-inline" role="status" aria-live="polite">
							<div className="chat-avatar chat-avatar--metis"><img src={metisLogo} alt="METIS" /></div>
							<div className="chat-activity-content">
								<p><LoaderCircle size={15} /> Working on your request...</p>
								<div className="chat-activity-steps">
									{activitySteps.map((step) => (
										<span className={`chat-activity-step ${step.done ? 'is-done' : ''} ${step.active ? 'is-active' : ''}`} key={step.label}>
											{step.done ? <Check size={12} /> : null}{step.label}
										</span>
									))}
								</div>
							</div>
						</div>
					)}
					<div ref={latestMessageRef} aria-hidden="true" />
				</div>
			</div>
			<TaskInput conversationMode onSubmit={continueTask} onEnterVoiceMode={onEnterVoiceMode} voiceToggleRef={voiceToggleRef} />
		</div>
	)
}
