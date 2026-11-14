import { QueryStatus } from '../components/ui/query-status'
import { AccuracyPanel } from './accuracy'
import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { LogOut, Settings, Activity, CalendarDays, Download } from 'lucide-react'
import { api, ApiError, send } from '../api/client'
import { BackupSettings } from './backups'
import { AgentSettings } from './agent'
import { ProviderSettings } from './providers'
import type { Health } from '../health'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, ErrorMessage, Field, Loading } from '../components/ui'

export function SettingsPage({
  onSignedOut,
  passwordRequired,
}: {
  onSignedOut: () => void
  passwordRequired: boolean
}) {
  const { preferences, refresh } = useLibrary(),
    toast = useToast()
  const [error, setError] = useState<unknown>()
  const password = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    try {
      await send('/auth/password', {
        current_password: data.get('current'),
        password: data.get('password'),
      })
      form.reset()
      toast('Password changed. Other devices will need to sign in again.')
    } catch (error) {
      setError(error)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Settings</h1>
          <p className="muted">Your library, your way.</p>
        </div>
      </div>
      <div className="settings-links">
        <Link to="/expos">
          <CalendarDays size={20} />
          Expos
        </Link>
        <Link to="/health">
          <Activity size={20} />
          System health
        </Link>
        <Link to="/exports">
          <Download size={20} />
          Exports
        </Link>
      </div>
      <ProviderSettings />
      <AccuracyPanel />
      <details className="panel">
        <summary>Agent access (Hermes)</summary>
        <AgentSettings />
      </details>
      <details className="panel">
        <summary>Backups & recovery</summary>
        <BackupSettings />
      </details>
      <div className="settings-grid">
        <section className="panel">
          <h2>Appearance & preferences</h2>
          <Field label="Colour theme">
            <select
              value={preferences?.theme ?? 'system'}
              onChange={(event) => {
                void send('/preferences', { theme: event.target.value }, 'PATCH').then(refresh)
              }}
            >
              <option value="system">Follow device</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </Field>
          <Field
            label="Phone number region hint"
            hint="Used only when a region is known. Original numbers are kept."
          >
            <input
              defaultValue={preferences?.region_hint}
              placeholder="e.g. IN"
              maxLength={8}
              onBlur={(event) => {
                void send('/preferences', { region_hint: event.target.value }, 'PATCH').then(
                  refresh,
                )
              }}
            />
          </Field>
          <p className="caption">Times follow APP_TIMEZONE (UTC by default).</p>
        </section>
        {passwordRequired && (
          <section className="panel">
            <h2>Account password</h2>
            <form onSubmit={password}>
              <Field label="Current password">
                <input name="current" type="password" autoComplete="current-password" required />
              </Field>
              <Field label="New password">
                <input
                  name="password"
                  type="password"
                  minLength={8}
                  maxLength={256}
                  autoComplete="new-password"
                  required
                />
              </Field>
              <ErrorMessage error={error} />
              <Button variant="secondary">Change password</Button>
            </form>
          </section>
        )}
      </div>
      {passwordRequired && (
        <Button
          variant="ghost"
          onClick={async () => {
            await send('/auth/logout', {})
            onSignedOut()
          }}
        >
          <LogOut size={17} />
          Sign out
        </Button>
      )}
    </>
  )
}

export function HealthPage() {
  const health = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api<any>('/system/status'),
    refetchInterval: 5000,
    retry: false,
  })
  const current = health.error instanceof ApiError ? (health.error.details as any) : health.data
  const data = current?.services ? current : health.data
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>System health</h1>
          <p className="muted">A clear view of the services caring for your collection.</p>
        </div>
        <Badge tone={!health.isError && health.data?.status === 'ready' ? 'green' : 'amber'}>
          {!health.isError && health.data?.status === 'ready'
            ? 'Services available'
            : health.isError
              ? 'Status unavailable or services need attention'
              : 'Checking services'}
        </Badge>
      </div>
      <QueryStatus query={health} label="System health" />
      {health.isPending ? null : (
        <div className="settings-grid">
          <section className="panel">
            <h2>Services</h2>
            {Object.entries(data?.services ?? {}).map(([name, state]) => (
              <div className="status-row" key={name}>
                <span>{name}</span>
                <Badge tone={state === 'ready' ? 'green' : 'amber'}>{String(state)}</Badge>
              </div>
            ))}
          </section>
          <section className="panel">
            <h2>Storage drives</h2>
            {data?.storage?.map((disk: any) => (
              <div className="status-row" key={disk.name}>
                <span>{disk.name}</span>
                <Badge tone={disk.ok ? 'green' : 'amber'}>{disk.message}</Badge>
              </div>
            ))}
          </section>
          <section className="panel">
            <h2>Processing & models</h2>
            {Object.entries(data?.jobs ?? {}).map(([state, count]) => (
              <div className="status-row" key={state}>
                <span>{state}</span>
                <strong>{String(count)}</strong>
              </div>
            ))}
            {data?.models?.map((model: any) => (
              <div className="status-row" key={model.name}>
                <span>{model.name}</span>
                <Badge>{model.cached ? 'Cached locally' : 'Download needed'}</Badge>
              </div>
            ))}
          </section>
          <section className="panel">
            <h2>Recent issues</h2>
            {data?.errors?.map((error: any, index: number) => (
              <div className="system-row" key={index}>
                <strong>{error.stage}</strong>
                <p>{error.reason}</p>
                <small>{new Date(error.time).toLocaleString()}</small>
              </div>
            ))}
          </section>
        </div>
      )}
    </>
  )
}
