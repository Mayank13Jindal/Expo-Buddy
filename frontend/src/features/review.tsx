import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight, GitMerge } from 'lucide-react'
import { api, send, type Document } from '../api/client'
import { SourceViewer } from './source-viewer'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, Empty, ErrorMessage, Field, Loading, Modal } from '../components/ui'

type Proposal = {
  record_name: string
  company_name: string
  document_id?: string
  source_page?: import('../api/client').Page
  stale: boolean
  duplicate_warnings: string[]
  changes: {
    index: number
    operation: string
    before: string
    after: string
    label: string
    normalised: string
    warning: string
    can_accept: boolean
  }[]
  id: string
  entity_type: string
  entity_id: string
  field: string
  current_value: unknown
  proposed_value: unknown
  reason: string
  actor: string
  evidence: { page_id: string; quote: string }[]
}
export function MergeDialog({
  kind,
  sourceId,
  initialTarget,
  onClose,
}: {
  kind: 'company' | 'contact'
  sourceId: string
  initialTarget?: string
  onClose: () => void
}) {
  const [targetId, setTargetId] = useState(initialTarget ?? ''),
    [choices, setChoices] = useState<Record<string, string>>({}),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false)
  const { refresh } = useLibrary(),
    toast = useToast()
  const records = useQuery({
    queryKey: ['merge-options', kind],
    queryFn: () =>
      api<Record<string, unknown>[]>(`/${kind === 'company' ? 'companies' : 'contacts'}`),
  })
  const preview = useQuery({
    queryKey: ['merge-preview', kind, sourceId, targetId],
    enabled: !!targetId,
    queryFn: () =>
      send<{ source: Record<string, unknown>; target: Record<string, unknown> }>('/merge/preview', {
        entity_type: kind,
        source_id: sourceId,
        target_id: targetId,
      }),
  })
  const fields =
    kind === 'company'
      ? [
          'display_name',
          'aliases',
          'website',
          'description',
          'business_role',
          'products',
          'services',
          'categories',
          'channels',
        ]
      : ['full_name', 'designation', 'department', 'channels']
  const text = (value: unknown): string =>
    typeof value === 'string'
      ? value || 'Empty'
      : Array.isArray(value)
        ? value
            .map((item) =>
              typeof item === 'string'
                ? item
                : [item.kind, item.label, item.raw].filter(Boolean).join(' · '),
            )
            .join('\n')
        : 'Empty'
  const merge = async () => {
    if (!preview.data) return
    const values = Object.fromEntries(
      fields.map((field) => {
        const from = preview.data!.source[field],
          to = preview.data!.target[field],
          choice = choices[field] ?? 'target'
        return [
          field,
          choice === 'source'
            ? from
            : choice === 'both' && Array.isArray(from) && Array.isArray(to)
              ? [...to, ...from].filter(
                  (item, index, all) =>
                    all.findIndex((other) => JSON.stringify(other) === JSON.stringify(item)) ===
                    index,
                )
              : to,
        ]
      }),
    )
    setBusy(true)
    try {
      const result = await send<{ history_id: string }>('/merge', {
        entity_type: kind,
        source_id: sourceId,
        target_id: targetId,
        values,
      })
      await refresh()
      onClose()
      toast('Records merged.', () => {
        void send(`/history/${result.history_id}/undo`, {}).then(refresh)
      })
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title="Compare and merge"
      description="Choose the details to keep. Contacts, expo appearances, and originals are preserved."
    >
      <Field label="Merge into">
        <select
          value={targetId}
          onChange={(event) => {
            setTargetId(event.target.value)
            setChoices({})
          }}
        >
          <option value="">Choose a record</option>
          {records.data
            ?.filter((row) => row.id !== sourceId)
            .map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {String(row.display_name ?? row.full_name)}
              </option>
            ))}
        </select>
      </Field>
      {preview.data &&
        fields.map((field) => (
          <div className="merge-field" key={field}>
            <strong>{field.replaceAll('_', ' ')}</strong>
            <div className="merge-values">
              <p>{text(preview.data!.source[field])}</p>
              <p>{text(preview.data!.target[field])}</p>
            </div>
            <select
              aria-label={`Keep ${field}`}
              value={choices[field] ?? 'target'}
              onChange={(event) => setChoices({ ...choices, [field]: event.target.value })}
            >
              <option value="target">Use the destination value</option>
              <option value="source">Use the source value</option>
              {Array.isArray(preview.data!.source[field]) && (
                <option value="both">Keep both lists</option>
              )}
            </select>
          </div>
        ))}
      <ErrorMessage error={error ?? preview.error} />
      <div className="form-actions">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button
          disabled={busy || !preview.data}
          onClick={() => {
            void merge()
          }}
        >
          <GitMerge size={16} />
          Merge chosen values
        </Button>
      </div>
    </Modal>
  )
}

