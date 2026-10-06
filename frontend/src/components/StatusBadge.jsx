import { Check, Circle, Loader2, X } from 'lucide-react'

const STATUS_CONFIGS = {
	succeeded: { Icon: Check, label: 'succeeded', spin: false },
	running: { Icon: Loader2, label: 'running', spin: true },
	failed: { Icon: X, label: 'failed', spin: false },
	pending: { Icon: Circle, label: 'pending', spin: false },
}

export default function StatusBadge({ status = 'pending' }) {
	const normalized = (status || 'pending').toLowerCase()
	const config = STATUS_CONFIGS[normalized] || STATUS_CONFIGS.pending
	const { Icon, label, spin } = config

	return (
		<span className={`status-badge status-badge--${normalized}`}>
			<Icon size={12} className={spin ? 'animate-spin' : ''} />
			<span>{label}</span>
		</span>
	)
}