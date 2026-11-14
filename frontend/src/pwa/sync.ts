import { api, send } from '../api/client'
import { hashFile } from './hash'
import { allCaptures, database, meta, setMeta, updateCapture, type Capture, type CachedExpo } from './queue'

let running = false, rerun = false
export async function syncQueue() {
  if (running) { rerun = true; return }
  if (!navigator.onLine) return
  running = true
  try {
    await api('/auth/me', { signal: AbortSignal.timeout(5000) }) // The phone only drops bytes after an authenticated Saved response.
    const device = await meta<string>('device') ?? crypto.randomUUID()
    await setMeta('device', device)
    const deviceLabel = await meta<string>('deviceLabel') ?? 'My phone'
    const resolveExpo = async (id: string) => (await (await database()).get('queue', id))?.serverId ?? id
    const resolveTarget = async (item: Capture) => {
      if (item.targetKind === 'expo') return resolveExpo(item.targetId!)
      const parent = await (await database()).get('queue', item.targetId!)
      if (!parent?.serverId || parent.state !== 'saved') throw new Error('Waiting for this photo or booth to be saved.')
      return parent.serverId
    }
    for (const kind of ['expo', 'group', 'file', 'note', 'tags'] as const) {
      for (const item of (await allCaptures()).filter(item => item.kind === kind && item.state !== 'saved')) {
        try {
          await updateCapture(item.id, { state: 'syncing', error: undefined, attempted: true })
          if (kind === 'file' && item.serverId) { await updateCapture(item.id, { state: 'saved', blob: undefined }); continue }
          let serverId = item.serverId
          const expo = await resolveExpo(item.expoId)
          if (kind === 'expo') {
            const saved = await send<{id:string}>('/sync/expos', { client_uuid: item.id, name: item.label })
            serverId = saved.id
            const expos = await meta<CachedExpo[]>('expos') ?? []
            await setMeta('expos', expos.map(row => row.id === item.id ? { ...row, id: saved.id, client_uuid: item.id, serverId: saved.id } : row))
          } else if (kind === 'group') {
            serverId = (await send<{id:string}>('/sync/groups', { client_uuid: item.id, expo_id: expo, label: item.label ?? '', captured_at: item.capturedAt, device_label: deviceLabel })).id
          } else if (kind === 'file') {
            if (!item.expoId) throw new Error('Choose an expo for this shared file before syncing.')
            if (!item.blob) throw new Error('The photo is missing from this device. Choose it again.')
            const group = item.groupId ? await (await database()).get('queue', item.groupId) : undefined
            if (group && group.state !== 'saved') throw new Error('Waiting for the booth to be saved.')
            const sha256 = item.sha256 ?? await hashFile(item.blob)
            await updateCapture(item.id, { sha256 })
            const session = await send<{id:string}>('/upload-sessions', { expo_id: expo, device_label: deviceLabel, client_uuid: item.groupId ?? item.id })
            const check = await send<{existing:Record<string,string>}>(`/upload-sessions/${session.id}/check`, { sha256: [sha256] })
            const form = new FormData(); form.set('sha256', sha256); form.set('client_uuid', item.id); form.set('kind', item.type ?? 'other'); form.set('filename', item.filename ?? '')
            form.set('instructions', item.instructions ?? ''); form.set('auto_process', String(item.autoProcess ?? false))
            if (!check.existing[sha256]) form.set('file', item.blob, item.filename)
            const saved = await api<{status:string;asset:{id:string};document:{id:string}}>(`/upload-sessions/${session.id}/files`, { method: 'POST', body: form })
            if (saved.status !== 'saved') throw new Error('The server has not confirmed this photo is saved.')
            serverId = (await send<{id:string;status:string}>('/sync/files', { client_uuid: item.id, expo_id: expo, document_id: saved.document.id, asset_id: saved.asset.id, sha256, capture_group_id: group?.serverId })).id
            await send(`/upload-sessions/${session.id}/complete`, {})
          } else if (kind === 'note') {
            serverId = (await send<{id:string}>('/sync/notes', { client_uuid: item.id, revision: item.version, target_kind: item.targetKind, target_id: await resolveTarget(item), text_value: item.text ?? '', deleted: item.deleted ?? false })).id
          } else {
            serverId = (await send<{id:string}>('/sync/tags', { client_uuid: item.id, target_kind: item.targetKind, target_id: await resolveTarget(item), labels: item.labels ?? [] })).id
          }
          // A user may edit a note while its earlier revision is in flight.
          const current = await (await database()).get('queue', item.id)
          if (current?.version === item.version) await updateCapture(item.id, { state: 'saved', serverId, ...(kind === 'file' ? { blob: undefined } : {}) })
          else await updateCapture(item.id, { state: 'pending', serverId })
        } catch (error) {
          await updateCapture(item.id, { state: 'error', error: error instanceof Error ? error.message : 'Keep this item and retry when connected.' })
          if (!navigator.onLine || error instanceof TypeError) return
        }
      }
    }
    const remaining = (await allCaptures()).filter(row => row.state !== 'saved')
    await send('/sync/report', { client_uuid: device, device_label: deviceLabel, files: remaining.filter(row => row.kind === 'file').length, notes: remaining.filter(row => row.kind === 'note').length, bytes: remaining.reduce((sum, row) => sum + (row.blob?.size ?? 0), 0) })
  } catch { /* Offline or signed out: every unsaved item stays on this phone. */ }
  finally { running = false; window.dispatchEvent(new Event('capture-change')); window.dispatchEvent(new Event('capture-synced')); if (rerun) { rerun = false; await syncQueue() } }
}
