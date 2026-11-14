import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { hashFile } from '../pwa/hash'
import { CheckCircle2, FileImage, FolderUp, Camera, UploadCloud, RotateCw, X } from 'lucide-react'
import { api, csrfToken, send } from '../api/client'
import { useLibrary } from '../app/providers'
import { Button, ErrorMessage } from '../components/ui'

type UploadItem = {
  id: string
  file: File
  expoId: string
  sessionId?: string
  state: string
  percent: number
  instructions?: string
  error?: string
}
export { hashFile } from '../pwa/hash'
export function uploadWithProgress(
  path: string,
  form: FormData,
  progress: (value: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/v1${path}`)
    xhr.setRequestHeader('X-CSRF-Token', csrfToken())
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) progress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onerror = () => reject(new Error('Connection lost. Your file can be retried.'))
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve()
      else {
        let message = 'Upload failed. Please retry.'
        try {
          message = JSON.parse(xhr.responseText).detail
        } catch {}
        reject(new Error(message))
      }
    }
    xhr.send(form)
  })
}

export function UploadPage() {
  const { activeExpo, refresh } = useLibrary()
  const [items, setItems] = useState<UploadItem[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(),
    [drag, setDrag] = useState(false)
  const input = useRef<HTMLInputElement>(null),
    camera = useRef<HTMLInputElement>(null)
  const [notes, setNotes] = useState('')
  const update = (id: string, values: Partial<UploadItem>) =>
    setItems((items) => items.map((item) => (item.id === id ? { ...item, ...values } : item)))
  const start = async (files: File[], retryItem?: UploadItem) => {
    if ((!activeExpo && !retryItem) || (!files.length && !retryItem) || busy) return
    const expo = retryItem?.expoId ?? activeExpo!.id // Frozen for this batch, including hashing and retries.
    const incoming = retryItem
      ? [{ ...retryItem, state: 'Waiting', error: undefined }]
      : files.map((file) => ({
          id: crypto.randomUUID(),
          file,
          expoId: expo,
          state: 'Waiting',
          percent: 0,
          instructions: notes,
        }))
    if (retryItem)
      setItems((items) => items.map((row) => (row.id === retryItem.id ? incoming[0] : row)))
    else setItems((items) => [...items, ...incoming])
    setBusy(true)
    setError(undefined)
    try {
      const session = retryItem?.sessionId
        ? { id: retryItem.sessionId }
        : await send<{ id: string }>('/upload-sessions', { expo_id: expo })
      for (const item of incoming) update(item.id, { sessionId: session.id })
      const queue = [...incoming]
      await Promise.all(
        Array.from({ length: Math.min(3, incoming.length) }, async () => {
          let item: UploadItem | undefined
          while ((item = queue.shift())) {
            const current = item
            try {
              update(current.id, { state: 'Checking' })
              const sha = await hashFile(current.file)
              const check = await send<{ existing: Record<string, string> }>(
                `/upload-sessions/${session.id}/check`,
                { sha256: [sha] },
              )
              const form = new FormData()
              form.set('sha256', sha)
              form.set('client_uuid', current.id)
              form.set('filename', current.file.name)
              form.set('instructions', current.instructions ?? '')
              form.set('kind', current.file.type === 'application/pdf' ? 'brochure' : 'card')
              form.set('auto_process', 'true')
              if (!check.existing[sha]) form.set('file', current.file)
              update(current.id, { state: 'Uploading' })
              await uploadWithProgress(`/upload-sessions/${session.id}/files`, form, (percent) =>
                update(current.id, { percent }),
              )
              update(current.id, { state: 'Saved', percent: 100 })
            } catch (error) {
              update(current.id, {
                state: 'Failed',
                error: error instanceof Error ? error.message : 'Please retry this file.',
              })
            }
          }
        }),
      )
      await send(`/upload-sessions/${session.id}/complete`, {})
      await refresh()
    } catch (error) {
      setError(error)
      for (const item of incoming)
        update(item.id, {
          state: 'Failed',
          error: error instanceof Error ? error.message : 'Please retry.',
        })
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Add to your library</h1>
          <p className="muted">Cards, brochures, and the possibilities they hold.</p>
        </div>
      </div>
      {!activeExpo ? (
        <div className="notice">
          Choose or <Link to="/expos">create an expo</Link> before adding files.
        </div>
      ) : (
        <>
          <label className="field">
            Notes for these photos (optional)
            <textarea
              aria-label="Upload notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              maxLength={20000}
              rows={3}
              placeholder="What matters? Who did you meet? Anything AI should double-check?"
            />
            <small>Saved with the photos and shared with your selected AI as context.</small>
          </label>
          <div
            className={`upload-drop ${drag ? 'drag' : ''}`}
            onDragOver={(event) => {
              event.preventDefault()
              setDrag(true)
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDrag(false)
              void start(Array.from(event.dataTransfer.files))
            }}
          >
            <div className="upload-art">
              <UploadCloud size={42} strokeWidth={1.4} />
            </div>
            <h2>Bring your discoveries together.</h2>
            <p>Drop photos or PDFs here, or choose files below.</p>
            <div className="button-row">
              <Button disabled={busy} onClick={() => input.current?.click()}>
                <FolderUp size={18} />
                Choose files
              </Button>
              <Button variant="secondary" disabled={busy} onClick={() => camera.current?.click()}>
                <Camera size={18} />
                Take a photo
              </Button>
            </div>
            <p className="caption">
              JPG, PNG, WebP, HEIC · Images up to 100 MB · PDFs up to 400 MB
            </p>
            <input
              ref={input}
              type="file"
              className="sr-only"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
              multiple
              onChange={(event) => {
                void start(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
            <input
              ref={camera}
              type="file"
              className="sr-only"
              accept="image/*"
              capture="environment"
              onChange={(event) => {
                void start(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
          </div>
          <ErrorMessage error={error} />
          <div className="upload-hint">
            <CheckCircle2 size={19} />
            <p>
              <strong>Your originals stay just as they are.</strong>
              <br />
              Once a file says Saved, processing continues on your server.
            </p>
          </div>
        </>
      )}
      {items.length > 0 && (
        <section className="panel">
          <div className="panel-heading">
            <h2>Your files</h2>
            <span className="caption">
              {items.filter((item) => item.state === 'Saved').length} of {items.length} saved
            </span>
          </div>
          {items.map((item) => (
            <div className="upload-item" key={item.id}>
              <FileImage size={23} />
              <div>
                <strong>{item.file.name}</strong>
                <small>{item.error ?? item.state}</small>
                {item.state === 'Uploading' && <progress max={100} value={item.percent} />}
              </div>
              {item.state === 'Saved' ? (
                <CheckCircle2 className="text-green" size={20} />
              ) : (
                item.state === 'Failed' && (
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => {
                      void start([], item)
                    }}
                  >
                    <RotateCw size={16} />
                    Retry
                  </Button>
                )
              )}
            </div>
          ))}
        </section>
      )}
    </>
  )
}
