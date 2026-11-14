import { QueryStatus } from '../components/ui/query-status'
import { formatTime } from '../app/time'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { HardDrive, Save } from 'lucide-react'
import { api, send } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, ErrorMessage, Field } from '../components/ui'
export function BackupSettings() {
  const { refresh } = useLibrary(),
    toast = useToast()
  const config = useQuery({
    queryKey: ['backup-settings'],
    queryFn: () => api<any>('/system/backup-settings'),
  })
  const system = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api<any>('/system/status'),
  })
  const history = useQuery({
    queryKey: ['backups'],
    queryFn: () => api<any[]>('/system/backups'),
    refetchInterval: 10000,
  })
  const [form, setForm] = useState<any>({
      enabled: true,
      hour: 2,
      minute: 0,
      daily_keep: 7,
      weekly_keep: 4,
    }),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false)
  useEffect(() => {
    if (config.data) setForm(config.data)
  }, [config.data])
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>
            <HardDrive size={19} />
            Backups
          </h2>
          <p>Records and originals, in your configured backup folder.</p>
        </div>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await send('/system/backup', {})
              await refresh()
              toast('Backup queued. Its status will update below.')
            } catch (error) {
              setError(error)
            } finally {
              setBusy(false)
            }
          }}
        >
          Back up now
        </Button>
      </div>
      <QueryStatus query={config} label="Backup settings" />
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void send('/system/backup-settings', form, 'PUT')
            .then(async () => {
              await refresh()
              toast('Backup schedule saved.')
            })
            .catch(setError)
        }}
      >
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
          />
          Back up nightly
        </label>
        <div className="form-grid">
          <Field
            label="Nightly time"
            hint="Uses your configured server timezone (Asia/Calcutta by default)."
          >
            <input
              type="time"
              value={`${String(form.hour).padStart(2, '0')}:${String(form.minute).padStart(2, '0')}`}
              onChange={(event) => {
                const [hour, minute] = event.target.value.split(':').map(Number)
                setForm({ ...form, hour, minute })
              }}
            />
          </Field>
          <Field label="Daily snapshots to keep">
            <input
              type="number"
              min={1}
              max={90}
              value={form.daily_keep}
              onChange={(event) => setForm({ ...form, daily_keep: Number(event.target.value) })}
            />
          </Field>
          <Field label="Weekly snapshots to keep">
            <input
              type="number"
              min={1}
              max={52}
              value={form.weekly_keep}
              onChange={(event) => setForm({ ...form, weekly_keep: Number(event.target.value) })}
            />
          </Field>
        </div>
        <Button variant="secondary" type="submit" disabled={config.isPending || config.isError}>
          <Save size={16} />
          Save schedule
        </Button>
      </form>
      <p className="caption">
        Use a different physical disk for backups. Provider credentials are excluded; reconnect them
        after restoring. Previews, search vectors, models and temporary exports can be rebuilt.
      </p>
      {system.data?.backup?.same_filesystem_as_originals && (
        <p className="notice">
          Backups and originals share a filesystem. Use a separate physical disk for protection from
          drive failure.
        </p>
      )}
      <details className="recovery-walkthrough">
        <summary>Recovery walkthrough</summary>
        <ol>
          <li>Choose a completed snapshot. Keep your current library and phone queue.</li>
          <li>
            On the server, restore into a new database:{' '}
            <code>
              python3 scripts/restore.py /path/to/completed-snapshot --database expo_restore_check
            </code>
            .
          </li>
          <li>
            Check the restored originals, records, corrections and personal notes in a temporary
            instance before switching databases.
          </li>
          <li>
            Reconnect providers and create fresh agent tokens; credentials are deliberately excluded
            from snapshots.
          </li>
        </ol>
        <p>
          For storage preparation, verification and cutover steps, open{' '}
          <code>docs/backup-restore.md</code> in your checkout. The restore command refuses an
          existing destination database.
        </p>
      </details>
      <ErrorMessage error={error} />
      <QueryStatus query={history} label="Backup history" />
      {history.data?.slice(0, 12).map((row) => (
        <div className="system-row" key={row.id}>
          <div className="status-row">
            <strong>{formatTime(row.created_at)}</strong>
            <Badge tone={row.state === 'complete' ? 'green' : 'amber'}>{row.state}</Badge>
          </div>
          <small>
            {row.trigger} · {(row.bytes / 1024 ** 2).toFixed(1)} MB
            {row.path ? ` · ${row.path}` : ''}
          </small>
          {row.error && <p className="notice">{row.error}</p>}
        </div>
      ))}
      {!history.isPending && !history.isError && !history.data?.length && (
        <p className="notice">No backup yet. Run one after setting up your backup drive.</p>
      )}
    </section>
  )
}
