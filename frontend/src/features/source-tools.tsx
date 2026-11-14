import { useRef, useState, type FormEvent } from 'react'
import { RotateCw, Crop, Replace } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api, send, type Document, type Page } from '../api/client'
import { useLibrary, useToast } from '../app/providers'
import { Button, ErrorMessage, Field, Modal } from '../components/ui'

export function SourceTools({ document, page }: { document: Document; page: Page }) {
  const { refresh } = useLibrary(),
    toast = useToast()
  const [cropOpen, setCropOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>()
  const file = useRef<HTMLInputElement>(null)
  const versions = useQuery({
    queryKey: ['source-versions', document.id],
    queryFn: () =>
      api<{ id: string; kind: string; params: { old_asset_id?: string }; created_at: string }[]>(
        `/documents/${document.id}/versions`,
      ),
  })
  const edit = async (kind: string, body: unknown) => {
    setBusy(true)
    setError(undefined)
    try {
      await send(`/documents/${document.id}/${kind}`, body)
      await refresh()
      setCropOpen(false)
      toast('Source updated. Reading will start again; your corrections are kept.')
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  const crop = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    void edit('crop', {
      page_id: page.id,
      ...Object.fromEntries(
        ['left', 'top', 'right', 'bottom'].map((key) => [key, Number(data.get(key)) / 100]),
      ),
    })
  }
  const replace = async (photo: File) => {
    setBusy(true)
    setError(undefined)
    try {
      const session = await send<{ id: string }>('/upload-sessions', { expo_id: document.expo_id })
      const form = new FormData()
      form.set('file', photo)
      const saved = await api<{ asset: { id: string }; document: { id: string } }>(
        `/upload-sessions/${session.id}/files`,
        { method: 'POST', body: form },
      )
      await send(`/documents/${document.id}/replace`, {
        page_id: page.id,
        asset_id: saved.asset.id,
        replacement_document_id: saved.document.id,
      })
      await refresh()
      toast('Photo replaced. The previous original is kept in source history.')
    } catch (error) {
      setError(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div className="source-tools">
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => {
            void edit('rotate', { page_id: page.id, degrees: 90 })
          }}
        >
          <RotateCw size={16} />
          Rotate
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => setCropOpen(true)}>
          <Crop size={16} />
          Crop
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => file.current?.click()}>
          <Replace size={16} />
          Better photo
        </Button>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => {
            void edit('reprocess', {})
          }}
        >
          Read again
        </Button>
        <input
          ref={file}
          type="file"
          accept="image/*"
          className="sr-only"
          aria-label="Choose a better photo"
          onChange={(event) => {
            if (event.target.files?.[0]) void replace(event.target.files[0])
            event.target.value = ''
          }}
        />
      </div>
      <ErrorMessage error={error} />
      {!!versions.data?.length && (
        <details className="raw-text">
          <summary>Source history</summary>
          {versions.data.map((version) => (
            <p className="caption" key={version.id}>
              {new Date(version.created_at).toLocaleString('en-IN', { timeZone: 'Asia/Calcutta' })}{' '}
              ·{' '}
              {version.kind === 'replacement' && version.params.old_asset_id ? (
                <a
                  className="text-button"
                  href={`/api/v1/assets/${version.params.old_asset_id}/original`}
                >
                  Download previous original
                </a>
              ) : (
                'Reading copy changed'
              )}
            </p>
          ))}
        </details>
      )}
      <Modal
        open={cropOpen}
        onOpenChange={setCropOpen}
        title="Choose the area to read"
        description="Enter the edges as percentages of this page. Your original stays saved."
      >
        <form onSubmit={crop}>
          <div className="form-grid">
            {['left', 'top', 'right', 'bottom'].map((key) => (
              <Field key={key} label={`${key[0].toUpperCase() + key.slice(1)} edge (%)`}>
                <input
                  name={key}
                  type="number"
                  min="0"
                  max="100"
                  required
                  defaultValue={key === 'right' || key === 'bottom' ? 100 : 0}
                />
              </Field>
            ))}
          </div>
          <ErrorMessage error={error} />
          <div className="form-actions">
            <Button type="button" variant="secondary" onClick={() => setCropOpen(false)}>
              Cancel
            </Button>
            <Button disabled={busy}>Save crop & read again</Button>
          </div>
        </form>
      </Modal>
    </>
  )
}
