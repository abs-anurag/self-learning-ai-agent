import { Calendar, ChevronRight, Clock, History, Target } from 'lucide-react'
import StatusBadge from './StatusBadge'

export default function TaskHistory({ tasks = [], onSelect, activeTaskId }) {
	return (
		<section className="panel task-history" aria-label="Task history list">
			<div className="section-heading">
				<div>
					<span className="eyebrow">PERSISTENT RUN LOG</span>
					<h2>Task History</h2>
				</div>
				<span className="sequence-label">
					<History size={13} className="inline mr-1 text-cyan" />
					{tasks.length} total
				</span>
			</div>

			<div className="task-list">
				{tasks.length === 0 ? (
					<div className="empty-state">
						<Clock size={20} className="text-muted" />
						<p>No task runs recorded. Submit a goal to begin.</p>
					</div>
				) : (
					tasks.map((task) => {
						const id = task.task_id || task.id
						const taskType = task.task_type || task.taskType || 'math'
						const isSelected = activeTaskId === id

						let createdStr = 'Recent'
						if (task.created_at) {
							try {
								const d = new Date(task.created_at)
								createdStr = d.toLocaleDateString(undefined, {
									month: 'short',
									day: 'numeric',
									hour: '2-digit',
									minute: '2-digit',
								})
							} catch {
								createdStr = String(task.created_at)
							}
						} else if (task.created) {
							createdStr = task.created
						}

						return (
							<button
								className={`task-row ${isSelected ? 'task-row--active' : ''}`}
								key={id}
								onClick={() => onSelect?.(task)}
								type="button"
							>
								<span className="task-type-dot" data-type={taskType} />
								<div className="task-row-main">
									<strong>{task.goal}</strong>
									<span className="task-row-meta">
										<Clock size={11} className="inline mr-1 text-muted" />
										{createdStr} · <span className="uppercase text-[9px]">{taskType}</span>
									</span>
								</div>
								<StatusBadge status={task.status} />
								<ChevronRight size={16} className="muted-icon" />
							</button>
						)
					})
				)}
			</div>
		</section>
	)
}
