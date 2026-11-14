import { QueryStatus } from '../components/ui/query-status'
import { formatTime, formatDate } from '../app/time'
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  ArrowUpRight,
  Building2,
  ContactRound,
  Files,
  StickyNote,
  Plus,
  Upload,
  Check,
  Layers,
  Sparkles,
} from 'lucide-react'
import { api, isServerReachable, type Dashboard } from '../api/client'
import { useLibrary } from '../app/providers'
import {
  Badge,
  DocumentStatus,
  Button,
  Empty,
  ErrorMessage,
  Loading,
  stateLabel,
} from '../components/ui'
import type { SystemStatus } from '../api/types'

export function HomePage() {
  const [all, setAll] = useState(false),
    [error, setError] = useState<unknown>()
  const { activeExpo } = useLibrary()
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: ['dashboard', all, activeExpo?.id],
    queryFn: () =>
      api<Dashboard>(`/dashboard${!all && activeExpo ? `?expo_id=${activeExpo.id}` : ''}`),
    refetchInterval: 5000,
    retry: false,
  })
  const system = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api<SystemStatus>('/system/status'),
    refetchInterval: 10000,
    retry: false,
  })
  const [reachable, setReachable] = useState(isServerReachable)
  useEffect(() => {
    const changed = (event: Event) => setReachable((event as CustomEvent<boolean>).detail)
    window.addEventListener('server-reachability', changed)
    return () => window.removeEventListener('server-reachability', changed)
  }, [])
  const data = query.data
  const available = !!data && !query.isError && reachable
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Your expo library.</h1>
          <p className="muted">
            {activeExpo
              ? `Everything you brought back from ${activeExpo.name}.`
              : 'Turn your expo discoveries into a library you can use.'}
          </p>
        </div>
        <Button onClick={() => navigate(activeExpo ? '/capture' : '/expos')}>
          <Plus size={18} />
          {activeExpo ? 'Add to library' : 'Create your first expo'}
        </Button>
      </div>
      <label className="checkbox-label">
        <input type="checkbox" checked={all} onChange={(event) => setAll(event.target.checked)} />
        All expos
      </label>
      <ErrorMessage error={error} />
      <QueryStatus query={query} label="Overview" />
      {!available && data && (
        <p className="notice">Showing last known counts. They may be stale.</p>
      )}
      <div className="stats-grid">
        {[
          { label: 'Companies', key: 'companies', icon: Building2 },
          { label: 'People', key: 'contacts', icon: ContactRound },
          { label: 'Documents', key: 'documents', icon: Files },
          { label: 'Personal notes', key: 'notes', icon: StickyNote },
        ].map(({ label, key, icon: Icon }) => (
          <div className="stat-card" key={key}>
            <div>
              <span>{label}</span>
              <Icon size={19} />
            </div>
            <strong>{data ? (data[key as keyof Dashboard] as number) : '—'}</strong>
            <small>
              {!available
                ? 'Unavailable or last known'
                : activeExpo
                  ? 'In this expo'
                  : 'Across your library'}
            </small>
          </div>
        ))}
      </div>
      <div className="dashboard-columns">
        <div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>In progress</h2>
                <p>Your files keep processing after you leave.</p>
              </div>
              <span className="icon-tile">
                <Sparkles size={18} />
              </span>
            </div>
            {query.isPending ? (
              <Loading />
            ) : query.isError || !reachable ? (
              <p className="notice">Processing status unavailable. Reconnect to check progress.</p>
            ) : data &&
              Object.entries(data.processing)
                .filter(([state]) => state !== 'ready')
                .some(([, count]) => count > 0) ? (
              <div className="processing-list">
                {Object.entries(data.processing)
                  .filter(([state]) => state !== 'ready')
                  .map(([state, count]) => (
                    <div className="processing-row" key={state}>
                      <span className="status-dot" />
                      <span>{stateLabel(state)}</span>
                      <strong>{count}</strong>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="quiet-status">
                <span className="check-circle">
                  <Check size={18} />
                </span>
                <div>
                  <strong>No processing work waiting</strong>
                  <p>Review outstanding suggestions before using contact details.</p>
                </div>
              </div>
            )}
          </section>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Recent additions</h2>
                <p>The latest pieces of your collection.</p>
              </div>
              <Link className="text-button" to="/library">
                View library
                <ArrowUpRight size={15} />
              </Link>
            </div>
            {query.isPending ? (
              <Loading />
            ) : !available && !data ? (
              <p className="notice">Recent additions unavailable.</p>
            ) : data?.recent.length ? (
              <div className="recent-list">
                {data.recent.map((doc) => (
                  <Link to={`/documents/${doc.id}`} className="recent-row" key={doc.id}>
                    <div className="document-mini">
                      <Files size={20} />
                    </div>
                    <div>
                      <strong>{doc.title}</strong>
                      <small>
                        {formatDate(doc.created_at, { month: 'short', day: 'numeric' })} ·{' '}
                        {doc.type}
                      </small>
                    </div>
                    <DocumentStatus document={doc} />
                    <ArrowRight size={17} />
                  </Link>
                ))}
              </div>
            ) : (
              <Empty
                title="Your collection starts here"
                description="Add visiting cards, brochures, and the notes that make them useful."
                action={
                  <Button
                    variant="secondary"
                    onClick={() => navigate(activeExpo ? '/capture' : '/expos')}
                  >
                    <Upload size={16} />
                    Add your first files
                  </Button>
                }
              />
            )}
          </section>
        </div>
        <div>
          <section className="panel attention-panel">
            {(data?.grouping_overdue ?? 0) > 0 && (
              <p className="notice">
                {data?.grouping_overdue} documents have waited more than three days. Check their
                groups when ready.
              </p>
            )}
            {(data?.failed ?? 0) > 0 && (
              <Link to="/health" className="notice">
                {data?.failed} items could not finish. View details.
              </Link>
            )}
            <div className="panel-heading">
              <h2>A moment of your attention</h2>
            </div>
            <Link className="attention-item" to="/grouping">
              <span className="icon-tile amber">
                <Layers size={19} />
              </span>
              <div>
                <strong>Check photo groups</strong>
                <p>
                  {!available
                    ? 'Group status unavailable'
                    : data?.grouping
                      ? `${data.grouping} documents need confirmation before AI extraction`
                      : 'No groups waiting'}
                </p>
              </div>
              <ArrowRight size={17} />
            </Link>
            <Link className="attention-item" to="/review">
              <span className="icon-tile">
                <ContactRound size={19} />
              </span>
              <div>
                <strong>Review details</strong>
                <p>
                  {available
                    ? `${data?.review} documents · ${data?.proposed_changes} suggestions`
                    : 'Review status unavailable'}
                </p>
              </div>
              <ArrowRight size={17} />
            </Link>
          </section>
          <section className="panel">
            <h2>AI providers</h2>
            {data?.providers.map((provider) => (
              <div className="status-row" key={provider.provider}>
                <span>
                  {provider.provider === 'chatgpt'
                    ? 'ChatGPT'
                    : provider.provider === 'openrouter'
                      ? 'OpenRouter'
                      : 'Ollama'}
                </span>
                <div className="badge-row">
                  {provider.provider === 'chatgpt' && (
                    <Badge>{provider.connected ? 'Connected' : 'Signed out'}</Badge>
                  )}
                  <Badge>
                    Processing:{' '}
                    {provider.processing_allowed ? provider.state.replaceAll('_', ' ') : 'off'}
                  </Badge>
                </div>
              </div>
            ))}
            {data?.waiting_reason && <p className="notice">Paused: {data.waiting_reason}</p>}
            {data?.providers
              .filter((row) => row.provider === 'openrouter')
              .map((row) => (
                <p className="caption" key={row.provider}>
                  Estimated this month: ${row.spent} / ${row.spending_cap}
                </p>
              ))}
            <Link className="text-button" to="/settings">
              Manage providers
            </Link>
          </section>
          <section className="panel">
            <h2>Phone queue</h2>
            {!available ? (
              <p className="notice">Phone queue status unavailable.</p>
            ) : data?.phone_queue.length ? (
              data.phone_queue.map((phone) => (
                <div className="system-row" key={phone.id}>
                  <strong>
                    {phone.device_label} · {phone.client_uuid.slice(0, 6)}
                  </strong>
                  <p>
                    {phone.files} files · {phone.notes} notes waiting
                  </p>
                  <small>
                    Last reported {formatTime(phone.updated_at)}. Counts may have changed while
                    offline.
                  </small>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void api(`/sync/report/${phone.id}`, { method: 'DELETE' })
                        .then(() => query.refetch())
                        .catch(setError)
                    }}
                  >
                    Dismiss report
                  </Button>
                  <small>Dismisses this report only. Captures stay on the device.</small>
                </div>
              ))
            ) : (
              <p className="muted">
                No pending work reported. Connected devices update their own queue report.
              </p>
            )}
          </section>
          <section className="panel">
            <h2>System</h2>
            <QueryStatus query={system} label="System status" />
            {system.data?.storage?.map((disk) => (
              <div className="system-row" key={disk.name}>
                <strong>{disk.name}</strong>
                <small>
                  {disk.free_bytes == null || disk.total_bytes == null
                    ? disk.message
                    : `${(disk.free_bytes / 1024 ** 3).toFixed(1)} GB free of ${(disk.total_bytes / 1024 ** 3).toFixed(1)} GB`}
                </small>
                {disk.total_bytes != null && disk.free_bytes != null && disk.total_bytes > 0 && (
                  <progress
                    className="disk-meter"
                    max={disk.total_bytes}
                    value={disk.total_bytes - disk.free_bytes}
                  />
                )}
                {disk.warning && <p className="notice">{disk.message}</p>}
              </div>
            ))}
            <p className="notice">
              {system.isPending
                ? 'Checking backup status…'
                : system.isError || !reachable || !system.data?.backup
                  ? 'Backup status unavailable. Reconnect to verify your last backup.'
                  : !system.data.backup.last_success
                    ? 'No successful backup recorded.'
                    : system.data.backup.warning
                      ? `Backup needs attention. Last successful backup ${formatTime(system.data.backup.last_success)}.`
                      : `Backup is current. Last saved ${formatTime(system.data.backup.last_success)}.`}
            </p>
            <Link className="text-button" to="/health">
              View health
            </Link>
          </section>
          <section className="panel tip-panel">
            <span className="eyebrow">A GOOD HABIT</span>
            <h2>Capture the context, too.</h2>
            <p>A quick note about a conversation can be more useful than the card itself.</p>
            <Link className="text-button" to="/capture">
              Open capture
              <ArrowRight size={15} />
            </Link>
          </section>
          <section className="panel compact-panel">
            <div className="panel-heading">
              <h2>Private by default</h2>
              <span className="status-dot" />
            </div>
            <p className="muted">
              Originals and search stay on your server. You choose which AI providers can read
              document text.
            </p>
            <Link className="text-button" to="/settings">
              Provider settings
              <ArrowUpRight size={14} />
            </Link>
          </section>
        </div>
      </div>
    </>
  )
}
