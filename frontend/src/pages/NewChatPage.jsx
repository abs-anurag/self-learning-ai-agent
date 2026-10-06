import { ArrowUp, Sparkles } from 'lucide-react'
import TaskInput from '../components/TaskInput'

const SUGGESTIONS = [
	['Analyze data', 'Summarize patterns and surface anomalies', 'Analyze a dataset'],
	['Research', 'Compare sources into a concise brief', 'Research a topic'],
	['Explain', 'Turn a difficult idea into clear steps', 'Explain a concept'],
	['Build', 'Give the agent a focused objective', 'Run an agent task'],
]

export default function NewChatPage({ onTaskCreated, onEnterVoiceMode, voiceToggleRef }) {
	return (
		<div className="new-chat-page page-enter">
			<div className="new-chat-welcome">
				<h1>What can <span>METIS</span> do for you?</h1>
			</div>
			<TaskInput isEmpty onTaskCreated={onTaskCreated} onEnterVoiceMode={onEnterVoiceMode} voiceToggleRef={voiceToggleRef} />
			<div className="new-chat-suggestions" aria-label="Suggested tasks">
				{SUGGESTIONS.map(([title, description, task], index) => (
					<button
						key={title}
						type="button"
						className="quick-start-card"
						aria-label={title}
						aria-describedby={`quick-action-description-${index}`}
						data-description={description}
						onClick={() => window.dispatchEvent(new CustomEvent('metis-quick-start', { detail: task }))}
					>
						<Sparkles size={13} aria-hidden="true" />
						<strong>{title}</strong>
						<ArrowUp size={12} aria-hidden="true" />
						<span className="quick-action-tooltip" id={`quick-action-description-${index}`} role="tooltip">{description}</span>
					</button>
				))}
			</div>
		</div>
	)
}
