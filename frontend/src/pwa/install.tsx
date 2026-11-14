import { useEffect, useState } from 'react'
import { Button } from '../components/ui'
interface InstallEvent extends Event { prompt: () => Promise<void> }
export function InstallHint() {
  const [event, setEvent] = useState<InstallEvent>(), [hidden, setHidden] = useState(localStorage.getItem('expo-install-dismissed') === '1')
  useEffect(() => { const handler = (event: Event) => { event.preventDefault(); setEvent(event as InstallEvent) }; window.addEventListener('beforeinstallprompt', handler); return () => window.removeEventListener('beforeinstallprompt', handler) }, [])
  if (hidden || matchMedia('(display-mode: standalone)').matches || !matchMedia('(max-width: 760px)').matches) return null
  return <div className="install-hint"><div><strong>Keep Expo Buddy on your phone</strong><p>Install from your browser menu. On iPhone, use Safari → Share → Add to Home Screen.</p></div>{event && <Button variant="secondary" onClick={() => { void event.prompt() }}>Install app</Button>}<button className="icon-button" aria-label="Dismiss install hint" onClick={() => { setHidden(true); localStorage.setItem('expo-install-dismissed', '1') }}>×</button></div>
}
