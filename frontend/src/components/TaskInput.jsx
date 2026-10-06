import { ArrowUp, FileText, Mic, Plus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import ParticleGimbal from './originkit/ui/particle-gimbal'
import { useAgentStore } from '../store/agentStore'

const MAX_ATTACHMENTS = 5
const MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
const ACCEPTED_FILE_TYPES = [
	'image/png',
	'image/jpeg',
	'image/gif',
	'image/webp',
	'application/pdf',
	'text/plain',
	'text/csv',
	'application/json',
	'application/rtf',
	'application/msword',
	'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]
const ACCEPTED_FILE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.txt', '.csv', '.json', '.rtf', '.doc', '.docx']

export default function TaskInput({ isEmpty = false, conversationMode = false, onTaskCreated, onSubmit, onActivityChange, onEnterVoiceMode, voiceToggleRef }) {
	const [goal, setGoal] = useState('')
	useEffect(() => {
	const handleQuickStart = (event) => {
		setGoal(event.detail)
		composerRef.current?.focus()
	}

	window.addEventListener('metis-quick-start', handleQuickStart)

	return () => window.removeEventListener('metis-quick-start', handleQuickStart)
}, [])
	const [attachments, setAttachments] = useState([])
	const [attachmentError, setAttachmentError] = useState('')
	const [isDragActive, setIsDragActive] = useState(false)
	const composerRef = useRef(null)
	const fileInputRef = useRef(null)
	const attachmentsRef = useRef([])
	const { submitMockTask, status, playback } = useAgentStore()

	const isProcessing = playback.active || status === 'running'

	const isAcceptedFile = (file) => {
		const extension = `.${file.name.split('.').pop()?.toLowerCase() || ''}`
		return ACCEPTED_FILE_TYPES.includes(file.type) || ACCEPTED_FILE_EXTENSIONS.includes(extension)
	}

	const addAttachments = (fileList) => {
		const incomingFiles = Array.from(fileList || [])
		if (!incomingFiles.length) return

		const remainingSlots = MAX_ATTACHMENTS - attachments.length
		const nextFiles = incomingFiles.slice(0, remainingSlots)
		const rejected = incomingFiles.length > remainingSlots ? 'You can attach up to 5 files in this composer.' : ''
		const invalidFile = nextFiles.find((file) => !isAcceptedFile(file))
		const oversizedFile = nextFiles.find((file) => file.size > MAX_ATTACHMENT_SIZE)

		if (invalidFile) {
			setAttachmentError(`Unsupported file type: ${invalidFile.name}`)
			return
		}
		if (oversizedFile) {
			setAttachmentError(`File is larger than 10 MB: ${oversizedFile.name}`)
			return
		}

		setAttachmentError(rejected)
		setAttachments((current) => [
			...current,
			...nextFiles.map((file) => ({
				id: `${file.name}-${file.lastModified}-${Math.random()}`,
				file,
				previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
			})),
		])
	}

	const removeAttachment = (id) => {
		setAttachments((current) => {
			const removed = current.find((attachment) => attachment.id === id)
			if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
			return current.filter((attachment) => attachment.id !== id)
		})
		setAttachmentError('')
	}

	const submit = (event) => {
		event.preventDefault()
		if (goal.trim() && !isProcessing) {
			if (onSubmit) onSubmit(goal.trim())
			else {
				submitMockTask(goal.trim())
				onTaskCreated?.()
			}
			setGoal('')
		}
	}

	useEffect(() => {
		const focusComposer = () => composerRef.current?.focus()
		window.addEventListener('focus-task-composer', focusComposer)
		return () => window.removeEventListener('focus-task-composer', focusComposer)
	}, [])

	useEffect(() => {
		attachmentsRef.current = attachments
	}, [attachments])

	useEffect(() => () => {
		attachmentsRef.current.forEach(({ previewUrl }) => previewUrl && URL.revokeObjectURL(previewUrl))
	}, [])

	return (
		<section
			className={`task-composer panel ${isEmpty ? 'task-composer--empty' : ''} ${conversationMode ? 'task-composer--conversation' : ''} ${isDragActive ? 'task-composer--dragging' : ''}`}
			aria-label="Task goal input composer"
			onFocusCapture={() => onActivityChange?.(true)}
			onBlurCapture={(event) => {
				if (!event.currentTarget.contains(event.relatedTarget)) onActivityChange?.(false)
			}}
			onPointerEnter={() => onActivityChange?.(true)}
			onPointerLeave={(event) => {
				if (!event.currentTarget.contains(document.activeElement)) onActivityChange?.(false)
			}}
			onDragOver={(event) => { event.preventDefault(); setIsDragActive(true) }}
			onDragLeave={(event) => { if (event.currentTarget === event.target) setIsDragActive(false) }}
			onDrop={(event) => { event.preventDefault(); setIsDragActive(false); addAttachments(event.dataTransfer.files) }}
		>
			<form className="composer-body" onSubmit={submit}>
				{!isEmpty && (
					<div className="flex items-center justify-between mb-2">
						<label htmlFor="task-goal" className="composer-label">
							{conversationMode ? 'Message METIS' : 'What can METIS help you with ?'}
						</label>
					</div>
				)}

				<textarea
					id="task-goal"
					value={goal}
					ref={composerRef}
					onChange={(event) => {
						setGoal(event.target.value)
						if (isEmpty) {
							const textarea = event.currentTarget
							textarea.style.height = '32px'
							textarea.style.height = `${Math.min(textarea.scrollHeight, 132)}px`
						}
					}}
					onKeyDown={(event) => {
						if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
							event.preventDefault()
							submit(event)
						}
					}}
					aria-label={isEmpty ? 'Ask anything' : undefined}
					placeholder={isEmpty ? 'ask anything' : conversationMode ? 'Ask a follow-up...' : 'Ask METIS to perform a task...'}
					rows={isEmpty ? 1 : 3}
					disabled={isProcessing}
				/>

				{attachments.length > 0 && (
					<div className="attachment-list" aria-label="Selected attachments">
						{attachments.map(({ id, file, previewUrl }) => (
							<div className="attachment-chip" key={id}>
								{previewUrl ? <img src={previewUrl} alt="" className="attachment-thumb" /> : <FileText size={15} aria-hidden="true" />}
								<span title={file.name}>{file.name}</span>
								<button type="button" className="attachment-remove" onClick={() => removeAttachment(id)} aria-label={`Remove ${file.name}`}>
									<X size={13} />
								</button>
							</div>
						))}
					</div>
				)}

				{attachmentError && <p className="attachment-error" role="alert">{attachmentError} Frontend-only validation.</p>}

				<div className="composer-meta">
					<button
						className="composer-action"
						type="button"
						onClick={() => fileInputRef.current?.click()}
						aria-label="Add attachment"
						title="Add attachment"
						disabled={isProcessing || attachments.length >= MAX_ATTACHMENTS}
					>
						<Plus size={16} />
					</button>
					<input
						ref={fileInputRef}
						type="file"
						className="visually-hidden"
						accept={ACCEPTED_FILE_EXTENSIONS.join(',')}
						multiple
						onChange={(event) => { addAttachments(event.target.files); event.target.value = '' }}
						aria-label="Choose attachments"
					/>
					{!isEmpty && <span className="composer-hint">Enter to run · Shift + Enter for a new line</span>}
					{onEnterVoiceMode && (
						<button
							className="composer-voice-button"
							ref={voiceToggleRef}
							type="button"
							onClick={onEnterVoiceMode}
							aria-label="Start voice mode"
							title="Start voice mode"
							disabled={isProcessing}
						>
							<Mic size={16} strokeWidth={1.8} />
						</button>
					)}
					<button
						className="primary-button"
						type="submit"
						aria-label={isEmpty ? (isProcessing ? 'Working' : 'Run task') : undefined}
						disabled={!goal.trim() || isProcessing}
					>
						<span className="composer-gimbal" aria-hidden="true">
							<ParticleGimbal
								width={34}
								height={34}
								dotColor="#d8d8d8"
								accentColor="#aaaaaa"
								density={70}
								dotSize={28}
								speed={12}
								spinTurns={1}
								ball={{ spread: 72 }}
								pointer={{ drag: 0 }}
								style={{ width: '100%', height: '100%', opacity: 0.34, pointerEvents: 'none' }}
							/>
						</span>
						{isEmpty ? (
							<span className="visually-hidden">{isProcessing ? 'Working...' : 'Run'}</span>
						) : (
							isProcessing ? 'Working...' : 'Run'
						)}
						<ArrowUp size={15} />
					</button>
				</div>
			</form>
		</section>
	)
}
