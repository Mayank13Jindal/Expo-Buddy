import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, send } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Button, ErrorMessage, Field, Modal } from '../components/ui'

export function AIReprocess({ document }: { document: any }) {
  const [open, setOpen] = useState(false),
    [instructions, setInstructions] = useState(document.processing_options?.instructions ?? ''),
    [vision, setVision] = useState(document.processing_options?.image_check ?? false),
    [crop, setCrop] = useState(document.processing_options?.auto_crop ?? true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>()
  const { refresh } = useLibrary(),
    toast = useToast()
  return (
    <>
      <Button
        variant="secondary"
        onClick={() => {
          setInstructions(document.processing_options?.instructions ?? '')
          setVision(document.processing_options?.image_check ?? false)
          setCrop(document.processing_options?.auto_crop ?? true)
          setOpen(true)
        }}
      >
        Ask AI again
      </Button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title="Reprocess this scan"
        description="Add context or ask for a closer look. Your corrections are protected."
      >
        <Field label="Note or instructions for AI">
          <textarea
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            rows={4}
            maxLength={20000}
            placeholder="Check the company logo; compare the email’s O/0; focus on this person…"
          />
        </Field>
        <div className="quick-tags">
          {[
            'Read the company logo',
            'Check O/0 and e/c in emails',
            'Separate names from job titles',
          ].map((prompt) => (
            <button
              type="button"
              className="badge"
              key={prompt}
              onClick={() =>
                setInstructions(
                  prompt + '. Compare with the source; flag uncertainty instead of guessing.',
                )
              }
            >
              {prompt}
            </button>
          ))}
        </div>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={crop}
            onChange={(event) => setCrop(event.target.checked)}
          />
          Auto-crop and straighten before OCR
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={vision}
            onChange={(event) => setVision(event.target.checked)}
          />
          Also check the photo with local Ollama
        </label>
        <p className="caption">
          Image checks require a locally installed vision model. Up to four prepared pages are sent
          locally; suggested corrections need your approval. Printed text and this instruction may
          use your enabled cloud providers. Existing personal notes are not sent.
        </p>
        <ErrorMessage error={error} />
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await send(`/documents/${document.id}/reprocess`, {
                instructions,
                image_check: vision,
                auto_crop: crop,
              })
              await refresh()
              setOpen(false)
              toast('Reprocessing started. Follow OCR → AI → Review below.')
            } catch (error) {
              setError(error)
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? 'Starting…' : 'Reprocess with these instructions'}
        </Button>
      </Modal>
    </>
  )
}

export function ProcessingProgress({ id, state }: { id: string; state: string }) {
  const { refresh } = useLibrary(),
    toast = useToast()
  const query = useQuery({
    queryKey: ['document-progress', id],
    queryFn: () => api<any>(`/documents/${id}/progress`),
    refetchInterval: 3000,
  })
  const steps = query.data?.steps ?? []
  const finished = ['ready', 'indexing', 'needs_review', 'failed'].includes(state)
  const current = steps.find((row: any) =>
    ['failed', 'needs_review', 'waiting', 'running'].includes(row.state),
  )
  return (
    <section className="panel processing-progress">
      <h2>From photo to contact</h2>
      <ol>
        {[
          ['prepare', 'Prepare photo'],
          ['read', 'OCR'],
          ['ai', 'AI'],
          ...(steps.some((row: any) => row.step === 'vision') ? [['vision', 'Image check']] : []),
          ['review', 'Review'],
        ].map(([key, label]) => {
          const item = steps.find((row: any) => row.step === key)
          return (
            <li
              key={key}
              data-state={item?.state ?? (key === 'review' && finished ? 'ready' : 'queued')}
            >
              <span>{label}</span>
              <small>
                {item?.state ?? (key === 'review' && finished ? 'Ready to check' : 'Next')}
              </small>
            </li>
          )
        })}
      </ol>
      {current?.reason && <p className="notice">{current.reason}</p>}
      {state === 'needs_review' && (
        <p className="notice">
          No readable text was found. Try a sharper photo or request a local image check.
        </p>
      )}
      {state === 'waiting_grouping' && (
        <>
          <p>Are these pages one card? Confirm to start AI.</p>
          <Button
            variant="secondary"
            onClick={() => {
              void send('/grouping/accept', { document_ids: [id] })
                .then(refresh)
                .catch((error) => toast(error.message))
            }}
          >
            Process this document
          </Button>
          <Link className="text-button" to="/grouping">
            Group front/back first
          </Link>
        </>
      )}
      {state === 'waiting_ai' && !current?.reason && (
        <p className="caption">
          Waiting for an enabled AI provider. Check <Link to="/settings#ai">AI connections</Link>.
        </p>
      )}
    </section>
  )
}

