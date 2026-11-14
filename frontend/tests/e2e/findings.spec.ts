import { test, expect } from '@playwright/test'

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'wait' })
})

test.skip(
  !process.env.AUDIT_FINDINGS_FIXTURES,
  'Requires synthetic findings fixtures in the isolated audit stack',
)
async function open(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
}

test('search, multiline address editing, review decisions, people empty states and export sample are honest', async ({
  page,
}, info) => {
  await open(page)
  const fixture = await page.evaluate(async (mode) => {
    const docs = await (await fetch('/api/v1/documents?limit=500')).json()
    return docs.find((row: { title: string }) =>
      row.title.startsWith('SYNTHETIC findings ' + mode + ' '),
    ) as {
      id: string
      company_id: string
      expo_id: string
    }
  }, info.project.name)
  expect(fixture).toBeTruthy()
  await page.getByLabel('Active expo').selectOption(fixture.expo_id)
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
    fixture.expo_id,
  )
  await page.goto('/library?q=zzqvwx987654321')
  await expect(page.getByText('No matching records', { exact: true })).toBeVisible()
  await expect(page.getByText('Printed text match', { exact: true })).toHaveCount(0)
  await page.getByLabel('Include related meanings').check()
  await expect(page.getByText('No matching records', { exact: true })).toBeVisible()
  await page.goto('/documents/' + fixture.id)
  await expect(page.getByLabel('Office address', { exact: true })).toHaveValue(
    'New Colony\nSoyepur',
  )
  await expect(page.getByRole('button', { name: 'Mark reviewed', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Edit company', exact: true }).click()
  let editor = page.getByRole('dialog', { name: 'Edit company' })
  await expect(editor.getByLabel('Value of detail 1')).toHaveValue('New Colony\nSoyepur')
  await editor.getByLabel('Value of detail 1').fill('CANCELLED ADDRESS EDIT')
  await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('button', { name: 'Edit company', exact: true }).click()
  editor = page.getByRole('dialog', { name: 'Edit company' })
  await expect(editor.getByLabel('Value of detail 1')).toHaveValue('New Colony\nSoyepur')
  await editor.getByRole('button', { name: 'Save corrections', exact: true }).click()
  await expect(editor).toHaveCount(0)
  const stored = await page.evaluate(
    async (id) => (await (await fetch('/api/v1/companies/' + id)).json()).channels[0].raw,
    fixture.company_id,
  )
  expect(stored).toBe('New Colony\nSoyepur')
  const evidence = page.locator('.field-evidence').first()
  await expect(evidence).toBeVisible()
  for (const theme of ['light', 'dark']) {
    const contrast = await evidence.evaluate((element, theme) => {
      document.documentElement.dataset.theme = theme
      const rgb = (value: string) =>
        value
          .match(/[\d.]+/g)!
          .slice(0, 3)
          .map(Number)
      const luminance = (values: number[]) =>
        values
          .map((x) => {
            x /= 255
            return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
          })
          .reduce((sum, x, i) => sum + x * [0.2126, 0.7152, 0.0722][i], 0)
      let parent: Element | null = element
      while (parent && getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)')
        parent = parent.parentElement
      const foreground = luminance(rgb(getComputedStyle(element).color)),
        background = luminance(rgb(getComputedStyle(parent!).backgroundColor))
      return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05)
    }, theme)
    expect(contrast).toBeGreaterThanOrEqual(4.5)
  }
  await page.evaluate(() => (document.documentElement.dataset.theme = 'light'))
  await page.goto('/review')
  const reviewDoc = page
    .locator('.review-document')
    .filter({ has: page.locator(`a[href="/documents/${fixture.id}"]`) })
  await expect(reviewDoc.getByRole('button', { name: 'Mark reviewed', exact: true })).toBeDisabled()
  await page.goto('/library/people')
  await page.getByLabel('Find a person').fill('zzqvwx987654321')
  await expect(page.getByText('No people match this search', { exact: true })).toBeVisible()
  await expect(page.getByText('No people saved yet', { exact: true })).toHaveCount(0)
  const contactCount = await page.evaluate(
    async (id) => (await (await fetch('/api/v1/contacts?expo_id=' + id)).json()).length,
    fixture.expo_id,
  )
  expect(contactCount).toBeGreaterThanOrEqual(7)
  await page.goto('/exports')
  await page.getByRole('button', { name: '4 Preview', exact: true }).click()
  await expect(
    page.getByText(
      `Showing 5 of ${contactCount} rows. Preview sample only; the export contains all selected rows.`,
      { exact: true },
    ),
  ).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('Overview removes success claims immediately when a previously reachable server fails', async ({
  page,
}) => {
  await open(page)
  await expect(page.locator('.stat-card strong').first()).not.toHaveText('—')
  await page.route('**/api/v1/**', (route) => route.abort('connectionfailed'))
  await expect(page.getByText(/Server unreachable/)).toBeVisible({ timeout: 15000 })
  await expect(
    page.getByText('Processing status unavailable. Reconnect to check progress.', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText('Backup status unavailable. Reconnect to verify your last backup.', {
      exact: true,
    }),
  ).toBeVisible()
  await expect(page.getByText('All caught up', { exact: true })).toHaveCount(0)
  await expect(page.getByText('No processing work waiting', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/Backup is current/)).toHaveCount(0)
  await expect(page.getByText(/Invalid Date/)).toHaveCount(0)
  await page.locator('a[href="/review"]:visible').first().click()
  await expect(page.getByRole('alert').first()).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('Everything looks good', { exact: true })).toHaveCount(0)
})

test('Overview and Settings distinguish connected ChatGPT from disabled cloud processing', async ({
  page,
}) => {
  await open(page)
  await page.route('**/api/v1/dashboard*', async (route) => {
    const response = await route.fetch(),
      data = await response.json()
    const chatgpt = data.providers.find((row: { provider: string }) => row.provider === 'chatgpt')
    Object.assign(chatgpt, {
      connected: true,
      enabled: true,
      processing_allowed: false,
      state: 'ready',
    })
    await route.fulfill({ response, json: data })
  })
  await page.route('**/api/v1/settings/providers', async (route) => {
    const response = await route.fetch(),
      data = await response.json()
    data.cloud_fallback = false
    const chatgpt = data.providers.find((row: { provider: string }) => row.provider === 'chatgpt')
    Object.assign(chatgpt, {
      enabled: true,
      active_account: 'synthetic',
      accounts: [
        { id: 'synthetic', label: 'Fictional account', connected: true, plan_enabled: true },
      ],
      state: 'ready',
    })
    await route.fulfill({ response, json: data })
  })
  await page.reload()
  const overview = page.locator('.status-row').filter({ hasText: 'ChatGPT' })
  await expect(overview.getByText('Connected', { exact: true })).toBeVisible()
  await expect(overview.getByText('Processing: off', { exact: true })).toBeVisible()
  await page.goto('/settings')
  const card = page
    .locator('.provider-card')
    .filter({ has: page.getByRole('heading', { name: /ChatGPT plan/ }) })
  await expect(card.getByText('Connected', { exact: true })).toBeVisible()
  await expect(
    card.getByText('Account connected. Card processing is off.', { exact: true }),
  ).toBeVisible()
})