function ProposalCard({
  item,
  decide,
}: {
  item: Proposal
  decide: (id: string, decision: string, selected?: number[]) => Promise<void>
}) {
  const [selected, setSelected] = useState<number[]>([]),
    [busy, setBusy] = useState(false)
  const apply = async (decision: string) => {
    setBusy(true)
    try {
      await decide(item.id, decision, selected)
    } finally {
      setBusy(false)
    }
  }
  const currentValues = Array.isArray(item.current_value)
    ? item.current_value.map((value) =>
        typeof value === 'string'
          ? value
          : [value.kind, value.label, value.raw].filter(Boolean).join(' · '),
      )
    : []
  const source = item.document_id
    ? `/documents/${item.document_id}`
    : item.entity_type === 'company'
      ? `/companies/${item.entity_id}`
      : '/library/people'
  return (
    <section className="panel proposal-card">
      <div className="panel-heading">
        <div>
          <Link to={source}>
            <h2>{item.record_name || 'Unnamed record'}</h2>
          </Link>
          {item.company_name && item.company_name !== item.record_name && (
            <p>{item.company_name}</p>
          )}
          <p className="caption">
            {item.field.replaceAll('_', ' ')} · {item.actor === 'ai' ? 'AI suggestion' : item.actor}
          </p>
        </div>
        <Badge tone="amber">Needs a decision</Badge>
      </div>
      <p className="muted">{item.reason}</p>
      {item.stale && (
        <p className="notice">
          The record changed after this suggestion was made. Keep the current value or correct it
          beside the source.
        </p>
      )}
      <div className="review-compare">
        <div className="proposal-source">
          {item.source_page ? (
            <SourceViewer page={item.source_page} />
          ) : (
            <p className="caption">No source image is attached to this suggestion.</p>
          )}
          <Link className="text-button" to={source}>
            Open source & edit
            <ArrowRight size={15} />
          </Link>
        </div>
        <div>
          {currentValues.length > 0 && (
            <details className="raw-text" open>
              <summary>Currently stored</summary>
              <ul>
                {currentValues.map((value, index) => (
                  <li key={index}>{value}</li>
                ))}
              </ul>
            </details>
          )}
          <p className="caption">
            Select each change you verified against the source. Syntax checks do not prove that OCR
            read a value correctly.
          </p>
          {item.changes.map((change) => (
            <label className="proposal-change" key={change.index}>
              <input
                type="checkbox"
                aria-label={`${change.operation} ${change.label}: ${change.after || change.before}`}
                checked={selected.includes(change.index)}
                disabled={busy || item.stale || !change.can_accept}
                onChange={(event) =>
                  setSelected((current) =>
                    event.target.checked
                      ? [...current, change.index]
                      : current.filter((index) => index !== change.index),
                  )
                }
              />
              <div>
                <strong>
                  {change.operation === 'add'
                    ? 'Add'
                    : change.operation === 'remove'
                      ? 'Remove'
                      : 'Change'}{' '}
                  {change.label}
                </strong>
                <div className={`review-values ${change.operation !== 'replace' ? 'single' : ''}`}>
                  {change.operation !== 'add' && (
                    <div>
                      <small>Current</small>
                      <p>{change.before || 'Empty'}</p>
                    </div>
                  )}
                  {change.operation !== 'remove' && (
                    <div>
                      <small>Suggested</small>
                      <p>{change.after || 'Empty'}</p>
                    </div>
                  )}
                </div>
                {['phone', 'email'].includes(change.label) &&
                  change.normalised &&
                  change.normalised !== change.after && (
                    <p className="caption">Normalised: {change.normalised}</p>
                  )}
                {change.warning && <p className="notice">{change.warning}</p>}
              </div>
            </label>
          ))}
          {item.duplicate_warnings?.map((message) => (
            <p className="notice" key={message}>
              {message} No duplicate will be added.
            </p>
          ))}
          <p className="caption">
            Only checked changes are applied. Unchecked suggestions are dismissed; other stored
            values stay as they are.
          </p>
          <div className="button-row">
            <Button
              disabled={busy || item.stale || !selected.length}
              onClick={() => {
                void apply('accept')
              }}
            >
              Apply checked changes
            </Button>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                void apply('reject')
              }}
            >
              Keep all current values
            </Button>
          </div>
        </div>
      </div>
      {item.evidence.length > 0 && (
        <details className="raw-text">
          <summary>Printed evidence</summary>
          {item.evidence.map((evidence, index) => (
            <blockquote key={index}>{evidence.quote}</blockquote>
          ))}
        </details>
      )}
    </section>
  )
}

