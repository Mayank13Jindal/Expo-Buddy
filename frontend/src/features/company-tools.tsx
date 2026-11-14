import { LibraryTabs } from './library-tabs'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Building2, Plus, Search, StickyNote } from 'lucide-react'
import { api, send, type Note } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, Empty, ErrorMessage, Field, Modal } from '../components/ui'
import type { CompanySummary } from '../api/types'

export function LinkCompany({ documentId }: { documentId: string }) {
  const { refresh } = useLibrary(),
    toast = useToast(),
    [open, setOpen] = useState(false),
    [selected, setSelected] = useState(''),
    [name, setName] = useState(''),
    [error, setError] = useState<unknown>()
  const companies = useQuery({
    queryKey: ['company-choices'],
    enabled: open,
    queryFn: () => api<CompanySummary[]>('/companies'),
  })
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Link a company
      </Button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Link this document to a company"
        description="Use an existing company or add its name yourself."
      >
        <Field label="Existing company">
          <select value={selected} onChange={(event) => setSelected(event.target.value)}>
            <option value="">Choose a company</option>
            {companies.data?.map((row) => (
              <option key={row.id} value={row.id}>
                {row.display_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Or create company">
          <input value={name} maxLength={300} onChange={(event) => setName(event.target.value)} />
        </Field>
        <ErrorMessage error={error} />
        <Button
          disabled={!selected && !name.trim()}
          onClick={async () => {
            try {
              const id = name.trim()
                ? (
                    await send<{ id: string }>('/companies', {
                      fields: { display_name: name.trim() },
                    })
                  ).id
                : selected
              await send(`/documents/${documentId}/attach-company`, { company_id: id })
              await refresh()
              setOpen(false)
              toast('Company linked.')
            } catch (error) {
              setError(error)
            }
          }}
        >
          Link company
        </Button>
      </Modal>
    </>
  )
}
export function CompanyNotes({ id, notes }: { id: string; notes: Note[] }) {
  const { refresh } = useLibrary(),
    [text, setText] = useState(''),
    [error, setError] = useState<unknown>()
  return (
    <section className="panel">
      <h2>
        <StickyNote size={18} />
        Personal notes
      </h2>
      {notes.map((note) => (
        <div className="note" key={note.id}>
          <p>{note.text}</p>
          <small>{note.origin}</small>
        </div>
      ))}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void send('/notes', { company_id: id, text })
            .then(async () => {
              setText('')
              await refresh()
            })
            .catch(setError)
        }}
      >
        <Field label="New company note">
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={20000}
            required
            rows={3}
          />
        </Field>
        <ErrorMessage error={error} />
        <Button variant="secondary" disabled={!text.trim()}>
          Add note
        </Button>
      </form>
      <p className="caption">These notes are searchable and are never sent to document AI.</p>
    </section>
  )
}
export function AddPerson({
  companyId,
  documents,
}: {
  companyId: string
  documents: { id: string; title: string }[]
}) {
  const { refresh } = useLibrary(),
    [open, setOpen] = useState(false),
    [error, setError] = useState<unknown>()
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <Plus size={16} />
        Add a person
      </Button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Add a person"
        description="Enter what you know. Missing details can stay blank."
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            const form = new FormData(event.currentTarget)
            const channels = [
              ['phone', 'Phone'],
              ['email', 'Email'],
            ].flatMap(([key, label]) =>
              form.get(key) ? [{ kind: key, label, raw: String(form.get(key)) }] : [],
            )
            void send('/contacts', {
              company_id: companyId,
              document_id: form.get('document_id') || null,
              fields: {
                full_name: form.get('full_name'),
                designation: form.get('designation'),
                channels,
              },
            })
              .then(async () => {
                await refresh()
                setOpen(false)
              })
              .catch(setError)
          }}
        >
          <Field label="Full name">
            <input name="full_name" required maxLength={300} />
          </Field>
          <Field label="Designation">
            <input name="designation" maxLength={300} />
          </Field>
          <Field label="Phone">
            <input name="phone" type="tel" />
          </Field>
          <Field label="Email">
            <input name="email" type="email" />
          </Field>
          <Field label="Source document (optional)">
            <select name="document_id">
              <option value="">Company record only</option>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.title}
                </option>
              ))}
            </select>
          </Field>
          <ErrorMessage error={error} />
          <Button>Save person</Button>
        </form>
      </Modal>
    </>
  )
}
export function CompaniesPage() {
  const { activeExpo } = useLibrary(),
    [all, setAll] = useState(true),
    [q, setQ] = useState('')
  const rows = useQuery({
    queryKey: ['companies', all, activeExpo?.id],
    queryFn: () =>
      api<CompanySummary[]>(`/companies${!all && activeExpo ? `?expo_id=${activeExpo.id}` : ''}`),
  })
  const visible = rows.data?.filter((row) =>
    JSON.stringify([row.display_name, row.people, row.products, row.services, row.channels])
      .toLowerCase()
      .includes(q.toLowerCase()),
  )
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Companies</h1>
          <p className="muted">Browse your companies and their distinct contacts.</p>
        </div>
        <Link className="button secondary" to="/library">
          Document view
        </Link>
      </div>
      <LibraryTabs />
      <div className="library-toolbar">
        <div className="search-field">
          <Search size={18} />
          <input
            aria-label="Filter companies"
            placeholder="Company, person or product…"
            value={q}
            onChange={(event) => setQ(event.target.value)}
          />
        </div>
        <label className="checkbox-label">
          <input type="checkbox" checked={all} onChange={(event) => setAll(event.target.checked)} />
          All expos
        </label>
      </div>
      <ErrorMessage error={rows.error} />
      {visible?.length ? (
        <div className="expo-grid">
          {visible.map((company) => (
            <Link className="panel expo-card" key={company.id} to={`/companies/${company.id}`}>
              <Building2 size={25} />
              <h2>{company.display_name}</h2>
              <p className="muted">
                {company.description ||
                  [...company.products, ...company.services].join(' · ') ||
                  'Open company details'}
              </p>
              {company.business_role && <Badge>{company.business_role}</Badge>}
            </Link>
          ))}
        </div>
      ) : (
        <Empty
          title="No companies here yet"
          description="Confirm document groups for extraction, or link a document to a company yourself."
        />
      )}
    </>
  )
}
