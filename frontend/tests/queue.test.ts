import 'fake-indexeddb/auto'
import { beforeEach, expect, test, vi } from 'vitest'
import { allCaptures, database, newCapture, queueFiles, updateCapture } from '../src/pwa/queue'

vi.mock('../src/api/client', () => ({ api: vi.fn(), send: vi.fn() }))
import { api, send } from '../src/api/client'
import { syncQueue } from '../src/pwa/sync'

beforeEach(async () => { vi.resetAllMocks(); const db = await database(); await db.clear('queue'); await db.clear('meta'); vi.stubGlobal('window', new EventTarget()); vi.stubGlobal('navigator', { onLine: true }) })
test('captured expo stays fixed; a lost acknowledgement keeps the blob until retry succeeds', async () => {
  const file = new File(['FAKE ONLY'], 'fake.txt', { type: 'text/plain' })
  const [queued] = await queueFiles([file], 'expo-one')
  vi.mocked(api).mockImplementation(async path => { if (path.endsWith('/files')) throw new TypeError('offline'); return {} as never })
  vi.mocked(send).mockImplementation(async path => path.endsWith('/check') ? { existing: {} } as never : { id: 'server-session' } as never)
  await syncQueue()
  expect((await allCaptures())[0].blob?.size).toBe(file.size)
  vi.mocked(api).mockResolvedValue({ status: 'saved', asset: { id: 'asset' }, document: { id: 'doc' } })
  await syncQueue()
  const saved = (await allCaptures())[0]
  expect(saved.state).toBe('saved'); expect(saved.blob).toBeUndefined(); expect(saved.expoId).toBe('expo-one')
  expect(vi.mocked(send).mock.calls.some(([path, body]) => path === '/sync/files' && (body as any).expo_id === 'expo-one')).toBe(true)
  expect(saved.id).toBe(queued.id)
})
test('an edit during note sync stays pending and the next revision is sent', async () => {
  const note = await newCapture('note', 'expo', { targetKind: 'expo', targetId: 'expo', text: 'old' })
  vi.mocked(api).mockResolvedValue({})
  let edited = false
  vi.mocked(send).mockImplementation(async path => { if (path === '/sync/notes' && !edited) { edited = true; await updateCapture(note.id, { text: 'latest', version: 2, state: 'pending' }) }; return { id: 'server-note' } as never })
  await syncQueue(); expect((await allCaptures())[0].state).toBe('pending')
  await syncQueue(); expect((await allCaptures())[0].state).toBe('saved')
  expect(vi.mocked(send).mock.calls.some(([path, body]) => path === '/sync/notes' && (body as any).text_value === 'latest' && (body as any).revision === 2)).toBe(true)
})

test('a note deleted before sync is never sent; deleting an attempted note sends an empty newer tombstone', async () => {
  const { deleteQueuedNote } = await import('../src/pwa/queue')
  const neverSent = await newCapture('note', 'expo', { targetKind: 'expo', targetId: 'expo', text: 'discarded private text' })
  await deleteQueuedNote(neverSent.id)
  expect(await allCaptures()).toHaveLength(0)
  const attempted = await newCapture('note', 'expo', { targetKind: 'expo', targetId: 'expo', text: 'in-flight old text', attempted: true })
  await deleteQueuedNote(attempted.id)
  vi.mocked(api).mockResolvedValue({})
  vi.mocked(send).mockResolvedValue({id:'server-note'})
  await syncQueue()
  const request = vi.mocked(send).mock.calls.find(([path]) => path === '/sync/notes')?.[1] as any
  expect(request.deleted).toBe(true); expect(request.text_value).toBe(''); expect(request.revision).toBe(2)
})

test('a capture added during an existing sync is sent without waiting for the periodic timer', async () => {
  let release!: () => void
  let reached!: () => void
  const atReport = new Promise<void>(resolve => { reached = resolve })
  const reporting = new Promise<void>(resolve => { release = resolve })
  vi.mocked(api).mockResolvedValue({status: 'saved', asset: {id: 'asset'}, document: {id: 'doc'}})
  let firstReport = true
  vi.mocked(send).mockImplementation(async path => {
    if (path === '/sync/report' && firstReport) { firstReport = false; reached(); await reporting }
    return path.endsWith('/check') ? {existing: {}} as never : {id: 'server'} as never
  })
  const current = syncQueue()
  await atReport
  await queueFiles([new File(['new bytes'], 'later.txt')], 'expo-one')
  await syncQueue()
  release()
  await current
  expect((await allCaptures())[0].state).toBe('saved')
})
