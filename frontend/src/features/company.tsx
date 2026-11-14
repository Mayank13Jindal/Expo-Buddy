import { formatTime } from '../app/time'
import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Building2, Pencil, History, ArrowLeft, ExternalLink, Plus } from 'lucide-react'
import { api, send, type Document, type Note } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { AddPerson, CompanyNotes } from './company-tools'
import { MergeDialog } from './review'
import {
  Badge,
  DocumentStatus,
  Button,
  ErrorMessage,
  Field,
  Loading,
  Modal,
} from '../components/ui'

export type Channel = {
  kind: string
  label: string
  raw: string
  evidence?: { page_id: string; quote: string }
}
export type Contact = {
  id: string
  full_name: string
  designation: string
  department: string
  channels: Channel[]
  review_warning?: string
}
export type Company = {
  review_warning?: string
  id: string
  updated_at: string
  display_name: string
  website: string
  description: string
  business_role: string
  products: string[]
  services: string[]
  categories: string[]
  aliases: string[]
  channels: Channel[]
  contacts: Contact[]
  documents: Document[]
  notes: Note[]
  appearances?: { expo_id: string; document_id: string }[]
  tags?: { id: string; label: string }[]
  processed_by?: { provider: string; cloud: boolean }[]
  field_sources: { field: string; source: string; evidence: { page_id: string; quote: string }[] }[]
}

export function RecordEditor({
  kind,
  record,
  open,
  onOpenChange,
}: {
  kind: 'company' | 'contact'
  record: Company | Contact
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { refresh } = useLibrary(),
    toast = useToast()
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false)
  const fields =
    kind === 'company'
      ? [
          'display_name',
          'website',
          'description',
          'business_role',
          'products',
          'services',
          'categories',
        ]
      : ['full_name', 'designation', 'department']
  const [channels, setChannels] = useState(record.channels),
    [wasOpen, setWasOpen] = useState(open)
  // Reset the draft only when the dialog opens, so edits survive background refreshes.
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setChannels(record.channels)
      setError(undefined)
    }
  }
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    const data = new FormData(event.currentTarget)
    const updates = Object.fromEntries(
      fields.map((field) => [
        field,
        ['products', 'services', 'categories'].includes(field)
          ? String(data.get(field) ?? '')
              .split('\n')
              .map((value) => value.trim())
              .filter(Boolean)
          : (data.get(field) ?? ''),
      ]),
    )
    try {
      await send(
        `/${kind === 'company' ? 'companies' : 'contacts'}/${record.id}`,
        { fields: { ...updates, channels: channels.filter((channel) => channel.raw.trim()) } },
        'PATCH',
      )
      await refresh()
      onOpenChange(false)
      toast('Your corrections are saved and protected.')
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={kind === 'company' ? 'Edit company' : 'Edit person'}
      description="Your corrections are kept during reprocessing."
    >
      <form onSubmit={submit}>
        {fields.map((field) => {
          const value = (record as unknown as Record<string, unknown>)[field]
          return (
            <Field
              key={field}
              label={field.replaceAll('_', ' ').replace(/^./, (char) => char.toUpperCase())}
            >
              {['description', 'products', 'services', 'categories'].includes(field) ? (
                <textarea
                  name={field}
                  rows={3}
                  defaultValue={Array.isArray(value) ? value.join('\n') : String(value ?? '')}
                />
              ) : (
                <input
                  name={field}
                  maxLength={field === 'website' ? 2000 : 300}
                  defaultValue={String(value ?? '')}
                />
              )}
            </Field>
          )
        })}
        <h3>Contact details</h3>
        {channels.map((channel, index) => (
          <div className="channel-edit" key={index}>
            <select
              aria-label={`Type of detail ${index + 1}`}
              value={channel.kind}
              onChange={(event) =>
                setChannels((items) =>
                  items.map((item, i) =>
                    i === index ? { ...item, kind: event.target.value } : item,
                  ),
                )
              }
            >
              <option value="phone">Phone</option>
              <option value="email">Email</option>
              <option value="web">Website</option>
              <option value="address">Address</option>
            </select>
            <input
              aria-label={`Label of detail ${index + 1}`}
              value={channel.label}
              placeholder="Label"
              onChange={(event) =>
                setChannels((items) =>
                  items.map((item, i) =>
                    i === index ? { ...item, label: event.target.value } : item,
                  ),
                )
              }
            />
            {channel.kind === 'address' ? (
              <textarea
                aria-label={`Value of detail ${index + 1}`}
                rows={3}
                value={channel.raw}
                onChange={(event) =>
                  setChannels((items) =>
                    items.map((item, i) =>
                      i === index ? { ...item, raw: event.target.value } : item,
                    ),
                  )
                }
              />
            ) : (
              <input
                aria-label={`Value of detail ${index + 1}`}
                value={channel.raw}
                onChange={(event) =>
                  setChannels((items) =>
                    items.map((item, i) =>
                      i === index ? { ...item, raw: event.target.value } : item,
                    ),
                  )
                }
              />
            )}
            <button
              type="button"
              className="icon-button"
              aria-label="Remove contact detail"
              onClick={() => setChannels((items) => items.filter((_, i) => i !== index))}
            >
              ×
            </button>
          </div>
        ))}
        <Button
          type="button"
          variant="ghost"
          onClick={() => setChannels((items) => [...items, { kind: 'phone', label: '', raw: '' }])}
        >
          <Plus size={15} />
          Add contact detail
        </Button>
        <ErrorMessage error={error} />
        <div className="form-actions">
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={busy}>{busy ? 'Saving…' : 'Save corrections'}</Button>
        </div>
      </form>
    </Modal>
  )
}

