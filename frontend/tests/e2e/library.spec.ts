import { test, expect } from '@playwright/test'

test('setup, persistent expo, upload and notes work on desktop and phone', async ({
  page,
}, testInfo) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: /Create my library|Sign in/, exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page.goto('/expos')
  await page.getByRole('button', { name: 'New expo', exact: true }).click()
  const name = `Fictional Solar Expo ${testInfo.project.name} ${Date.now()}`
  await page.getByLabel('Expo name').fill(name)
  await page.getByLabel('City', { exact: true }).fill('Example City')
  await page.getByRole('button', { name: 'Create expo', exact: true }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  const card = page.locator('article').filter({ has: page.getByRole('heading', { name }) })
  const use = card.getByRole('button', { name: 'Use this expo' })
  if (await use.count()) {
    await use.click()
    await expect(card.getByRole('button', { name: 'Selected', exact: true })).toBeVisible()
  }
  await page.reload()
  await expect(page.getByLabel('Active expo')).toHaveValue(
    (await page
      .getByLabel('Active expo')
      .locator('option')
      .filter({ hasText: name })
      .getAttribute('value')) as string,
  )
  await page.goto('/upload')
  const bytes = await page.evaluate(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 600
    canvas.height = 350
    const context = canvas.getContext('2d')!
    context.fillStyle = '#fff'
    context.fillRect(0, 0, 600, 350)
    context.fillStyle = '#183f34'
    context.font = '30px sans-serif'
    context.fillText('FICTIONAL SOLAR COMPANY', 30, 65)
    context.font = '24px sans-serif'
    context.fillText('FAKE CONTACT — TEST ONLY', 30, 120)
    context.fillText('example@example.invalid', 30, 170)
    return Array.from(
      Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]), (char) =>
        char.charCodeAt(0),
      ),
    )
  })
  await page
    .locator('input[type=file][multiple]')
    .setInputFiles({ name: 'FAKE-CARD.png', mimeType: 'image/png', buffer: Buffer.from(bytes) })
  await expect(page.getByText('1 of 1 saved')).toBeVisible({ timeout: 30000 })
  await page.goto('/library')
  await page.getByRole('heading', { name: 'FAKE-CARD.png' }).first().click()
  await page.getByLabel('New note').fill('Fictional note: solar structure sample requested.')
  await page.getByRole('button', { name: 'Add note', exact: true }).click()
  await expect(
    page.getByText('Fictional note: solar structure sample requested.', { exact: true }),
  ).toBeVisible()
  await page.goto('/')
  await page.screenshot({
    path: `test-results/stage1-${testInfo.project.name}.png`,
    fullPage: true,
  })
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy()
})

test('saved searches, selection, bulk undo and command palette', async ({ page }, info) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page.goto('/library?q=solar%20structure%20sample%20requested')
  await expect(page.getByRole('heading', { name: 'FAKE-CARD.png' }).first()).toBeVisible({
    timeout: 20000,
  })
  page.once('dialog', (dialog) => dialog.accept(`Fictional saved search ${info.project.name}`))
  await page.getByRole('button', { name: 'Save search', exact: true }).click()
  await expect(
    page
      .getByRole('button', { name: `Fictional saved search ${info.project.name}`, exact: true })
      .first(),
  ).toBeVisible()
  await page.goto('/library')
  await page.getByRole('checkbox', { name: 'Select FAKE-CARD.png', exact: true }).first().check()
  await expect(page).toHaveURL(/\/library$/)
  await page.getByRole('button', { name: 'Reviewed', exact: true }).click()
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  if (info.project.name === 'desktop') {
    await page.keyboard.press('Control+k')
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.keyboard.press('Escape')
  }
})
