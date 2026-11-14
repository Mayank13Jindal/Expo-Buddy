import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
test.skip(
  !process.env.AUDIT_STABILITY_FIXTURES,
  'Only run against the isolated synthetic audit stack',
)
const cwd = fileURLToPath(new URL('../../..', import.meta.url))
async function open(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
}

test('warnings, exact search entities, missing documents, titles and view-only rotation work at 320px', async ({
  page,
}, info) => {
  await open(page)
  const suffix = info.project.name + ' ' + Date.now()
  const ids = await page.evaluate(async (suffix) => {
    const csrf = document.cookie
      .split('; ')
      .find((x) => x.startsWith('expo_csrf='))!
      .split('=')[1]
    const result = []
    for (const name of ['KOSOL', 'VSOLE'])
      result.push(
        await (
          await fetch('/api/v1/companies', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
            body: JSON.stringify({ fields: { display_name: name + ' ' + suffix } }),
          })
        ).json(),
      )
    const people = await (await fetch('/api/v1/contacts')).json()
    const person = people.find(
      (row: { source_document_id?: string; review_status: string }) =>
        row.source_document_id && row.review_status === 'needs_attention',
    )
    return { company: result[0].id, person: person.id, document: person.source_document_id }
  }, suffix)
  await page.goto('/library?q=KOSOL')
  await page.getByLabel('All expos', { exact: true }).check()
  await expect(page.locator('.document-card').filter({ hasText: 'KOSOL ' + suffix })).toBeVisible()
  await expect(page.locator('.document-card').filter({ hasText: 'VSOLE ' + suffix })).toHaveCount(0)
  const companyCard = page.locator('.document-card').filter({ hasText: 'KOSOL ' + suffix })
  await expect(companyCard.getByRole('link')).toHaveAttribute('href', '/companies/' + ids.company)
  await expect(companyCard).toContainText('COMPANY')
  await expect(companyCard).not.toContainText('NOTE')
  await expect(companyCard.locator('input[type=checkbox]')).toBeDisabled()
  await page.goto('/library/people')
  const person = page
    .locator('.person-card')
    .filter({ has: page.locator(`a[href="/documents/${ids.document}"]`) })
    .first()
  await expect(person.locator('.contact-review-warning')).toBeVisible()
  await page.setViewportSize({ width: 320, height: 900 })
  await page.goto('/documents/' + ids.document)
  await expect(page.locator('main h1')).toBeVisible()
  await expect(page).toHaveTitle(/.+ · Expo Buddy/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  const before = await page.evaluate(
    async (id) => (await (await fetch('/api/v1/documents/' + id)).json()).revision,
    ids.document,
  )
  await page.getByRole('button', { name: 'Rotate view', exact: true }).click()
  const transform = await page
    .locator('.source-panel .evidence-image')
    .evaluate((el) => getComputedStyle(el).transform)
  expect(transform).not.toBe('none')
  const after = await page.evaluate(
    async (id) => (await (await fetch('/api/v1/documents/' + id)).json()).revision,
    ids.document,
  )
  expect(after).toBe(before)
  await page.goto('/documents/missing-document')
  await expect(page.getByRole('heading', { name: 'Document not found', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Back to library', exact: true })).toBeVisible()
  await expect(page).toHaveTitle('Document not found · Expo Buddy')
  await page.goto('/library')
  await page.getByText('More filters', { exact: true }).click()
  await page.getByLabel('Company ID', { exact: true }).fill('00000000-0000-4000-8000-000000000000')
  await expect(page.getByRole('heading', { name: 'No matching records' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Clear filters' })).toBeVisible()
  await expect(page.getByText('Add your first files', { exact: true })).toHaveCount(0)
})

test('metadata timeout and failed worker have bounded and distinct retry states', async ({
  page,
}) => {
  test.setTimeout(60000)
  await open(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let block = true
  await page.route('**/api/v1/settings/providers', async (route) => {
    if (block) {
      await gate
      await route.abort().catch(() => {})
    } else await route.continue()
  })
  await page.goto('/settings')
  await page.bringToFront()
  await expect(page.getByRole('button', { name: 'Retry ai connections', exact: true })).toBeVisible(
    { timeout: 35000 },
  )
  await expect(page.getByText(/took too long to respond/)).toBeVisible()
  block = false
  release()
  await page.getByRole('button', { name: 'Retry ai connections', exact: true }).click()
  await expect(page.getByRole('heading', { name: /ChatGPT plan/ })).toBeVisible()
  await page.route('**/api/v1/system/status', (route) =>
    route.fulfill({
      status: 503,
      json: {
        status: 'unavailable',
        services: { database: 'ready', schema: 'ready', worker: 'stale' },
        storage: [],
        jobs: {},
        models: [],
        errors: [],
      },
    }),
  )
  await page.goto('/health')
  await expect(page.locator('.status-row').filter({ hasText: 'worker' })).toContainText('stale')
  await expect(page.getByRole('button', { name: 'Retry system health', exact: true })).toBeVisible()
  await expect(page.getByText('Checking services', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/Server unreachable/)).toHaveCount(0)
})

test('same browser recovers from an actual API restart and syncs its retained capture exactly once', async ({
  page,
}, info) => {
  test.setTimeout(90000)
  await open(page)
  const id = await page.evaluate(async (mode) => {
    const csrf = document.cookie
      .split('; ')
      .find((x) => x.startsWith('expo_csrf='))!
      .split('=')[1]
    return (
      await (
        await fetch('/api/v1/expos', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
          body: JSON.stringify({ name: 'SYNTHETIC Restart ' + mode + ' ' + Date.now() }),
        })
      ).json()
    ).id as string
  }, info.project.name)
  await page.reload()
  await page.getByLabel('Active expo').selectOption(id)
  await page.waitForFunction(
    (id) =>
      new Promise<boolean>((resolve) => {
        const request = indexedDB.open('expo-capture', 1)
        request.onsuccess = () => {
          const db = request.result
          const get = db.transaction('meta').objectStore('meta').get('activeExpo')
          get.onsuccess = () => {
            resolve(get.result?.value === id)
            db.close()
          }
        }
      }),
    id,
  )
  await page.goto('/capture')
  await expect(page.getByLabel('Active expo')).toHaveValue(id)
  await expect(page.getByRole('button', { name: 'Choose from gallery', exact: true })).toBeEnabled()
  try {
    execFileSync(
      'docker',
      [
        'compose',
        '--env-file',
        '.local/audit/.env',
        '-p',
        'expo-buddy-audit',
        'stop',
        '-t',
        '2',
        'api',
      ],
      { cwd, stdio: 'pipe' },
    )
    await page.locator('input[type=file][multiple]').setInputFiles({
      name: 'SYNTHETIC-restart.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=',
        'base64',
      ),
    })
    await expect(page.locator('strong').filter({ hasText: 'SYNTHETIC-restart.png' })).toBeVisible()
    await page.locator('a[href="/"]:visible').first().click()
    await expect(page.getByText('Review status unavailable', { exact: true })).toBeVisible({
      timeout: 20000,
    })
    await expect(page.getByText('Group status unavailable', { exact: true })).toBeVisible()
    await expect(page.getByText('Phone queue status unavailable.', { exact: true })).toBeVisible()
    await expect(page.getByText(/Backup is current/)).toHaveCount(0)
  } finally {
    execFileSync(
      'docker',
      [
        'compose',
        '--env-file',
        '.local/audit/.env',
        '-p',
        'expo-buddy-audit',
        'up',
        '-d',
        '--no-deps',
        '--no-build',
        '--wait',
        'api',
      ],
      { cwd, stdio: 'pipe' },
    )
  }
  await expect(page.getByText('Review status unavailable', { exact: true })).toHaveCount(0, {
    timeout: 20000,
  })
  await page.goto('/capture')
  await page.getByRole('button', { name: 'Sync now', exact: true }).click()
  await expect(page.getByText('1 of 1 saved', { exact: true })).toBeVisible({ timeout: 30000 })
  await page.getByRole('button', { name: 'Sync now', exact: true }).click()
  const docs = await page.evaluate(
    async (id) => (await (await fetch('/api/v1/documents?expo_id=' + id)).json()).length,
    id,
  )
  expect(docs).toBe(1)
})
