/// <reference lib="webworker" />
import { cleanupOutdatedCaches, precacheAndRoute, createHandlerBoundToURL } from 'workbox-precaching'
import { registerRoute, NavigationRoute } from 'workbox-routing'
import { clientsClaim } from 'workbox-core'
import { meta, queueFiles } from './queue'

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: { url: string; revision: string | null }[] }
cleanupOutdatedCaches()
precacheAndRoute(self.__WB_MANIFEST)
registerRoute(new NavigationRoute(createHandlerBoundToURL('/index.html'), { denylist: [/^\/api\//, /^\/mcp/, /^\/share-target/] }))
clientsClaim()
self.addEventListener('message', event => { if (event.data?.type === 'SKIP_WAITING') void self.skipWaiting() })
// Never cache API responses, notes, originals, authentication, or export downloads.
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url)
  if (url.origin !== self.location.origin || url.pathname !== '/share-target' || event.request.method !== 'POST') return
  event.respondWith((async () => {
    try {
      const form = await event.request.formData()
      const files = form.getAll('files').filter((value): value is File => typeof value !== 'string')
      await queueFiles(files, await meta<string>('activeExpo') ?? '', undefined, 'other', { autoProcess: true })
      return Response.redirect('/capture?shared=1', 303)
    } catch { return Response.redirect('/capture?share_failed=1', 303) }
  })())
})
