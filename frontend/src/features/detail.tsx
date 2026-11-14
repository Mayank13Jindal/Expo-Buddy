import { CheckedExample } from './accuracy'
import { AIReprocess, ProcessingProgress, FieldReview } from './ai-tools'
import { formatTime, formatDate } from '../app/time'
import { useEffect, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Download, FileText, StickyNote, Trash2, RotateCcw } from 'lucide-react'
import { api, ApiError, send, type Document, type Note } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { SourceTools } from './source-tools'
import { SourceViewer } from './source-viewer'
import { LinkCompany } from './company-tools'
import { CompanyPanel } from './company'
import {
  Badge,
  DocumentStatus,
  Button,
  ErrorMessage,
  Field,
  Loading,
  Modal,
  stateLabel,
} from '../components/ui'

export function DetailPage() {
  const { id } = useParams(),
    { refresh, expos } = useLibrary(),
    toast = useToast(),
    navigate = useNavigate()
  const query = useQuery({
    queryKey: ['document', id],
    queryFn: () => api<Document>(`/documents/${id}`),
    refetchInterval: 5000,
  })
  const text = useQuery({
    queryKey: ['document-text', id],
    queryFn: () =>
      api<{ pages: { page_id: string; text: string; engine: string }[] }>(`/documents/${id}/text`),
    refetchInterval: 5000,
  })
  const [page, setPage] = useState(0),
    [note, setNote] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(),
    [confirm, setConfirm] = useState(false)
  const [params] = useSearchParams()
  const doc = query.data,
    currentSource = doc?.pages?.[page]
  const historical = useQuery({
    queryKey: ['asset', params.get('asset')],
    enabled: !!params.get('asset'),
    queryFn: () => api<import('../api/client').Asset>(`/assets/${params.get('asset')}`),
  })
  const source =
    currentSource && historical.data && params.get('asset')
      ? { ...currentSource, asset_id: historical.data.id, asset: historical.data }
      : currentSource
  useEffect(() => {
    const index = doc?.pages?.findIndex((page) => page.id === params.get('page'))
    if (index !== undefined && index >= 0) setPage(index)
  }, [doc?.pages?.length, params])
  let box: number[][] | undefined
  try {
    const value = JSON.parse(params.get('box') ?? 'null')
    if (
      Array.isArray(value) &&
      value.every(
        (point) =>
          Array.isArray(point) &&
          point.length === 2 &&
          point.every((x: unknown) => typeof x === 'number' && Number.isFinite(x)),
      )
    )
      box = value
  } catch {}
  const saveNote = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    try {
      await send('/notes', { document_id: id, text: note })
      setNote('')
      await refresh()
      toast('Note saved.')
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  if (query.isPending) return <Loading />
  if (!doc)
    return (
      <>
        <h1>
          {query.error instanceof ApiError && [404, 422].includes(query.error.status)
            ? 'Document not found'
            : 'Could not load document'}
        </h1>
        <ErrorMessage error={query.error} />
        <Link className="button secondary" to="/library">
          Back to library
        </Link>
        <Button
          variant="ghost"
          onClick={() => {
            void query.refetch()
          }}
        >
          Retry
        </Button>
      </>
    )
  return (
    <>
      <Link className="back-link" to="/library">
        <ArrowLeft size={16} />
        Back to library
      </Link>
      <div className="page-heading detail-heading">
        <div>
          <h1>{doc.title}</h1>
          <div className="badge-row">
            <DocumentStatus document={doc} />
            <Badge tone={doc.group_state === 'confirmed' ? '' : 'amber'}>
              {stateLabel(doc.group_state)}
            </Badge>
          </div>
        </div>
        <div className="button-row">
          <AIReprocess document={doc} />
          <Link className="button secondary" to={`/exports?ids=${doc.id}`}>
            Export
          </Link>
          <Button variant="ghost" onClick={() => setConfirm(true)}>
            <Trash2 size={17} />
            Trash
          </Button>
        </div>
      </div>
      <ProcessingProgress id={doc.id} state={doc.processing_state} />
      {doc.processing_state === 'waiting_grouping' && (
        <p className="notice">
          <Link className="text-button" to="/grouping">
            Confirm photo groups to start AI extraction
          </Link>
          .
        </p>
      )}
      <div className="detail-columns">
        <section className="panel source-panel">
          <div className="panel-heading">
            <h2>Source</h2>
            {source && (
              <a className="text-button" href={`/api/v1/assets/${source.asset_id}/original`}>
                <Download size={15} />
                Original
              </a>
            )}
          </div>
          <div className="source-viewer">
            {['removing', 'removed'].includes(doc.processing_state) ? (
              <p className="notice">
                Original files are being removed or have been permanently removed.
              </p>
            ) : source ? (
              <SourceViewer
                page={source}
                revision={Number(params.get('revision')) || source.preview_revision || undefined}
                box={box}
              />
            ) : (
              <p className="caption">A preview is being prepared.</p>
            )}
          </div>
          {(doc.pages?.length ?? 0) > 1 && (
            <div className="page-strip">
              {doc.pages?.map((item, index) => (
                <button
                  className={page === index ? 'active' : ''}
                  key={item.id}
                  onClick={() => setPage(index)}
                >
                  Page {index + 1}
                </button>
              ))}
            </div>
          )}
          <p className="caption">Original files are kept untouched.</p>
          {source && !['removing', 'removed'].includes(doc.processing_state) && (
            <SourceTools document={doc} page={source} />
          )}
          <details className="raw-text">
            <summary>Printed text</summary>
            {text.data?.pages.map((item) => (
              <div key={item.page_id}>
                <p className="caption">{item.engine}</p>
                <pre>{item.text}</pre>
              </div>
            ))}
            {!text.data?.pages.length && <p className="muted">Text is being read.</p>}
          </details>
        </section>
        <div>
          {doc.company_id && <FieldReview companyId={doc.company_id} documentId={doc.id} />}
          {doc.company_id && <CompanyPanel id={doc.company_id} />}
          <section className="panel">
            <div className="panel-heading">
              <h2>Document details</h2>
              <Badge>{stateLabel(doc.review_status ?? doc.review_state)}</Badge>
            </div>
            <LinkCompany documentId={doc.id} />
            <Field label="Title">
              <input
                id="document-title"
                defaultValue={doc.title}
                key={doc.title}
                onBlur={(event) => {
                  if (event.target.value !== doc.title)
                    void send(`/documents/${id}`, { title: event.target.value }, 'PATCH')
                      .then(refresh)
                      .catch((error) => toast(error.message))
                }}
              />
            </Field>
            <Field label="Type">
              <select
                value={doc.type}
                onChange={(event) => {
                  void send(`/documents/${id}`, { type: event.target.value }, 'PATCH').then(refresh)
                }}
              >
                <option value="other">Other</option>
                <option value="card">Visiting card</option>
                <option value="brochure">Brochure</option>
              </select>
            </Field>
            <Button
              variant="secondary"
              disabled={!!doc.pending_changes}
              title={
                doc.pending_changes ? 'Decide outstanding suggestions in Review first' : undefined
              }
              onClick={async () => {
                try {
                  await send(`/documents/${id}`, { review_state: 'reviewed' }, 'PATCH')
                  await refresh()
                  toast('Marked as reviewed.')
                } catch (error) {
                  toast((error as Error).message)
                }
              }}
            >
              Mark reviewed
            </Button>
            {!!doc.pending_changes && (
              <p className="caption">
                <Link className="text-button" to="/review">
                  Decide outstanding suggestions in Review first ↗
                </Link>
              </p>
            )}
            <CheckedExample
              id={doc.id}
              reviewed={(doc.review_status ?? doc.review_state) === 'reviewed'}
            />
            {doc.review_reasons?.map((reason) => (
              <p className="notice" key={reason}>
                {reason}
              </p>
            ))}
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <StickyNote size={18} /> Your notes
              </h2>
            </div>
            <p className="caption">
              Notes added here stay private. Capture notes and reprocessing instructions are shared
              only when entered in those flows.
            </p>
            <div className="note-list">
              {doc.notes?.map((item) => (
                <div className="note" key={item.id}>
                  <p>{item.text}</p>
                  <small>
                    {formatDate(item.created_at)} · {item.origin}
                  </small>
                  <button
                    className="icon-button"
                    aria-label="Delete note"
                    onClick={async () => {
                      await api(`/notes/${item.id}`, { method: 'DELETE' })
                      await refresh()
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
            <form onSubmit={saveNote}>
              <textarea
                aria-label="New note"
                required
                placeholder="What would you like to remember?"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                maxLength={20000}
              />
              <ErrorMessage error={error} />
              <Button type="submit" variant="secondary" disabled={busy || !note.trim()}>
                {busy ? 'Saving…' : 'Add note'}
              </Button>
            </form>
          </section>
        </div>
      </div>
      <Modal
        open={confirm}
        onOpenChange={setConfirm}
        title="Move this document to Trash?"
        description="You can restore it later. Original files are kept."
      >
        <div className="form-actions">
          <Button variant="secondary" onClick={() => setConfirm(false)}>
            Keep document
          </Button>
          <Button
            variant="danger"
            onClick={async () => {
              await api(`/documents/${id}`, { method: 'DELETE' })
              toast('Moved to Trash.', () => {
                void send(`/documents/${id}/restore`, {}).then(refresh)
              })
              navigate('/library')
              await refresh()
            }}
          >
            Move to Trash
          </Button>
        </div>
      </Modal>
    </>
  )
}
