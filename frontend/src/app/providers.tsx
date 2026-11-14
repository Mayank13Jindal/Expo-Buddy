import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { meta, setMeta, type CachedExpo } from '../pwa/queue'
import { useCaptureSync } from '../pwa/hooks'
import { api, send, type Expo, type Preferences } from '../api/client'
import type { SystemStatus } from '../api/types'

const LibraryContext = createContext<{
  expos: Expo[]
  preferences: Preferences | undefined
  activeExpo: Expo | undefined
  setExpo: (id: string) => Promise<void>
  refresh: () => Promise<void>
}>({
  expos: [],
  preferences: undefined,
  activeExpo: undefined,
  setExpo: async () => {},
  refresh: async () => {},
})

export function LibraryProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  useCaptureSync()
  const [, timezoneChanged] = useState(0)
  const system = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api<SystemStatus>('/system/status'),
  })
  useEffect(() => {
    const zone = system.data?.timezone
    if (zone && localStorage.getItem('expo-timezone') !== zone) {
      localStorage.setItem('expo-timezone', zone)
      timezoneChanged((value) => value + 1)
    }
  }, [system.data?.timezone])
  const [cachedExpos, setCachedExpos] = useState<Expo[]>([]),
    [capturedExpo, setCapturedExpo] = useState<string | null>()
  useEffect(() => {
    const load = () => {
      void meta<Expo[]>('expos').then((value) => setCachedExpos(value ?? []))
      void meta<string>('activeExpo').then((value) => setCapturedExpo(value ?? null))
    }
    load()
    window.addEventListener('capture-change', load)
    return () => window.removeEventListener('capture-change', load)
  }, [])
  const expos = useQuery({ queryKey: ['expos'], queryFn: () => api<Expo[]>('/expos') })
  const preferences = useQuery({
    queryKey: ['preferences'],
    queryFn: () => api<Preferences>('/preferences'),
    refetchOnWindowFocus: true,
  })
  useEffect(() => {
    const theme = preferences.data?.theme ?? 'system'
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === 'system' ? (media.matches ? 'dark' : 'light') : theme
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [preferences.data?.theme])
  useEffect(() => {
    if (!expos.data) return
    void (async () => {
      const existing = (await meta<CachedExpo[]>('expos')) ?? []
      const merged = [
        ...expos.data!,
        ...existing.filter(
          (row) =>
            !expos.data!.some(
              (server) =>
                server.id === row.id || (row.client_uuid && server.client_uuid === row.client_uuid),
            ),
        ),
      ]
      await setMeta('expos', merged)
      if (!(await meta('activeExpo')) && preferences.data?.active_expo_id)
        await setMeta('activeExpo', preferences.data.active_expo_id)
    })()
  }, [expos.data, preferences.data?.active_expo_id])
  const refresh = async () => {
    await client.invalidateQueries()
  }
  const setExpo = async (id: string) => {
    if (!navigator.onLine || !expos.data?.some((expo) => expo.id === id)) {
      await setMeta('activeExpo', id)
      return
    }
    await send(
      '/preferences',
      { active_expo_id: id, expected_revision: preferences.data?.revision },
      'PATCH',
    )
    await setMeta('activeExpo', id)
    await refresh()
  }
  useEffect(() => {
    const events = new EventSource('/api/v1/events')
    const refresh = () => {
      void client.invalidateQueries({
        predicate: (query) => !['session', 'account-status'].includes(String(query.queryKey[0])),
      })
    }
    events.addEventListener('progress', refresh)
    window.addEventListener('capture-synced', refresh)
    let timer: ReturnType<typeof setInterval> | undefined
    events.onerror = () => {
      if (!timer) timer = setInterval(refresh, 5000)
    }
    events.onopen = () => {
      if (timer) {
        clearInterval(timer)
        timer = undefined
      }
    }
    return () => {
      window.removeEventListener('capture-synced', refresh)
      events.close()
      if (timer) clearInterval(timer)
    }
  }, [client])
  const availableExpos = [
    ...(expos.data ?? []),
    ...cachedExpos.filter(
      (row) => !expos.data?.some((server) => server.id === row.id || server.client_uuid === row.id),
    ),
  ]
  // A stored selection must resolve before capture can use it; never fall back to another expo.
  const selected = capturedExpo === null ? preferences.data?.active_expo_id : capturedExpo
  return (
    <LibraryContext
      value={{
        expos: availableExpos,
        preferences: preferences.data,
        activeExpo: availableExpos.find(
          (expo) => selected && (expo.id === selected || expo.client_uuid === selected),
        ),
        setExpo,
        refresh,
      }}
    >
      {children}
    </LibraryContext>
  )
}
export const useLibrary = () => useContext(LibraryContext)

const ToastContext = createContext<(message: string, undo?: () => void) => void>(() => {})
export const useToast = () => useContext(ToastContext)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string; undo?: () => void } | null>(null)
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 7000)
    return () => clearTimeout(timer)
  }, [toast])
  return (
    <ToastContext value={(message, undo) => setToast({ message, undo })}>
      {children}
      {toast && (
        <div className="toast" role="status">
          {toast.message}
          {toast.undo && (
            <button
              onClick={() => {
                toast.undo?.()
                setToast(null)
              }}
            >
              Undo
            </button>
          )}
          <button aria-label="Dismiss message" onClick={() => setToast(null)}>
            ×
          </button>
        </div>
      )}
    </ToastContext>
  )
}
