import { test, expect } from '@playwright/test'

test('unreachable server keeps captures and an expired session requires sign-in before sync', async ({
  page,
  context,
}) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page.goto('/capture')
  await expect(page.getByRole('heading', { name: 'Keep the discovery.' })).toBeVisible()
  // The phone has internet, but its home server cannot be reached.
  await context.route('**/api/v1/**', (route) => route.abort('connectionrefused'))
  await page.getByRole('button', { name: 'Sync now', exact: true }).click()
  await expect(
    page.getByText('Server unreachable — captures stay on this device until reconnected.', {
      exact: true,
    }),
  ).toBeVisible()
  await page.locator('input[type=file][multiple]').setInputFiles({
    name: 'FAKE-SESSION-RETRY.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=',
      'base64',
    ),
  })
  await expect(page.getByRole('strong').filter({ hasText: 'FAKE-SESSION-RETRY.png' })).toBeVisible()
  await context.clearCookies()
  await context.unroute('**/api/v1/**')
  // Reopening an expired session is deterministic even if a background request signs out first.
  await page.reload()
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  expect(
    await page.evaluate(async () => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('expo-capture', 1)
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
      })
      return await new Promise<number>((resolve, reject) => {
        const request = db.transaction('queue').objectStore('queue').getAll()
        request.onsuccess = () =>
          resolve(
            request.result.filter((row) => row.filename === 'FAKE-SESSION-RETRY.png' && row.blob)
              .length,
          )
        request.onerror = () => reject(request.error)
      })
    }),
  ).toBe(1)
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Keep the discovery.' })).toBeVisible()
  await page.getByRole('button', { name: 'Sync now', exact: true }).click()
  await expect(page.getByText('1 of 1 saved', { exact: true })).toBeVisible({ timeout: 30000 })
})

test('offline app reload, new expo, booth, photo and edited note survive and sync once', async ({
  page,
  context,
}) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready
  })
  await page.goto('/capture')
  await context.setOffline(true)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Keep the discovery.' })).toBeVisible({
    timeout: 20000,
  })
  await page.getByRole('button', { name: 'New expo', exact: true }).click()
  const name = `Fictional Offline Expo ${Date.now()}`
  await page.getByLabel('Expo name', { exact: true }).fill(name)
  await page.getByRole('button', { name: 'Create expo', exact: true }).click()
  await expect(page.getByLabel('Adding to expo', { exact: true })).toContainText(name)
  const latestNote = `Fictional latest orchid note ${name}`
  await page.getByText('Front/back or booth grouping (optional)', { exact: true }).click()
  await page.getByLabel('Next booth label').fill('Fictional booth A')
  await page.getByRole('button', { name: 'New booth', exact: true }).click()
  await page.locator('input[type=file][multiple]').setInputFiles({
    name: 'FAKE-OFFLINE.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=',
      'base64',
    ),
  })
  await page.getByText('Attach a note to an earlier photo or booth', { exact: true }).click()
  await page.getByLabel('Note belongs to').selectOption('booth')
  await page.getByLabel('Capture note').fill('Fictional first note')
  await page.getByRole('button', { name: 'Keep note', exact: true }).click()
  await page.getByLabel('Edit queued note').fill(latestNote)
  await page.reload()
  await expect(page.getByLabel('Edit queued note')).toHaveValue(latestNote)
  await context.setOffline(false)
  await page.getByRole('button', { name: 'Sync now', exact: true }).click()
  await expect(page.getByText('1 of 1 saved', { exact: true })).toBeVisible({ timeout: 45000 })
  await expect(page.getByText('Everything has reached your server.', { exact: true })).toBeVisible({
    timeout: 45000,
  })
  await page.getByRole('button', { name: 'Sync now', exact: true }).click()
  const notes = await page.evaluate(async () => (await fetch('/api/v1/notes')).json())
  expect(notes.filter((row: any) => row.text === latestNote)).toHaveLength(1)
  const expoID = await page.evaluate(
    async (name) =>
      (await (await fetch('/api/v1/expos')).json()).find((row: any) => row.name === name).id,
    name,
  )
  const docs = await page.evaluate(
    async (expoID) => await (await fetch(`/api/v1/documents?expo_id=${expoID}`)).json(),
    expoID,
  )
  expect(docs.filter((row: any) => row.title === 'FAKE-OFFLINE.png')).toHaveLength(1)
  await page.goto('/library')
  await expect(page.getByRole('heading', { name: 'FAKE-OFFLINE.png' }).first()).toBeVisible()
  await page.getByRole('heading', { name: 'FAKE-OFFLINE.png' }).first().click()
  await expect(page.getByText(latestNote, { exact: true })).toBeVisible()
})
