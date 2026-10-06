import { useEffect, useRef, useState } from 'react'
import {
	Activity,
	BrainCircuit,
	ChevronLeft,
	ChevronRight,
	History,
	Menu,
	MessageSquareMore,
	Plus,
	Settings,
	Sparkles,
	X,
} from 'lucide-react'

import metisLogo from './assets/metis-logo.jpeg'
import DotCursor from './components/originkit/ui/dot-cursor'
import Tornado from './components/originkit/ui/tornado'
import VoiceMode from './components/VoiceMode'

import ActivityPage from './pages/ActivityPage'
import ConversationPage from './pages/ConversationPage'
import NewChatPage from './pages/NewChatPage'
import SettingsPage from './pages/SettingsPage'
import TasksPage from './pages/TasksPage'
import MemoryPage from './pages/MemoryPage'
import { useAgentStore } from './store/agentStore'

const NAVIGATION_ITEMS = [
	{ id: 'new-chat', label: 'New Chat', icon: MessageSquareMore },
	{ id: 'history', label: 'History', icon: History },
	{ id: 'activity', label: 'Activity', icon: Activity },
	{ id: 'memory', label: 'Memory', icon: BrainCircuit },
]

function App() {
	const [activeView, setActiveView] = useState('new-chat')
	const [sidebarOpen, setSidebarOpen] = useState(false)
	const [collapsed, setCollapsed] = useState(false)
	const [voiceMode, setVoiceMode] = useState(false)
	const [voiceMounted, setVoiceMounted] = useState(false)
	const [dotCursorEnabled, setDotCursorEnabled] = useState(false)
	const voiceToggleRef = useRef(null)
	const { tasks, systemStatus, status, activeTask, setActiveTask, startNewChat } = useAgentStore()
	const recentTasks = tasks.slice(0, 6)

	useEffect(() => {
		const finePointer = window.matchMedia('(pointer: fine)')
		const hover = window.matchMedia('(hover: hover)')
		const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
		const updateCursorSupport = () => {
			setDotCursorEnabled(finePointer.matches && hover.matches && !reducedMotion.matches)
		}

		updateCursorSupport()
		finePointer.addEventListener('change', updateCursorSupport)
		hover.addEventListener('change', updateCursorSupport)
		reducedMotion.addEventListener('change', updateCursorSupport)
		return () => {
			finePointer.removeEventListener('change', updateCursorSupport)
			hover.removeEventListener('change', updateCursorSupport)
			reducedMotion.removeEventListener('change', updateCursorSupport)
		}
	}, [])

	useEffect(() => {
		const closeOnEscape = (event) => {
			if (event.key === 'Escape') {
				setSidebarOpen(false)
				setVoiceMode(false)
			}
		}
		window.addEventListener('keydown', closeOnEscape)
		return () => window.removeEventListener('keydown', closeOnEscape)
	}, [])

	useEffect(() => {
		if (voiceMode) {
			setVoiceMounted(true)
			return undefined
		}
		if (!voiceMounted) return undefined

		const timer = window.setTimeout(() => {
			setVoiceMounted(false)
			voiceToggleRef.current?.focus()
		}, 480)
		return () => window.clearTimeout(timer)
	}, [voiceMode, voiceMounted])

	useEffect(() => {
		if (!voiceMounted) return undefined

		const bodyOverflow = document.body.style.overflow
		const documentOverflow = document.documentElement.style.overflow
		document.body.style.overflow = 'hidden'
		document.documentElement.style.overflow = 'hidden'
		return () => {
			document.body.style.overflow = bodyOverflow
			document.documentElement.style.overflow = documentOverflow
		}
	}, [voiceMounted])

	const focusComposer = () => {
		startNewChat()
		setVoiceMode(false)
		setActiveView('new-chat')
		setSidebarOpen(false)
		window.requestAnimationFrame(() => window.dispatchEvent(new CustomEvent('focus-task-composer')))
	}

	const openTask = (task) => {
		setActiveTask(task)
		setActiveView('chat')
		setSidebarOpen(false)
	}

	const handleTaskCreated = () => setActiveView('chat')

	const enterVoiceMode = () => {
		setVoiceMode(true)
	}

	const submitVoiceTranscript = (transcript) => {
		const store = useAgentStore.getState()
		if (store.activeTask) store.continueTask(transcript)
		else store.submitTask(transcript)
		setActiveView('chat')
	}

	const typeVoiceMessage = () => {
		setVoiceMode(false)
		setActiveView(useAgentStore.getState().activeTask ? 'chat' : 'new-chat')
		window.setTimeout(() => window.dispatchEvent(new CustomEvent('focus-task-composer')), 500)
	}

	const mainLabel = {
		'new-chat': 'New Chat',
		chat: 'Conversation',
		history: 'History',
		activity: 'Activity',
		memory: 'Memory',
		settings: 'Settings',
	}[activeView] || 'New Chat'

	const page =
		activeView === 'new-chat' ? (
			<NewChatPage onTaskCreated={handleTaskCreated} onEnterVoiceMode={enterVoiceMode} voiceToggleRef={voiceToggleRef} />
		) : activeView === 'chat' ? (
			<ConversationPage onOpenActivity={() => setActiveView('activity')} onEnterVoiceMode={enterVoiceMode} voiceToggleRef={voiceToggleRef} />
		) : activeView === 'history' ? (
			<TasksPage onSelect={openTask} />
		) : activeView === 'activity' ? (
			<ActivityPage />
		) : activeView === 'memory' ? (
			<MemoryPage />
		) : activeView === 'settings' ? (
			<SettingsPage />
		) : (
			<NewChatPage onTaskCreated={handleTaskCreated} onEnterVoiceMode={enterVoiceMode} voiceToggleRef={voiceToggleRef} />
		)
	const showTornado = !voiceMode && (activeView === 'new-chat' || activeView === 'chat')

	return (
		<>
		<div className={`app-shell ${dotCursorEnabled ? 'app-shell--dot-cursor' : ''}`}>
			<div className="ambient-grid" aria-hidden="true" />

			<aside
				className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''} ${sidebarOpen ? 'sidebar--open' : ''}`}
				aria-label="Sidebar navigation"
				aria-hidden={voiceMode}
				inert={voiceMode ? '' : undefined}
			>
				<div className="brand-row">
					<div className="brand-mark" aria-hidden="true">
						<img src={metisLogo} alt="METIS logo" />
					</div>
					{!collapsed && <div className="brand-name">METIS</div>}
					<button
						className="icon-button sidebar-search"
						type="button"
						aria-label="Open search"
						title="Search workspace"
					>
						<Sparkles size={16} />
					</button>
					<button
						className="icon-button sidebar-close"
						onClick={() => setSidebarOpen(false)}
						aria-label="Close navigation"
						type="button"
					>
						<X size={18} />
					</button>
				</div>

				<button
					className="new-task-button"
					type="button"
					onClick={focusComposer}
					title="Start a new task"
					aria-label="New Chat"
				>
					<Plus size={16} />
					{!collapsed && <span>New chat</span>}
				</button>

				<nav className="nav-list" aria-label="Main navigation">
					{!collapsed && <div className="eyebrow nav-eyebrow">Workspace</div>}
					{NAVIGATION_ITEMS.map(({ id, label, icon: Icon }) => (
						<button
							key={id}
							className={`nav-item ${activeView === id ? 'nav-item--active' : ''}`}
							onClick={() => {
								if (id === 'new-chat') focusComposer()
								else setActiveView(id)
								setSidebarOpen(false)
							}}
							title={collapsed ? label : undefined}
							aria-label={label}
							type="button"
							aria-current={activeView === id ? 'page' : undefined}
						>
							<Icon size={18} />
							{!collapsed && <span className="nav-label">{label}</span>}
							{id === 'history' && !collapsed && <span className="nav-count">{tasks.length}</span>}
						</button>
					))}
				</nav>

				{!collapsed && (
					<section className="sidebar-section" aria-labelledby="recent-tasks-title">
						<div className="sidebar-section-heading">
							<span id="recent-tasks-title" className="eyebrow">Recent chats</span>
							<span>{recentTasks.length}</span>
						</div>
						<div className="recent-task-list">
							{recentTasks.length === 0 ? (
								<p className="sidebar-empty">No recent tasks</p>
							) : (
								recentTasks.map((task) => (
									<button
										key={task.task_id || task.id}
										className={`recent-task ${activeTask?.task_id === (task.task_id || task.id) ? 'recent-task--active' : ''}`}
										type="button"
										onClick={() => openTask(task)}
									>
										<span className={`recent-task-dot recent-task-dot--${task.status}`} />
										<span>{task.goal}</span>
									</button>
								))
							)}
						</div>
					</section>
				)}

				<div className="sidebar-bottom">
					{!collapsed && (
						<div className="agent-card">
							<div className="agent-orbit">
								<Sparkles size={15} />
							</div>
							<div>
								<strong>{systemStatus?.label || 'METIS Online'}</strong>
								<span>{systemStatus?.sublabel || (systemStatus?.state === 'online' ? 'Live backend connected' : 'Demo mode active')}</span>
							</div>
							<span
								className="status-pulse"
								style={{
									backgroundColor:
										status === 'running'
											? '#c4c4c4'
											: status === 'succeeded'
												? '#f1f1f1'
												: status === 'failed'
													? '#999999'
													: '#a8a8a8',
								}}
							/>
						</div>
					)}
					<button
						className="settings-button"
						type="button"
						title="Settings"
						aria-label="Settings"
						onClick={() => setActiveView('settings')}
					>
						<Settings size={14} />
						{!collapsed && <span>Settings</span>}
					</button>
					<button
						className="collapse-button"
						onClick={() => setCollapsed(!collapsed)}
						aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
						type="button"
					>
						{collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
						<span>{collapsed ? 'Expand' : 'Collapse'}</span>
					</button>
				</div>
			</aside>

			{sidebarOpen && (
				<button
					className="mobile-scrim"
					onClick={() => setSidebarOpen(false)}
					aria-label="Close navigation"
					inert={voiceMode ? '' : undefined}
					type="button"
				/>
			)}

			<main className="main-content" aria-hidden={voiceMode} inert={voiceMode ? '' : undefined}>
				{showTornado && (
					<div className="tornado-background" aria-hidden="true">
						<Tornado
							background="transparent"
							speed={4}
							zoom={85}
							lineOptions={{ count: 80, color: '#e8e8e8', glow: 2.5 }}
							dotOptions={{ count: 700, size: 8, color: '#cfcfcf', glow: 1.2, flicker: 2 }}
							comets={false}
						/>
					</div>
				)}
				<header className="topbar">
					<button
						className="icon-button mobile-menu"
						onClick={() => setSidebarOpen(true)}
						aria-label="Open navigation"
						type="button"
					>
						<Menu size={20} />
					</button>

					<div className="topbar-identity">
						<span className="topbar-kicker">METIS</span>
						<span className="topbar-slash">/</span>
						<strong>{mainLabel}</strong>
					</div>

					<div className="topbar-actions">
						<div className="system-status">
							<span className="status-pulse status-pulse--small" />
							<span>{systemStatus.label}</span>
						</div>
						<button className="topbar-button topbar-button--primary" type="button" onClick={focusComposer}>New chat</button>
						<div className="avatar" aria-label="Profile">M</div>
					</div>
				</header>

				<div className="page-wrap">{page}</div>
			</main>

			{voiceMounted && (
				<VoiceMode
					active={voiceMode}
					onExit={() => setVoiceMode(false)}
					onSubmitTranscript={submitVoiceTranscript}
					onTypeMessage={typeVoiceMessage}
				/>
			)}
		</div>
		{dotCursorEnabled && (
			<DotCursor
				label={false}
				headColor="#e2e2e2"
				trailColor="rgba(226, 226, 226, 0.12)"
				size={8}
				trailLength={4}
				trailThickness={6}
				style={{
					position: 'fixed',
					inset: 0,
					width: '100vw',
					height: '100vh',
					zIndex: 10000,
				}}
			/>
		)}
		</>
	)
}
export default App
