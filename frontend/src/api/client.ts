export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public details?: unknown,
  ) {
    super(message)
  }
}
export function csrfToken(): string {
  return (
    document.cookie
      .split('; ')
      .find((cookie) => cookie.startsWith('expo_csrf='))
      ?.split('=')[1] ?? ''
  )
}
let opening: Promise<boolean> | undefined
async function openPasswordless(): Promise<boolean> {
  if (!opening)
    opening = (async () => {
      const status = await fetch('/api/v1/auth/status', {
        credentials: 'same-origin',
        signal: AbortSignal.timeout(15000),
      })
      if (!status.ok || (await status.json()).password_required !== false) return false
      return (
        await fetch('/api/v1/auth/open', {
          method: 'POST',
          credentials: 'same-origin',
          signal: AbortSignal.timeout(15000),
        })
      ).ok
    })().finally(() => {
      opening = undefined
    })
  return opening
}
let serverReachable = true
function reachability(reachable: boolean) {
  if (serverReachable === reachable) return
  serverReachable = reachable
  window.dispatchEvent(new CustomEvent('server-reachability', { detail: reachable }))
}
export const isServerReachable = () => serverReachable
export async function api<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken())
  const signal =
    !options.method || options.method === 'GET'
      ? options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)])
        : AbortSignal.timeout(15000)
      : options.signal
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      signal,
      headers,
      credentials: 'same-origin',
    })
    if (response.status === 401 && !path.startsWith('/auth/') && (await openPasswordless())) {
      headers.set('X-CSRF-Token', csrfToken())
      response = await fetch(`/api/v1${path}`, {
        ...options,
        signal,
        headers,
        credentials: 'same-origin',
      })
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    if (
      error instanceof TypeError ||
      (error instanceof DOMException && error.name === 'TimeoutError')
    )
      reachability(false)
    throw new TypeError(
      error instanceof DOMException && error.name === 'TimeoutError'
        ? 'The library took too long to respond. Retry when the server is available.'
        : 'Cannot reach your library. Check the server connection, then retry.',
      { cause: error },
    )
  }
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'The server could not complete this request.' }))
    if ([502, 504].includes(response.status)) {
      reachability(false)
      throw new TypeError(
        'The library server is temporarily unavailable. Retry after it restarts; captures stay on this device.',
      )
    }
    reachability(true)
    if (response.status === 401) window.dispatchEvent(new Event('signed-out'))
    throw new ApiError(
      response.status,
      response.status === 401
        ? 'Your session expired. Sign in again; queued captures remain on this device.'
        : typeof error.detail === 'string'
          ? error.detail
          : error.services
            ? 'Some library services need attention. See the service status below.'
            : 'The server could not complete this request.',
      error,
    )
  }
  reachability(true)
  return response.json() as Promise<T>
}
export const send = <T = unknown>(path: string, body: unknown, method = 'POST') =>
  api<T>(path, { method, body: JSON.stringify(body) })

export interface Expo {
  id: string
  client_uuid?: string
  name: string
  city: string
  venue: string
  archived: boolean
  start_date: string | null
  end_date: string | null
}
export interface Preferences {
  active_expo_id: string | null
  theme: 'light' | 'dark' | 'system'
  region_hint: string
  revision: number
  default_search_scope: string
}
export interface Note {
  id: string
  text: string
  origin: string
  created_at: string
  document_id?: string
  expo_id?: string
  asset_id?: string
}
export interface Asset {
  id: string
  mime: string
  original_filename: string
  sha256: string
  bytes: number
  page_count: number
}
export interface Page {
  preview_revision?: number | null
  id: string
  asset_id: string
  order: number
  pdf_page_no: number | null
  role: string
  asset: Asset
}
export interface Document {
  id: string
  title: string
  expo_id: string
  type: string
  group_state: string
  review_state: string
  review_status?: string
  pending_changes?: number
  review_reasons: string[]
  processing_state: string
  thumbnail_asset_id?: string
  created_at: string
  company_id?: string
  pages?: Page[]
  notes?: Note[]
  deleted_at?: string
}
export interface Dashboard {
  documents: number
  companies: number
  contacts: number
  notes: number
  grouping: number
  proposed_changes?: number
  grouping_overdue?: number
  failed?: number
  waiting_reason?: string
  activity?: unknown[]
  review: number
  processing: Record<string, number>
  recent: Document[]
  providers: { provider: string; state: string }[]
  phone_queue: any[]
}
