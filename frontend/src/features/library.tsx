import { LibraryTabs } from './library-tabs'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  BookmarkPlus,
  Check,
  Trash2,
  Tag,
  FolderInput,
  Grid2X2,
  List,
  Plus,
  FileText,
  ArrowUpRight,
  Search,
} from 'lucide-react'
import { api, send, type Document } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { TrashActions } from './trash'
import {
  Badge,
  DocumentStatus,
  Button,
  Empty,
  ErrorMessage,
  Field,
  Loading,
  Modal,
  stateLabel,
} from '../components/ui'

export function LibraryPage() {
  const { activeExpo, expos, refresh } = useLibrary()
  const toast = useToast()
  const [moveOpen, setMoveOpen] = useState(false),
    [moveExpo, setMoveExpo] = useState('')
  const [selected, setSelected] = useState<string[]>([]),
    [reviewState, setReviewState] = useState(''),
    [tag, setTag] = useState(''),
    [category, setCategory] = useState(''),
    [companyId, setCompanyId] = useState(''),
    [processedBy, setProcessedBy] = useState('')
  const saved = useQuery({
    queryKey: ['saved-searches'],
    queryFn: () =>
      api<{ id: string; name: string; query: string; filters: Record<string, string> }[]>(
        '/saved-searches',
      ),
  })
  const bulk = async (action: string, destination?: string) => {
    const body: Record<string, unknown> = { action, document_ids: selected }
    if (action === 'tag') {
      const label = prompt('Tag for the selected documents')
      if (!label) return
      body.labels = label
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
    }
    if (action === 'move_expo') {
      if (!destination) {
        setMoveOpen(true)
        return
      }
      body.expo_id = destination
    }
    try {
      const result = await send<{ action_id: string }>('/bulk', body)
      setSelected([])
      setMoveOpen(false)
      await refresh()
      toast('Documents updated.', () => {
        void send(`/bulk/${result.action_id}/undo`, {}).then(refresh)
      })
    } catch (error) {
      toast((error as Error).message)
    }
  }
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [all, setAll] = useState(false),
    [related, setRelated] = useState(false),
    [type, setType] = useState(''),
    [grid, setGrid] = useState(true),
    [trash, setTrash] = useState(false)
  const filters = {
    ...(type ? { type } : {}),
    ...(reviewState ? { review_state: reviewState } : {}),
    ...(tag ? { tag } : {}),
    ...(category ? { category } : {}),
    ...(companyId ? { company_id: companyId } : {}),
    ...(processedBy ? { processed_by: processedBy } : {}),
  }
  const query = useQuery({
    queryKey: ['documents', all ? undefined : activeExpo?.id, filters, trash],
    queryFn: () =>
      api<Document[]>(
        `/documents?${new URLSearchParams({ ...(activeExpo && !all ? { expo_id: activeExpo.id } : {}), ...filters, trash: String(trash) })}`,
      ),
  })
  const term = params.get('q') ?? ''
  const filtered = !!(type || reviewState || tag || category || companyId || processedBy)
  const clearFilters = () => {
    setParams({})
    setType('')
    setReviewState('')
    setTag('')
    setCategory('')
    setCompanyId('')
    setProcessedBy('')
    setRelated(false)
  }
  const search = useQuery({
    queryKey: ['search', term, related, all, activeExpo?.id, filters],
    enabled: !!term.trim(),
    queryFn: () =>
      api<{
        results: {
          id: string
          document_id?: string
          title: string
          company_id?: string
          expo_id: string
          snippet: string
          source_type: string
          match_kind: string
          processing_state: string
          type: string
          provisional: boolean
        }[]
      }>(
        `/search?${new URLSearchParams({ q: term, include_related: String(related), scope: all ? 'all' : 'active', ...filters, ...(activeExpo && !all ? { expo_id: activeExpo.id } : {}), ...(type ? { type } : {}) })}`,
      ),
  })
  const resultState = term.trim() ? search : query
  const docs:
    (Document & { snippet?: string; match_kind?: string; destination?: string })[] | undefined =
    term.trim()
      ? search.data?.results.map((hit) => ({
          id: hit.document_id ?? hit.id,
          title: hit.title,
          expo_id: hit.expo_id,
          type: hit.type,
          group_state: hit.provisional ? 'suggested' : 'confirmed',
          processing_state: hit.processing_state ?? 'ready',
          match_kind: hit.match_kind,
          review_state: (hit as any).review_state ?? 'unreviewed',
          review_status: (hit as any).review_status,
          pending_changes: (hit as any).pending_changes,
          review_reasons: [],
          created_at: '',
          snippet: hit.snippet,
          destination: hit.document_id
            ? `/documents/${hit.document_id}`
            : hit.company_id
              ? `/companies/${hit.company_id}`
              : '/expos',
        }))
      : query.data
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>The library</h1>
          <p className="muted">Find the right connection, when you need it.</p>
        </div>
        <Link className="button secondary" to="/library/companies">
          Companies
        </Link>
        <Button onClick={() => navigate('/capture')}>
          <Plus size={18} />
          Add files
        </Button>
      </div>
      <LibraryTabs />
      <div className="library-toolbar">
        <div className="search-field">
          <Search size={17} />
          <input
            aria-label="Filter library"
            value={term}
            onChange={(event) => setParams(event.target.value ? { q: event.target.value } : {})}
            placeholder="Search cards, companies, people…"
          />
        </div>
        <select
          aria-label="Document type"
          value={type}
          onChange={(event) => setType(event.target.value)}
        >
          <option value="">All types</option>
          <option value="card">Visiting cards</option>
          <option value="brochure">Brochures</option>
          <option value="other">Other files</option>
        </select>
        <label className="checkbox-label">
          <input type="checkbox" checked={all} onChange={(event) => setAll(event.target.checked)} />
          All expos
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={related}
            onChange={(event) => setRelated(event.target.checked)}
          />
          Include related meanings
        </label>
        <div className="view-toggle">
          <button
            className={grid ? 'active' : ''}
            aria-label="Grid view"
            onClick={() => setGrid(true)}
          >
            <Grid2X2 size={18} />
          </button>
          <button
            className={!grid ? 'active' : ''}
            aria-label="List view"
            onClick={() => setGrid(false)}
          >
            <List size={19} />
          </button>
        </div>
      </div>
      <details className="library-filters">
        <summary>More filters</summary>
        <div className="form-grid">
          <Field label="Review">
            <select value={reviewState} onChange={(event) => setReviewState(event.target.value)}>
              <option value="">Any review state</option>
              <option value="needs_attention">Needs attention</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="reviewed">Reviewed</option>
            </select>
          </Field>
          <Field label="Tag">
            <input value={tag} onChange={(event) => setTag(event.target.value)} />
          </Field>
          <Field label="Category">
            <input value={category} onChange={(event) => setCategory(event.target.value)} />
          </Field>
          <Field label="Company ID">
            <input
              value={companyId}
              onChange={(event) => setCompanyId(event.target.value)}
              placeholder="From company details"
            />
          </Field>
          <Field label="Processed by">
            <select value={processedBy} onChange={(event) => setProcessedBy(event.target.value)}>
              <option value="">Any provider</option>
              <option value="local">Local</option>
              <option value="cloud">Cloud</option>
            </select>
          </Field>
        </div>
      </details>
      <div className="saved-search-bar">
        {saved.data?.map((item) => (
          <button
            className="badge"
            key={item.id}
            onClick={() => {
              setParams({ q: item.query })
              setAll(item.filters.scope === 'all')
              setType(item.filters.type ?? '')
              setReviewState(item.filters.review_state ?? '')
              setTag(item.filters.tag ?? '')
              setCategory(item.filters.category ?? '')
              setCompanyId(item.filters.company_id ?? '')
              setProcessedBy(item.filters.processed_by ?? '')
            }}
          >
            {item.name}
          </button>
        ))}
        {term && (
          <button
            className="text-button"
            onClick={async () => {
              const name = prompt('Name this search', term)
              if (name) {
                await send('/saved-searches', {
                  name,
                  query: term,
                  filters: { scope: all ? 'all' : 'active', ...filters },
                })
                await refresh()
                toast('Search saved.')
              }
            }}
          >
            <BookmarkPlus size={15} />
            Save search
          </button>
        )}
      </div>
      {selected.length > 0 && (
        <div className="bulk-bar">
          <strong>{selected.length} selected</strong>
          <Button
            variant="secondary"
            onClick={() => {
              void bulk('review')
            }}
          >
            <Check size={15} />
            Reviewed
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              void bulk('tag')
            }}
          >
            <Tag size={15} />
            Tag
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              void bulk('move_expo')
            }}
          >
            <FolderInput size={15} />
            Move expo
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              void bulk('trash')
            }}
          >
            <Trash2 size={15} />
            Trash
          </Button>
          <Link className="button secondary" to={`/exports?ids=${selected.join(',')}`}>
            Export
          </Link>
          <button className="text-button" onClick={() => setSelected([])}>
            Clear
          </button>
        </div>
      )}
      <div className="results-meta">
        <span>
          {resultState.isPending
            ? 'Loading results…'
            : resultState.isError
              ? 'Results unavailable'
              : `${docs?.length ?? 0} ${term.trim() ? 'results' : 'documents'}`}
          {!all && activeExpo ? ` · ${activeExpo.name}` : ''}
        </span>
        <button className="text-button" onClick={() => setTrash(!trash)}>
          {trash ? 'Back to library' : 'Trash'}
        </button>
      </div>
      <ErrorMessage error={term.trim() ? search.error : query.error} />
      {(term.trim() ? search.isPending : query.isPending) ? (
        <Loading />
      ) : (term.trim() ? search.isError : query.isError) ? null : docs?.length ? (
        <div className={grid ? 'document-grid' : 'document-list'}>
          {docs.map((doc) => (
            <article className="document-card" key={doc.id}>
              <input
                type="checkbox"
                className="document-select"
                disabled={!!doc.destination && !doc.destination.startsWith('/documents/')}
                aria-label={`Select ${doc.title}`}
                checked={selected.includes(doc.id)}
                onClick={(event) => {
                  event.stopPropagation()
                }}
                onChange={(event) => {
                  setSelected((items) =>
                    event.target.checked ? [...items, doc.id] : items.filter((id) => id !== doc.id),
                  )
                }}
              />
              <Link className="document-link" to={doc.destination ?? `/documents/${doc.id}`}>
                <div className="document-cover">
                  {doc.thumbnail_asset_id ? (
                    <img
                      loading="lazy"
                      src={`/api/v1/assets/${doc.thumbnail_asset_id}/thumbnail`}
                      onError={(event) => {
                        event.currentTarget.style.display = 'none'
                      }}
                      alt=""
                    />
                  ) : null}
                  <FileText size={35} strokeWidth={1.2} />
                  <span>{doc.type === 'card' ? 'VISITING CARD' : doc.type.toUpperCase()}</span>
                </div>
                <div className="document-info">
                  <div className="document-title">
                    <h2>{doc.title}</h2>
                    <ArrowUpRight size={16} />
                  </div>
                  <p>{doc.snippet ?? expos.find((expo) => expo.id === doc.expo_id)?.name}</p>
                  <div>
                    {doc.match_kind && (
                      <span className="caption">
                        {doc.match_kind === 'semantic'
                          ? 'Related meaning · verify source'
                          : doc.match_kind === 'exact'
                            ? 'Exact contact match'
                            : 'Text match'}
                      </span>
                    )}
                    {['company', 'person', 'note'].includes(doc.type) ? (
                      <span className="caption">
                        {doc.type === 'note'
                          ? 'Personal note'
                          : doc.type === 'person'
                            ? 'Person record'
                            : 'Company record'}
                      </span>
                    ) : (
                      <DocumentStatus document={doc} />
                    )}
                    {doc.group_state === 'suggested' && (
                      <span className="caption">Provisional</span>
                    )}
                  </div>
                </div>
              </Link>
              {trash && <TrashActions id={doc.id} />}
            </article>
          ))}
        </div>
      ) : (
        <Empty
          title={
            term || filtered
              ? 'No matching records'
              : trash
                ? 'Trash is empty'
                : 'Room for your next discovery'
          }
          description={
            term || filtered
              ? 'Try another search, clear the filters, or switch to all expos.'
              : trash
                ? 'Documents moved to Trash will appear here. You can restore them before permanent removal.'
                : 'Add cards and brochures from your expo. They’ll appear here as soon as they’re saved.'
          }
          action={
            term || filtered ? (
              <Button variant="secondary" onClick={clearFilters}>
                Clear filters
              </Button>
            ) : (
              !trash && (
                <Button variant="secondary" onClick={() => navigate('/capture')}>
                  Add your first files
                </Button>
              )
            )
          }
        />
      )}
      <Modal
        open={moveOpen}
        onOpenChange={setMoveOpen}
        title="Move selected documents"
        description="Choose the expo these documents belong to."
      >
        <Field label="Destination expo">
          <select value={moveExpo} onChange={(event) => setMoveExpo(event.target.value)}>
            <option value="">Choose an expo</option>
            {expos.map((expo) => (
              <option value={expo.id} key={expo.id}>
                {expo.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="form-actions">
          <Button variant="secondary" onClick={() => setMoveOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={!moveExpo}
            onClick={() => {
              void bulk('move_expo', moveExpo)
            }}
          >
            Move documents
          </Button>
        </div>
      </Modal>
    </>
  )
}
