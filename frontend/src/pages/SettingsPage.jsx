import { Settings, Volume2 } from 'lucide-react'

export default function SettingsPage() {
	return (
		<div className="settings-page page-enter">
			<div className="page-intro">
				<div>
					<span className="eyebrow eyebrow-accent">WORKSPACE</span>
					<h1><Settings size={25} /> Settings</h1>
					<p>Current workspace configuration.</p>
				</div>
			</div>

			<section className="settings-section">
				<div className="settings-section-heading">
					<div>
						<span className="eyebrow">EXPERIENCE</span>
						<h2>Workspace mode</h2>
					</div>
				</div>
				<div className="settings-row">
					<div>
						<strong>Frontend demo</strong>
						<p>Tasks and agent activity use the local demo experience.</p>
					</div>
					<span className="settings-value">Active</span>
				</div>
				<div className="settings-row">
					<div className="settings-row-label">
						<Volume2 size={17} />
						<div>
							<strong>Voice input</strong>
							<p>Microphone input is not connected.</p>
						</div>
					</div>
					<span className="settings-value settings-value--muted">Unavailable</span>
				</div>
			</section>
		</div>
	)
}
