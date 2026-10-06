import { CircleAlert, X } from 'lucide-react'
export default function ErrorBanner({ message, onDismiss }) { if (!message) return null; return <div className="error-banner" role="alert"><CircleAlert size={17} /><span>{message}</span><button className="icon-button" onClick={onDismiss} aria-label="Dismiss error"><X size={16} /></button></div> }
