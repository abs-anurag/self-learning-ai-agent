import { Search } from 'lucide-react'
import { useState } from 'react'
import TaskHistory from '../components/TaskHistory'
import { useAgentStore } from '../store/agentStore'

export default function TasksPage({ onSelect }) {
	const { tasks, activeTask } = useAgentStore()
	const [query, setQuery] = useState('')
	const [statusFilter, setStatusFilter] = useState('all')

	const filtered = tasks.filter((task) => {
		const matchesQuery = (task.goal || '').toLowerCase().includes(query.toLowerCase())
		const matchesStatus = statusFilter === 'all' || task.status === statusFilter
		return matchesQuery && matchesStatus
	})

	return (
		<div className="page-enter tasks-page">
			<div className="page-intro">
				<div>
					<span className="eyebrow eyebrow-accent">CONVERSATION HISTORY</span>
					<h1>
						History<span className="title-dot">.</span>
					</h1>
					<p>
						A durable record of the goals METIS has accepted, the work it completed, and the outcomes it produced.
					</p>
				</div>
			</div>

			<div className="toolbar">
				<label className="search-field">
					<Search size={16} />
					<input
						aria-label="Search tasks"
						placeholder="Search goals, actions, or task context"
						value={query}
						onChange={(event) => setQuery(event.target.value)}
					/>
				</label>

				<div className="filter-row">
					{['all', 'succeeded', 'running', 'failed'].map((st) => (
						<button
							key={st}
							type="button"
							className={`secondary-button filter-button ${statusFilter === st ? 'filter-button--active' : ''}`}
							onClick={() => setStatusFilter(st)}
						>
							{st}
						</button>
					))}
				</div>
			</div>

			<TaskHistory
				tasks={filtered}
				onSelect={onSelect}
				activeTaskId={activeTask?.task_id || activeTask?.id}
			/>
		</div>
	)
}