export function CompanyPanel({ id }: { id: string }) {
  const query = useQuery({
    queryKey: ['company', id],
    queryFn: () => api<Company>(`/companies/${id}`),
  })
  const [edit, setEdit] = useState(false),
    [person, setPerson] = useState<Contact>(),
    [mergePerson, setMergePerson] = useState<Contact>()
  const company = query.data
  if (!company) return <ErrorMessage error={query.error} />
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <h2>
            <Building2 size={18} />
            {company.display_name}
          </h2>
          <button className="icon-button" aria-label="Edit company" onClick={() => setEdit(true)}>
            <Pencil size={16} />
          </button>
        </div>
        {company.processed_by?.some((run) => run.cloud) && (
          <Badge>Some details processed in cloud</Badge>
        )}
        {company.website && <p className="record-description">{company.website}</p>}
        {company.tags?.map((tag) => (
          <Badge key={tag.id}>{tag.label}</Badge>
        ))}
        {company.description && <p className="record-description">{company.description}</p>}
        {company.business_role && <Badge>{company.business_role}</Badge>}
        {['products', 'services', 'categories'].map((key) => (
          <div className="record-field" key={key}>
            <strong>{key[0].toUpperCase() + key.slice(1)}</strong>
            <p>{(company[key as keyof Company] as string[]).join(' · ') || 'Not added'}</p>
          </div>
        ))}
        {company.review_warning && <p className="notice">{company.review_warning}</p>}
        <ChannelList values={company.channels} />
        <Link to={`/companies/${id}`} className="text-button">
          Company details & history
          <ExternalLink size={14} />
        </Link>
        <RecordEditor
          key={(company.updated_at as string) ?? company.id}
          kind="company"
          record={company}
          open={edit}
          onOpenChange={setEdit}
        />
      </section>
      <AddPerson companyId={company.id} documents={company.documents} />
      {company.contacts.map((contact) => (
        <section className="panel" key={contact.id}>
          <div className="panel-heading">
            <div>
              <h2>{contact.full_name}</h2>
              <p>{[contact.designation, contact.department].filter(Boolean).join(' · ')}</p>
            </div>
            <button
              className="icon-button"
              aria-label={`Edit ${contact.full_name}`}
              onClick={() => setPerson(contact)}
            >
              <Pencil size={16} />
            </button>
          </div>
          {contact.review_warning && <p className="notice">{contact.review_warning}</p>}
          <ChannelList values={contact.channels} />
          <button className="text-button" onClick={() => setMergePerson(contact)}>
            Compare and merge this person
          </button>
        </section>
      ))}
      {mergePerson && (
        <MergeDialog
          kind="contact"
          sourceId={mergePerson.id}
          onClose={() => setMergePerson(undefined)}
        />
      )}
      {person && (
        <RecordEditor
          kind="contact"
          record={person}
          open
          onOpenChange={(open) => {
            if (!open) setPerson(undefined)
          }}
        />
      )}
    </>
  )
}

function historyText(value: unknown): string {
  if (typeof value === 'string') return value || 'Empty'
  if (Array.isArray(value))
    return (
      value
        .map((item) =>
          typeof item === 'string'
            ? item
            : item && typeof item === 'object'
              ? [item.kind, item.label, item.raw].filter(Boolean).join(' · ')
              : '',
        )
        .join('\n') || 'Empty'
    )
  return value == null ? 'Empty' : 'Record details'
}

