import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from '../src/api/client'

afterEach(() => vi.unstubAllGlobals())
function browser() {
  vi.stubGlobal('document', { cookie: 'expo_csrf=renewed' })
  vi.stubGlobal('window', { dispatchEvent: vi.fn() })
  vi.stubGlobal(
    'CustomEvent',
    class {
      constructor(public type: string) {}
    },
  )
}
it('renews an expired passwordless session and retries the rejected write with its new CSRF cookie', async () => {
  browser()
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response('{}', { status: 401 }))
    .mockResolvedValueOnce(Response.json({ password_required: false }))
    .mockResolvedValueOnce(Response.json({ signed_in: true }))
    .mockResolvedValueOnce(Response.json({ saved: true }))
  vi.stubGlobal('fetch', fetch)
  expect(await api('/preferences', { method: 'PATCH', body: '{}' })).toEqual({ saved: true })
  expect(fetch.mock.calls.map((call) => call[0])).toEqual([
    '/api/v1/preferences',
    '/api/v1/auth/status',
    '/api/v1/auth/open',
    '/api/v1/preferences',
  ])
  expect(fetch.mock.calls[3][1].headers.get('X-CSRF-Token')).toBe('renewed')
})
it('keeps password-required deployments protected', async () => {
  browser()
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(Response.json({ detail: 'Please sign in.' }, { status: 401 }))
    .mockResolvedValueOnce(Response.json({ password_required: true }))
  vi.stubGlobal('fetch', fetch)
  await expect(api('/preferences')).rejects.toBeInstanceOf(ApiError)
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('bounds metadata reads and preserves service failure details', async () => {
  browser()
  const fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({
      status: 'unavailable',
      services: { database: 'ready', worker: 'stale' },
    }),
  })
  vi.stubGlobal('fetch', fetch)
  try {
    await api('/system/status')
    throw new Error('Expected service failure')
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).details).toEqual({
      status: 'unavailable',
      services: { database: 'ready', worker: 'stale' },
    })
  }
  expect(fetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal)
})

it('a cancelled query does not report the server unreachable', async () => {
  browser()
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Cancelled', 'AbortError')))
  await expect(api('/documents')).rejects.toMatchObject({ name: 'AbortError' })
  expect(window.dispatchEvent).not.toHaveBeenCalled()
})

it('gateway unavailability is distinct from an expired session', async () => {
  browser()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({}) }),
  )
  await expect(api('/dashboard')).rejects.toBeInstanceOf(TypeError)
  expect(window.dispatchEvent).toHaveBeenCalled()
})
