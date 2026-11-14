import { useEffect, useState } from 'react'
import { registerSW } from 'virtual:pwa-register'
import { Button } from '../components/ui'

let available = false
const update = registerSW({
  immediate: true,
  onRegisteredSW(_url, registration) {
    const check = () => {
      if (document.visibilityState === 'visible') void registration?.update().catch(() => {})
    }
    window.addEventListener('online', check)
    document.addEventListener('visibilitychange', check)
  },
  onNeedRefresh() {
    available = true
    window.dispatchEvent(new Event('app-update-ready'))
  },
})

export function AppUpdateHint() {
  const [ready, setReady] = useState(available)
  useEffect(() => {
    const show = () => setReady(true)
    window.addEventListener('app-update-ready', show)
    return () => window.removeEventListener('app-update-ready', show)
  }, [])
  return ready ? (
    <div className="notice app-update" role="status">
      <div>
        <strong>An app update is ready.</strong>
        <p>Queued photos stay on this device. Finish typing any unsaved note before updating.</p>
      </div>
      <Button
        variant="secondary"
        onClick={() => {
          void update(true)
        }}
      >
        Update app
      </Button>
    </div>
  ) : null
}