export function ChannelList({ values }: { values: Channel[] }) {
  return (
    <div className="channel-list">
      {values.map((channel, index) => (
        <div key={index}>
          <small>{channel.label || channel.kind}</small>
          <p>{channel.raw}</p>
        </div>
      ))}
    </div>
  )
}

export function CompanyPage() {
  const { id } = useParams(),
    { refresh } = useLibrary(),
    toast = useToast(),
    navigate = useNavigate()
  const [mergeOpen, setMergeOpen] = useState(false)
  const query = useQuery({
    queryKey: ['company', id],
    queryFn: () => api<Company>(`/companies/${id}`),
  })
  const history = useQuery({
    queryKey: ['company-history', id],
    queryFn: () =>
      api<
        {
          id: string
          field: string
          old: unknown
          new: unknown
          actor: string
          created_at: string
          undone_at: string | null
        }[]
      >(`/companies/${id}/history`),
  })
  if (query.isPending) return <Loading />
  return (
    <>
      <Link className="back-link" to="/library">
        <ArrowLeft size={16} />
        Back to library
      </Link>
      <div className="page-heading">
        <div>
          <h1>{query.data?.display_name}</h1>
        </div>
        <Button variant="secondary" onClick={() => setMergeOpen(true)}>
          Compare and merge company
        </Button>
      </div>
      {mergeOpen && (
        <MergeDialog kind="company" sourceId={id!} onClose={() => setMergeOpen(false)} />
      )}
      <div className="detail-columns">
        <div>
          <CompanyPanel id={id!} />
          <CompanyNotes id={id!} notes={query.data?.notes ?? []} />
          <section className="panel">
            <h2>Related documents & expo appearances</h2>
            {query.data?.documents.map((doc) => (
              <Link className="recent-row" key={doc.id} to={`/documents/${doc.id}`}>
                <span>{doc.title}</span>
                <DocumentStatus document={doc} />
                <ExternalLink size={15} />
              </Link>
            ))}
          </section>
        </div>
        <div>
          <section className="panel">
            <h2>Where the details came from</h2>
            {query.data?.field_sources.map((source) => (
              <div className="source-evidence" key={source.field}>
                <strong>{source.field.replaceAll('_', ' ')}</strong>
                <Badge tone={source.source === 'user' ? 'green' : ''}>
                  {source.source === 'user' ? 'Your correction' : 'Printed source'}
                </Badge>
                {source.evidence.map((item, index) => (
                  <blockquote key={index}>
                    <button
                      className="evidence-link"
                      onClick={async () => {
                        const location = await api<{
                          document_id: string
                          page_id: string
                          asset_id?: string
                          revision?: number
                          box?: number[][]
                        }>(
                          `/pages/${item.page_id}/location?quote=${encodeURIComponent(item.quote)}`,
                        )
                        const params = new URLSearchParams({
                          page: location.page_id,
                          ...(location.asset_id ? { asset: location.asset_id } : {}),
                          ...(location.revision ? { revision: String(location.revision) } : {}),
                          ...(location.box ? { box: JSON.stringify(location.box) } : {}),
                        })
                        navigate(`/documents/${location.document_id}?${params}`)
                      }}
                    >
                      {item.quote}
                      <small>Open source page ↗</small>
                    </button>
                  </blockquote>
                ))}
              </div>
            ))}
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>
                <History size={18} />
                Edit history
              </h2>
            </div>
            {history.data?.map((item) => (
              <div className="history-row" key={item.id}>
                <strong>
                  {item.field === '__merge__' ? 'Records merged' : item.field.replaceAll('_', ' ')}
                </strong>
                <small>
                  {item.actor} · {formatTime(item.created_at)}
                </small>
                <div className="history-values">
                  <p>
                    <strong>Before:</strong> {historyText(item.old)}
                  </p>
                  <p>
                    <strong>After:</strong> {historyText(item.new)}
                  </p>
                </div>
                <details>
                  <summary>Technical details</summary>
                  <pre>{JSON.stringify({ before: item.old, after: item.new }, null, 2)}</pre>
                </details>
                {!item.undone_at && item.actor === 'owner' && (
                  <button
                    className="text-button"
                    onClick={async () => {
                      try {
                        await send(`/history/${item.id}/undo`, {})
                        await refresh()
                        toast('Change undone.')
                      } catch (error) {
                        toast((error as Error).message)
                      }
                    }}
                  >
                    Undo this change
                  </button>
                )}
              </div>
            ))}
          </section>
        </div>
      </div>
    </>
  )
}
