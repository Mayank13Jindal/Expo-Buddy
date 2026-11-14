import { test, expect } from '@playwright/test'

test('repair replaces a stale shell and preserves queued captures', async ({ page }) => {
  await page.goto('/api/v1/app-repair')
  await expect(page.getByRole('button', { name: 'Update and open library' })).toBeEnabled()
  await page.goto('/')
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.register('/sw.js')
    await navigator.serviceWorker.ready
    registration.waiting?.postMessage({ type: 'SKIP_WAITING' })
    const request = indexedDB.open('expo-capture', 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('queue', { keyPath: 'id' }).createIndex('kind', 'kind')
      request.result.createObjectStore('meta', { keyPath: 'key' })
    }
    await new Promise<void>((resolve, reject) => {
      request.onsuccess = () => {
        const db = request.result
        const tx = db.transaction('meta', 'readwrite')
        tx.objectStore('meta').put({ key: 'repair-test', value: 'preserved' })
        tx.oncomplete = () => {
          db.close()
          resolve()
        }
        tx.onerror = () => reject(tx.error)
      }
      request.onerror = () => reject(request.error)
    })
    for (const name of await caches.keys()) {
      if (!name.startsWith('workbox-precache-')) continue
      const cache = await caches.open(name)
      for (const key of await cache.keys()) {
        if (new URL(key.url).pathname === '/index.html') {
          await cache.put(
            key,
            new Response('<h1>Old cached app</h1>', { headers: { 'Content-Type': 'text/html' } }),
          )
        }
      }
    }
  })
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Old cached app' })).toBeVisible()
  await page.goto('/api/v1/app-repair')
  await page.getByRole('button', { name: 'Update and open library' }).click()
  await expect(page.getByRole('heading', { name: 'Old cached app' })).toHaveCount(0)
  await expect(page.locator('#root')).not.toBeEmpty()
  expect(
    await page.evaluate(async () => {
      return new Promise((resolve) => {
        const request = indexedDB.open('expo-capture', 1)
        request.onsuccess = () => {
          const db = request.result
          const read = db.transaction('meta').objectStore('meta').get('repair-test')
          read.onsuccess = () => {
            resolve(read.result?.value)
            db.close()
          }
        }
      })
    }),
  ).toBe('preserved')
  const mode = await (await page.request.get('/api/v1/auth/status')).json()
  if (mode.password_required) {
    await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
    await page.getByRole('button', { name: /Create my library|Sign in/, exact: true }).click()
    await expect(
      page.getByRole('heading', { name: 'Your expo library.', exact: true }),
    ).toBeVisible()
  }
  await page.goto('/api/v1/app-repair?auto=1&next=settings')
  await expect(page).toHaveURL(/\/settings\?updated=/)
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
})