export function ReviewPage() {
  const { activeExpo, refresh } = useLibrary(),
    toast = useToast()
  const query = useQuery({
    queryKey: ['review', activeExpo?.id],
    queryFn: () =>
      api<{
        documents: Document[]
        proposals: Proposal[]
        duplicates: {
          id: string
          entity_type: 'company' | 'contact'
          source_id: string
          candidate_id: string
          reason: string
        }[]
      }>(`/review${activeExpo ? `?expo_id=${activeExpo.id}` : ''}`),
    refetchInterval: 5000,
  })
  const [error, setError] = useState<unknown>(),
    [merge, setMerge] = useState<{
      kind: 'company' | 'contact'
      sourceId: string
      targetId: string
    }>(),
    [focus, setFocus] = useState(0)
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement).matches('input,textarea,select')) return
      if (event.key.toLowerCase() === 'j')
        setFocus((value) => Math.min((query.data?.documents.length ?? 1) - 1, value + 1))
      if (event.key.toLowerCase() === 'k') setFocus((value) => Math.max(0, value - 1))
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [query.data?.documents.length])
  useEffect(() => {
    document
      .getElementById(`review-doc-${focus}`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [focus])
  const decide = async (id: string, decision: string, selected?: number[]) => {
    try {
      await send(`/proposals/${id}/${decision}`, { selected_changes: selected })
      await refresh()
      toast(decision === 'accept' ? 'Correction accepted.' : 'Suggestion dismissed.')
    } catch (error) {
      setError(error)
    }
  }
  const count =
    (query.data?.documents.length ?? 0) +
    (query.data?.proposals.length ?? 0) +
    (query.data?.duplicates.length ?? 0)
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>A closer look</h1>
          <p className="muted">Small uncertainties, ready for your judgement.</p>
        </div>
        <Link className="button secondary" to="/grouping">
          Check photo groups
          <ArrowRight size={16} />
        </Link>
      </div>
      <p className="caption">
        {query.data
          ? `${query.isError ? 'Last known: ' : ''}${query.data.documents.length} documents · ${query.data.proposals.length} suggestions · ${query.data.duplicates.length} possible duplicates`
          : 'Review counts unavailable'}
      </p>
      <ErrorMessage error={error ?? query.error} />
      {query.isPending ? (
        <Loading />
      ) : query.isError ? null : !count ? (
        <Empty
          title="Everything looks good"
          description="When a detail needs your attention, you'll find it here."
        />
      ) : (
        <>
          <div className="review-list">
            {query.data?.proposals.map((item) => (
              <ProposalCard key={item.id} item={item} decide={decide} />
            ))}
          </div>
          {query.data?.documents.map((doc, index) => (
            <section
              id={`review-doc-${index}`}
              className={`panel review-document ${focus === index ? 'focused' : ''}`}
              key={doc.id}
            >
              <div className="panel-heading">
                <Link to={`/documents/${doc.id}`}>
                  <h2>{doc.title}</h2>
                </Link>
                <Badge tone="amber">Needs attention</Badge>
              </div>
              <ul>
                {doc.review_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              <div className="button-row">
                <Link className="button secondary" to={`/documents/${doc.id}`}>
                  Open source & edit
                  <ArrowRight size={16} />
                </Link>
                <Button
                  variant="ghost"
                  disabled={!!doc.pending_changes}
                  title={doc.pending_changes ? 'Decide the suggestions above first' : undefined}
                  onClick={async () => {
                    try {
                      await send(`/review/${doc.id}/resolve`, {})
                      await refresh()
                      toast('Marked as reviewed.')
                    } catch (error) {
                      setError(error)
                    }
                  }}
                >
                  Mark reviewed
                </Button>
              </div>
            </section>
          ))}
          {query.data?.duplicates.map((item) => (
            <section className="panel" key={item.id}>
              <h2>Possible duplicate</h2>
              <p className="muted">{item.reason}</p>
              <div className="button-row">
                <Button
                  variant="secondary"
                  onClick={() =>
                    setMerge({
                      kind: item.entity_type,
                      sourceId: item.source_id,
                      targetId: item.candidate_id,
                    })
                  }
                >
                  Compare records
                </Button>
                <button
                  className="text-button"
                  onClick={async () => {
                    await send(`/duplicates/${item.id}/dismiss`, {})
                    await refresh()
                  }}
                >
                  Keep separate
                </button>
              </div>
            </section>
          ))}
        </>
      )}
      {merge && (
        <MergeDialog
          kind={merge.kind}
          sourceId={merge.sourceId}
          initialTarget={merge.targetId}
          onClose={() => setMerge(undefined)}
        />
      )}
    </>
  )
}
