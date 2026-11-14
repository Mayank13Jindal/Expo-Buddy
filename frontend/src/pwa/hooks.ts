import { useEffect, useState } from 'react'
import { allCaptures, type Capture } from './queue'
import { syncQueue } from './sync'
export function useCaptures() {
  const [items, setItems] = useState<Capture[]>([])
  useEffect(() => {
    const load = () => {
      void allCaptures().then(setItems)
    }
    load()
    window.addEventListener('capture-change', load)
    return () => window.removeEventListener('capture-change', load)
  }, [])
  return items
}
export function useCaptureSync() {
  useEffect(() => {
    const sync = () => {
      void syncQueue()
    }
    sync()
    window.addEventListener('online', sync)
    window.addEventListener('focus', sync)
    const timer = setInterval(sync, 30000)
    return () => {
      window.removeEventListener('online', sync)
      window.removeEventListener('focus', sync)
      clearInterval(timer)
    }
  }, [])
}
