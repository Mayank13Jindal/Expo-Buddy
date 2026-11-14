import { test, expect } from '@playwright/test'

test('simple capture, visible directories/export, reprocessing and ChatGPT connection controls', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page.goto('/capture')
  await expect(page.getByRole('button', { name: 'Choose from gallery', exact: true })).toBeEnabled()
  await expect(page.getByLabel('Next booth label')).not.toBeVisible()
  await expect(page.locator('textarea:visible')).toHaveCount(1)
  if (test.info().project.name === 'phone') {
    const camera = await page.getByRole('button', { name: 'Take photo', exact: true }).boundingBox()
    expect(camera).not.toBeNull()
    expect(camera!.y + camera!.height).toBeLessThan(page.viewportSize()!.height - 70)
  }
  await page
    .getByLabel('Capture note')
    .fill('FICTIONAL simple capture note: check the company logo')
  await page.locator('input[type=file][multiple]').setInputFiles({
    name: 'FICTIONAL-SIMPLE.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=',
      'base64',
    ),
  })
  await expect(page.getByText('1 of 1 saved', { exact: true })).toBeVisible({ timeout: 30000 })
  const id = await page.evaluate(async () => {
    const preference = await (await fetch('/api/v1/preferences')).json()
    const docs = await (
      await fetch('/api/v1/documents?expo_id=' + preference.active_expo_id)
    ).json()
    return docs.find(
      (row: { processing_options?: { instructions?: string } }) =>
        row.processing_options?.instructions ===
        'FICTIONAL simple capture note: check the company logo',
    ).id as string
  })
  await page.goto('/documents/' + id)
  await expect(
    page.getByText('FICTIONAL simple capture note: check the company logo', { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'From photo to contact', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Ask AI again', exact: true }).click()
  await page
    .getByLabel('Note or instructions for AI')
    .fill('Compare O and zero; do not guess the email')
  await page.getByRole('button', { name: 'Reprocess with these instructions', exact: true }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  const doc = await page.evaluate(async (id) => (await fetch('/api/v1/documents/' + id)).json(), id)
  expect(doc.processing_options.instructions).toContain('Compare O and zero')
  expect(doc.group_state).toBe('confirmed')
  await page.goto('/library/people')
  await expect(page.getByRole('heading', { name: 'People', exact: true })).toBeVisible()
  await page
    .getByRole('navigation', { name: 'Browse scanned records' })
    .getByRole('link', { name: 'Companies', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: 'Companies', exact: true })).toBeVisible()
  await page
    .getByRole('navigation', { name: 'Browse scanned records' })
    .getByRole('link', { name: 'Export', exact: true })
    .click()
  await expect(page).toHaveURL(/\/exports/)
  await page.goto('/settings#ai')
  await page.getByRole('button', { name: 'Connect from another PC', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Continue with ChatGPT' })).toBeVisible()
  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download PC sign-in helper', exact: true }).click()
  expect((await downloadEvent).suggestedFilename()).toBe('expo-chatgpt-connect.zip')
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})

test('provider status refresh preserves unsaved model, pin and cloud choices', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page.goto('/settings#ai')
  const model = page.locator('.provider-card').first().locator('input[list]')
  await expect(model).toBeVisible()
  await page.route('**/api/v1/settings/providers/ollama/models', (route) =>
    route.fulfill({
      json: {
        models: [
          {
            id: 'fictional-unsaved-pinned-model',
            name: 'Fictional model',
            digest: 'fictional-pinned-digest-123',
          },
        ],
      },
    }),
  )
  await page
    .locator('.provider-card')
    .first()
    .getByRole('button', { name: 'Load available models', exact: true })
    .click()
  await page.getByLabel('Choose an available model').selectOption('fictional-unsaved-pinned-model')
  await expect(page.getByText(/Version pinned: fictional-pinned/)).toBeVisible()
  const cloud = page.getByLabel('Allow cloud processing with my connected providers')
  await cloud.setChecked(!(await cloud.isChecked()))
  const checked = await cloud.isChecked()
  await page.route('**/api/v1/settings/providers', async (route) => {
    const response = await route.fetch()
    const data = await response.json()
    data.providers[0].state = 'fictional_status_refresh'
    await route.fulfill({ response, json: data })
  })
  const refreshed = page.waitForResponse((response) =>
    response.url().endsWith('/api/v1/settings/providers'),
  )
  await page.evaluate(() => window.dispatchEvent(new Event('capture-synced')))
  await refreshed
  await expect(page.getByText('fictional status refresh', { exact: true })).toBeVisible()
  await expect(model).toHaveValue('fictional-unsaved-pinned-model')
  await expect(page.getByText(/Version pinned: fictional-pinned/)).toBeVisible()
  expect(await cloud.isChecked()).toBe(checked)
})
