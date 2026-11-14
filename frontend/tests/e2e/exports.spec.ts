import { test, expect } from '@playwright/test'

test('export wizard freezes documents, orders fields and downloads a ZIP', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  // Seed one fictional, unreviewed document so this test does not depend on earlier tests.
  await page.evaluate(async () => {
    const csrf = document.cookie
      .split('; ')
      .find((value) => value.startsWith('expo_csrf='))!
      .split('=')[1]
    const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }
    let { active_expo_id: expoId } = await (await fetch('/api/v1/preferences')).json()
    if (!expoId) {
      const expo = await fetch('/api/v1/expos', {
        method: 'POST',
        headers,
        body: JSON.stringify({ name: 'Fictional Export Test Expo', city: 'Example City' }),
      })
      expoId = (await expo.json()).id
    }
    const session = await (
      await fetch('/api/v1/upload-sessions', {
        method: 'POST',
        headers,
        body: JSON.stringify({ expo_id: expoId }),
      })
    ).json()
    const bytes = Uint8Array.from(
      atob(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=',
      ),
      (x) => x.charCodeAt(0),
    )
    const form = new FormData()
    form.set('file', new Blob([bytes], { type: 'image/png' }), 'FICTIONAL-EXPORT.png')
    form.set('client_uuid', crypto.randomUUID())
    const upload = await fetch(`/api/v1/upload-sessions/${session.id}/files`, {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrf },
      body: form,
    })
    if (!upload.ok) throw new Error(`Seed upload failed: ${upload.status}`)
  })
  await page.goto('/exports')
  await page.getByLabel('Scope', { exact: true }).selectOption('all')
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByLabel('Contacts', { exact: false }).uncheck()
  await page.getByLabel('Documents', { exact: false }).check()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByRole('button', { name: 'Move Title up', exact: true }).click()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByRole('columnheader', { name: 'Title', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await page.getByLabel('File format', { exact: true }).selectOption('zip')
  await expect(page.getByText(/Deselecting fields is not redaction/)).toBeVisible()
  const allow = page.getByLabel('Include unreviewed or flagged data in this export')
  await expect(allow).toBeVisible()
  await allow.check()
  await page.getByRole('button', { name: 'Generate export', exact: true }).click()
  await expect(page.locator('.toast')).toContainText(
    'Export started. Download it below when ready.',
  )
  const latest = page.locator('.recent-row').first()
  await expect(latest.locator('.badge')).toHaveText('ready', { timeout: 45000 })
  const link = latest.getByRole('link', { name: 'Download', exact: true })
  await expect(link).toBeVisible({ timeout: 45000 })
  const download = page.waitForEvent('download')
  await link.click()
  expect((await download).suggestedFilename()).toMatch(/\.zip$/)
})
