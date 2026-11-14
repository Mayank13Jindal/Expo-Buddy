import { openDB, type DBSchema } from 'idb'
import { hashFile } from './hash'

export type QueueKind = 'expo' | 'group' | 'file' | 'note' | 'tags'
export interface Capture {
  id: string; kind: QueueKind; expoId: string; capturedAt: string; state: 'pending' | 'syncing' | 'saved' | 'error'; version: number;
  attempted?: boolean; serverId?: string; groupId?: string; label?: string; blob?: Blob; filename?: string; mime?: string; bytes?: number; sha256?: string; type?: string;
  instructions?: string; autoProcess?: boolean;
  targetKind?: 'file' | 'group' | 'expo'; targetId?: string; text?: string; deleted?: boolean; labels?: string[]; error?: string;
}
export interface CachedExpo { id: string; name: string; client_uuid?: string; serverId?: string; archived?: boolean; city?: string; venue?: string; start_date?: string | null; end_date?: string | null }
interface CaptureDB extends DBSchema {
  queue: { key: string; value: Capture; indexes: { kind: QueueKind } };
  meta: { key: string; value: { key: string; value: unknown } };
}
export const database = () => openDB<CaptureDB>('expo-capture', 1, { upgrade(db) { db.createObjectStore('queue', { keyPath: 'id' }).createIndex('kind', 'kind'); db.createObjectStore('meta', { keyPath: 'key' }) } })
export const changed = () => { if (typeof window !== 'undefined') window.dispatchEvent(new Event('capture-change')) }
export async function meta<T>(key: string): Promise<T | undefined> { return (await (await database()).get('meta', key))?.value as T | undefined }
export async function setMeta(key: string, value: unknown) { await (await database()).put('meta', { key, value }); changed() }
export async function allCaptures(): Promise<Capture[]> { return (await (await database()).getAll('queue')).sort((a, b) => a.capturedAt.localeCompare(b.capturedAt)) }
export async function putCapture(item: Capture) { await (await database()).put('queue', item); changed(); return item }
export async function updateCapture(id: string, values: Partial<Capture>) { const db = await database(), tx = db.transaction('queue', 'readwrite'), row = await tx.store.get(id); if (row) await tx.store.put({ ...row, ...values }); await tx.done; changed() }
export async function removeCapture(id: string) {
  const items = await allCaptures()
  if (items.some(row => row.targetId === id && (row.state !== 'saved' || (row.kind === 'note' && !row.deleted)))) throw new Error('Remove the photo’s queued notes and tags first.')
  const db = await database(); await db.delete('queue', id); changed()
}
export async function newCapture(kind: QueueKind, expoId: string, values: Partial<Capture> = {}) { return putCapture({ id: crypto.randomUUID(), kind, expoId, capturedAt: new Date().toISOString(), state: 'pending', version: 1, ...values }) }
export async function createOfflineExpo(name: string) {
  if (!name.trim()) throw new Error('Give the expo a name.')
  const item = await newCapture('expo', '', { label: name.trim() }); item.expoId = item.id; await putCapture(item)
  const expos = await meta<CachedExpo[]>('expos') ?? []
  await setMeta('expos', [...expos, { id: item.id, name: item.label!, client_uuid: item.id }]); await setMeta('activeExpo', item.id)
  return item
}
export async function queueFiles(files: File[], expoId: string, groupId?: string, type = 'auto', options: { instructions?: string; autoProcess?: boolean } = {}) {
  const items: Capture[] = []
  for (const file of files) {
    if (file.size > (file.type === 'application/pdf' ? 400 : 100) * 1024 ** 2) throw new Error(`${file.name} exceeds the ${file.type === 'application/pdf' ? 400 : 100} MB limit.`)
    const item = await newCapture('file', expoId, { groupId, blob: file, filename: file.name, mime: file.type, bytes: file.size, type: type === 'auto' ? file.type === 'application/pdf' ? 'brochure' : 'card' : type, ...options }); items.push(item)
    try { await updateCapture(item.id, { sha256: await hashFile(file) }) } catch { /* Bytes are already durable in IndexedDB; hashing retries during sync. */ }
  }
  return items
}

export async function deleteQueuedNote(id: string) {
  const item = await (await database()).get('queue', id)
  if (!item || item.kind !== 'note') return
  if (!item.attempted && !item.serverId) await removeCapture(id)
  else await updateCapture(id, { deleted: true, text: '', version: item.version + 1, state: 'pending' })
}
