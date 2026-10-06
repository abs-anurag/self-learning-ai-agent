import { Activity, ArrowUpRight, Crosshair } from 'lucide-react'

export default function CurrentStep({ step = 'Autonomous Reasoning Standby' }) {
	return (
		<div className="current-step" role="status" aria-live="polite">
			<span className="current-step-icon">
				<Crosshair size={17} className="text-cyan animate-pulse" />
			</span>
			<div className="min-w-0 flex-1">
				<span className="eyebrow">ACTIVE AGENT NODE / STEP</span>
				<strong className="truncate block text-slate-100">{step}</strong>
			</div>
			<Activity size={16} className="text-teal opacity-75 shrink-0" />
		</div>
	)
}
