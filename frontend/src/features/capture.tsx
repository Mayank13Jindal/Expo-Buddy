import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Camera,
  Images,
  Plus,
  RefreshCw,
  StickyNote,
  Check,
  Trash2,
  UploadCloud,
} from 'lucide-react'
import { useLibrary, useToast } from '../app/providers'
import { Badge, Button, ErrorMessage, Field, Modal } from '../components/ui'
import { useCaptures } from '../pwa/hooks'
import {
  createOfflineExpo,
  database,
  deleteQueuedNote,
  meta,
  newCapture,
  queueFiles,
  removeCapture,
  setMeta,
  updateCapture,
  type Capture,
} from '../pwa/queue'
import { syncQueue } from '../pwa/sync'

function Thumbnail({ blob }: { blob?: Blob }) {
  const [url, setURL] = useState('')
  useEffect(() => {
    if (!blob || !blob.type.startsWith('image/')) return
    const url = URL.createObjectURL(blob)
    setURL(url)
    return () => URL.revokeObjectURL(url)
  }, [blob])
  return url ? (
    <img className="capture-thumb" src={url} alt="Queued photo" />
  ) : (
    <span className="icon-tile">
      <Images size={20} />
    </span>
  )
}
export function CapturePage() {
  const { activeExpo, expos, setExpo } = useLibrary(),
    toast = useToast(),
    items = useCaptures()
  const [params] = useSearchParams()
  const camera = useRef<HTMLInputElement>(null),
    gallery = useRef<HTMLInputElement>(null)
  const creatingBooth = useRef<Promise<string | undefined> | null>(null)
  const [booth, setBooth] = useState(''),
    [label, setLabel] = useState(''),
    [kind, setKind] = useState('auto'),
    [error, setError] = useState<unknown>(),
    [newExpo, setNewExpo] = useState(false),
    [name, setName] = useState('')
  const [noteTarget, setNoteTarget] = useState(''),
    [note, setNote] = useState(''),
    [quota, setQuota] = useState(''),
    [adding, setAdding] = useState(false)
  useEffect(() => {
    void meta<string>('booth').then((id) => setBooth(id ?? ''))
    void navigator.storage?.persist?.()
    void navigator.storage?.estimate?.().then((info) => {
      if (info.quota && info.usage && info.usage / info.quota > 0.8)
        setQuota(
          'Your phone storage is almost full. Sync soon and keep the app open until it finishes.',
        )
    })
  }, [])
  useEffect(() => {
    const group = items.find((item) => item.id === booth)
    if (
      group &&
      activeExpo &&
      group.expoId !== activeExpo.id &&
      group.expoId !== activeExpo.client_uuid
    ) {
      setBooth('')
      creatingBooth.current = null
      void setMeta('booth', '')
    }
  }, [activeExpo?.id, activeExpo?.client_uuid, items, booth])
  const makeBooth = () => {
    const task = (async () => {
      if (!activeExpo) return
      const item = await newCapture('group', activeExpo.id, {
        label: label.trim() || `Booth ${items.filter((item) => item.kind === 'group').length + 1}`,
      })
      setBooth(item.id)
      await setMeta('booth', item.id)
      setLabel('')
      return item.id
    })()
    creatingBooth.current = task
    return task
  }
  const add = async (files: File[]) => {
    if (!activeExpo || adding) return
    setAdding(true)
    try {
      const selected = creatingBooth.current
        ? await creatingBooth.current
        : booth || (await meta<string>('booth'))
      const group = selected ? await (await database()).get('queue', selected) : undefined
      const groupId =
        group && (group.expoId === activeExpo.id || group.expoId === activeExpo.client_uuid)
          ? group.id
          : undefined
      await queueFiles(files, activeExpo.id, groupId, kind, {
        instructions: note.trim(),
        autoProcess: !groupId,
      })
      setNote((current) => (current === note ? '' : current))
      toast('Photos and notes saved on this device. Processing starts after sync.')
      void syncQueue()
    } catch (error) {
      setError(error)
    } finally {
      setAdding(false)
    }
  }
  const saveNote = async () => {
    if (!activeExpo || !note.trim()) return
    await newCapture('note', activeExpo.id, {
      targetKind: noteTarget.startsWith('file:')
        ? 'file'
        : noteTarget === 'booth' && booth
          ? 'group'
          : 'expo',
      targetId: noteTarget.startsWith('file:')
        ? noteTarget.slice(5)
        : noteTarget === 'booth' && booth
          ? booth
          : activeExpo.id,
      text: note.trim(),
    })
    setNote('')
    toast('Note kept on this phone.')
    void syncQueue()
  }
  const pending = items.filter((item) => item.state !== 'saved'),
    files = items.filter((item) => item.kind === 'file'),
    notes = items.filter((item) => item.kind === 'note' && !item.deleted)
  const run = (task: Promise<unknown>) => {
    void task.catch(setError)
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Keep the discovery.</h1>
          <p className="muted">Photos and context, together. Even without a connection.</p>
        </div>
        <Link className="text-button" to="/upload">
          Desktop upload
        </Link>
      </div>
      {params.has('shared') && <p className="notice">Shared files are kept in your phone queue.</p>}
      {params.has('share_failed') && (
        <p role="alert" className="error">
          The share could not be saved. Choose the files again below.
        </p>
      )}
      <section className="panel capture-expo">
        <div>
          <p className="caption">Saving to</p>
          <strong aria-label="Adding to expo">{activeExpo?.name ?? 'Choose an expo above'}</strong>
        </div>
        <Button variant="secondary" onClick={() => setNewExpo(true)}>
          <Plus size={17} />
          New expo
        </Button>
      </section>
      <ErrorMessage error={error} />
      {quota && <p className="notice">{quota}</p>}
      <div className="dashboard-columns">
        <div>
          <section className="panel capture-actions">
            <div className="panel-heading">
              <h2>Add a card</h2>
              {booth && <Badge>{items.find((item) => item.id === booth)?.label}</Badge>}
            </div>
            <div className="capture-buttons">
              <Button disabled={!activeExpo || adding} onClick={() => camera.current?.click()}>
                <Camera size={25} />
                Take photo
              </Button>
              <Button
                variant="secondary"
                disabled={!activeExpo || adding}
                onClick={() => gallery.current?.click()}
              >
                <Images size={25} />
                Choose from gallery
              </Button>
            </div>
            <section className="panel capture-notes">
              <h2>
                <StickyNote size={18} />
                Notes (optional)
              </h2>
              <textarea
                aria-label="Capture note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                maxLength={20000}
                placeholder="Anything to remember or ask AI to check? This note goes with your next photos."
              />
              <p className="caption">
                Saved with your next photos and shared as AI context. Existing private notes are not
                sent.
              </p>
              <details>
                <summary>Attach a note to an earlier photo or booth</summary>
                <Field label="Note belongs to">
                  <select
                    value={noteTarget}
                    onChange={(event) => setNoteTarget(event.target.value)}
                  >
                    <option value="expo">This expo</option>
                    {booth && <option value="booth">This booth</option>}
                    {files
                      .filter((row) => row.expoId === activeExpo?.id)
                      .slice(-30)
                      .map((row) => (
                        <option key={row.id} value={`file:${row.id}`}>
                          {row.filename}
                        </option>
                      ))}
                  </select>
                </Field>
                <Button
                  variant="secondary"
                  disabled={!activeExpo || !note.trim()}
                  onClick={() => run(saveNote())}
                >
                  Keep note
                </Button>
                <div className="quick-tags">
                  {['Follow up', 'Price asked', 'Sample taken'].map((label) => (
                    <button
                      key={label}
                      className="badge"
                      disabled={!activeExpo}
                      onClick={() => {
                        if (activeExpo)
                          run(
                            newCapture('tags', activeExpo.id, {
                              targetKind: booth ? 'group' : 'expo',
                              targetId: booth || activeExpo.id,
                              labels: [label],
                            }).then(() => toast(`“${label}” kept.`)),
                          )
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <p className="caption">
                  “Keep note” saves a separate private note instead of sharing it with AI.
                </p>
              </details>
            </section>
            <input
              ref={camera}
              className="sr-only"
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(event) => {
                void add(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
            <input
              ref={gallery}
              className="sr-only"
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
              multiple
              onChange={(event) => {
                void add(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
            <details className="capture-advanced">
              <summary>Front/back or booth grouping (optional)</summary>
              <div className="button-row">
                <Field label="Next booth label">
                  <input
                    value={label}
                    onChange={(event) => setLabel(event.target.value)}
                    placeholder="e.g. Hall 3 · Solar structures"
                    maxLength={200}
                  />
                </Field>
                <Button variant="secondary" disabled={!activeExpo} onClick={() => run(makeBooth())}>
                  <Plus size={17} />
                  New booth
                </Button>
              </div>
              <Field label="These photos are">
                <select value={kind} onChange={(event) => setKind(event.target.value)}>
                  <option value="auto">Auto · photo as card, PDF as brochure</option>
                  <option value="other">Other</option>
                  <option value="card">Visiting card</option>
                  <option value="brochure">Brochure</option>
                </select>
              </Field>
              <p className="caption">
                Photos in a booth wait for group confirmation. Leave this closed for automatic
                single-card processing.
              </p>
            </details>
            <p className="caption">
              Take another photo whenever you’re ready. Images up to 100 MB · PDFs up to 400 MB.
            </p>
          </section>
        </div>
        <div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>On this phone</h2>
                <p>
                  {pending.filter((row) => row.kind === 'file').length} files ·{' '}
                  {pending.filter((row) => row.kind === 'note').length} notes ·{' '}
                  {(
                    pending.reduce((sum, row) => sum + (row.blob?.size ?? 0), 0) /
                    1024 ** 2
                  ).toFixed(1)}{' '}
                  MB waiting
                </p>
              </div>
              <Button variant="secondary" onClick={() => run(syncQueue())}>
                <RefreshCw size={16} />
                Sync now
              </Button>
            </div>
            <p className="caption">
              {files.filter((row) => row.state === 'saved').length} of {files.length} saved
            </p>
            {pending.length === 0 && (
              <p className="quiet-status">
                <Check size={19} />
                Everything has reached your server.
              </p>
            )}
            {items
              .filter((row) => ['file', 'note', 'group'].includes(row.kind) && !row.deleted)
              .slice(-100)
              .reverse()
              .map((item) => (
                <div className="queue-item" key={item.id}>
                  {item.kind === 'file' && <Thumbnail blob={item.blob} />}
                  <div>
                    <strong>{item.filename ?? item.label ?? 'Personal note'}</strong>
                    <small>
                      {expos.find(
                        (expo) => expo.id === item.expoId || expo.client_uuid === item.expoId,
                      )?.name ?? 'Choose an expo'}{' '}
                      ·{' '}
                      {item.state === 'saved'
                        ? 'Saved'
                        : item.state === 'syncing'
                          ? 'Syncing…'
                          : (item.error ?? 'Waiting on this phone')}
                    </small>
                    {item.kind === 'note' && (
                      <textarea
                        aria-label="Edit queued note"
                        value={item.text ?? ''}
                        onChange={(event) =>
                          run(
                            updateCapture(item.id, {
                              text: event.target.value,
                              version: item.version + 1,
                              state: 'pending',
                            }),
                          )
                        }
                        rows={2}
                        maxLength={20000}
                      />
                    )}
                    {!item.expoId && (
                      <Button
                        variant="secondary"
                        disabled={!activeExpo}
                        onClick={() => run(updateCapture(item.id, { expoId: activeExpo!.id }))}
                      >
                        Use selected expo
                      </Button>
                    )}
                  </div>
                  {item.state === 'error' && (
                    <button
                      className="icon-button"
                      aria-label="Retry queued item"
                      onClick={() =>
                        run(
                          updateCapture(item.id, { state: 'pending', error: undefined }).then(
                            syncQueue,
                          ),
                        )
                      }
                    >
                      <RefreshCw size={17} />
                    </button>
                  )}
                  {item.state !== 'syncing' && item.kind !== 'group' && (
                    <button
                      className="icon-button"
                      aria-label="Remove queued item"
                      onClick={() => {
                        if (item.kind === 'note') run(deleteQueuedNote(item.id))
                        else if (
                          confirm(
                            item.state === 'saved'
                              ? 'Clear this saved receipt from your phone?'
                              : 'Remove this item from your phone? Unsynced content will be lost.',
                          )
                        )
                          run(removeCapture(item.id))
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              ))}
            <p className="notice">
              Keep the app open while syncing, especially on iPhone. Sync soon after returning:
              phones may clear unused app storage.
            </p>
          </section>
        </div>
      </div>
      <Modal
        open={newExpo}
        onOpenChange={setNewExpo}
        title="New expo"
        description="You can create this while offline."
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            run(
              createOfflineExpo(name).then(async (item) => {
                await setExpo(item.id)
                setName('')
                setNewExpo(false)
              }),
            )
          }}
        >
          <Field label="Expo name">
            <input
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={200}
            />
          </Field>
          <Button type="submit">Create expo</Button>
        </form>
      </Modal>
    </>
  )
}