export function FieldReview({ companyId, documentId }: { companyId: string; documentId: string }) {
  const { refresh } = useLibrary(),
    toast = useToast()
  const query = useQuery({
    queryKey: ['field-review', companyId],
    queryFn: () => api<any>(`/companies/${companyId}`),
  })
  const company = query.data
  const save = (kind: string, id: string, field: string, value: unknown) => {
    void send(`/${kind}/${id}`, { fields: { [field]: value } }, 'PATCH')
      .then(refresh)
      .catch((error) => toast(error.message))
  }
  if (!company) return null
  return (
    <section className="panel field-review">
      <h2>Read it beside the card</h2>
      <p className="caption">
        Correct any value here. O/0, e/c and logo lettering need a visual check; email domains are
        clues, not proof of a company name.
      </p>
      <Field label="Company name">
        <input
          key={company.display_name}
          defaultValue={company.display_name}
          maxLength={300}
          onBlur={(event) => {
            if (event.target.value !== company.display_name)
              save('companies', company.id, 'display_name', event.target.value)
          }}
        />
      </Field>
      {company.field_sources
        ?.filter((field: any) => field.field === 'display_name')
        .flatMap((field: any) => field.evidence ?? [])
        .map((evidence: any, index: number) => (
          <Link
            className="field-evidence"
            key={index}
            to={`/documents/${documentId}?page=${evidence.page_id}`}
          >
            “{evidence.quote}” · source ↗
          </Link>
        ))}
      {[company, ...company.contacts].map((record: any) => (
        <div className="field-review-record" key={record.id}>
          {record.full_name !== undefined && (
            <Field label="Person name">
              <input
                key={record.full_name}
                defaultValue={record.full_name}
                maxLength={300}
                onBlur={(event) => {
                  if (event.target.value !== record.full_name)
                    save('contacts', record.id, 'full_name', event.target.value)
                }}
              />
            </Field>
          )}
          {record.review_warning && <p className="notice">{record.review_warning}</p>}
          {record.channels.map((channel: any, index: number) => (
            <div key={`${index}-${channel.raw}`}>
              <Field
                label={`${record.full_name ? record.full_name + ' · ' : ''}${channel.label || channel.kind}`}
              >
                {channel.kind === 'address' ? (
                  <textarea
                    rows={3}
                    defaultValue={channel.raw}
                    onBlur={(event) => {
                      if (event.target.value !== channel.raw)
                        save(
                          record.id === company.id ? 'companies' : 'contacts',
                          record.id,
                          'channels',
                          record.channels.map((row: any, i: number) =>
                            i === index ? { ...row, raw: event.target.value } : row,
                          ),
                        )
                    }}
                  />
                ) : (
                  <input
                    defaultValue={channel.raw}
                    onBlur={(event) => {
                      if (event.target.value !== channel.raw)
                        save(
                          record.id === company.id ? 'companies' : 'contacts',
                          record.id,
                          'channels',
                          record.channels.map((row: any, i: number) =>
                            i === index ? { ...row, raw: event.target.value } : row,
                          ),
                        )
                    }}
                  />
                )}
              </Field>
              {channel.evidence?.quote && (
                <Link
                  className="field-evidence"
                  to={`/documents/${documentId}?page=${channel.evidence.page_id}`}
                >
                  “{channel.evidence.quote}” · source ↗
                </Link>
              )}
            </div>
          ))}
        </div>
      ))}
    </section>
  )
}
