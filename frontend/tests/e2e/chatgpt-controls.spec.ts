import { test, expect } from '@playwright/test'

test('ChatGPT login, logout and processing status stay distinct', async ({ page, context }) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  let connected = false,
    state = 'idle'
  await page.route('**/api/v1/settings/providers', async (route) => {
    const response = await route.fetch()
    const data = await response.json()
    data.cloud_fallback = false
    const chatgpt = data.providers.find((row: any) => row.provider === 'chatgpt')
    Object.assign(chatgpt, {
      enabled: connected,
      state: 'off',
      active_account: 'fictional',
      accounts: [{ id: 'fictional', label: 'test@example.invalid', connected, plan_enabled: true }],
    })
    await route.fulfill({ response, json: data })
  })
  await page.route('**/api/v1/settings/providers/chatgpt/sign-in**', (route) => {
    if (route.request().method() === 'DELETE') {
      state = 'idle'
      return route.fulfill({ json: { state } })
    }
    if (route.request().method() === 'POST') {
      state = 'waiting'
      return route.fulfill({
        json: { authorization_url: 'https://auth.openai.com/fictional-consent' },
      })
    }
    return route.fulfill({
      json: {
        state,
        message: state === 'connected' ? 'ChatGPT connected.' : 'Waiting for consent',
      },
    })
  })
  await context.route('https://auth.openai.com/**', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<h1>Fictional OpenAI consent</h1>' }),
  )
  await page.route('**/api/v1/settings/providers/chatgpt/disconnect', (route) => {
    connected = false
    return route.fulfill({ json: { signed_out: true, remote_revocation_confirmed: true } })
  })
  await page.goto('/settings')
  const card = page
    .locator('.provider-card')
    .filter({ has: page.getByRole('heading', { name: /ChatGPT plan/ }) })
  await expect(card.getByText('Signed out', { exact: true })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Sign out of ChatGPT', exact: true })).toHaveCount(
    0,
  )
  const popup = page.waitForEvent('popup')
  await card.getByRole('button', { name: 'Sign in on server PC', exact: true }).click()
  const consent = await popup
  await expect(consent.getByRole('heading')).toHaveText('Fictional OpenAI consent')
  connected = true
  state = 'connected'
  await expect(card.getByText('Connected', { exact: true })).toBeVisible({ timeout: 10000 })
  await expect(card.getByLabel('Use my ChatGPT plan')).toBeChecked()
  await expect(card.getByText('Account connected. Card processing is off.')).toBeVisible()
  await card.getByRole('button', { name: 'Sign out of ChatGPT', exact: true }).click()
  await expect(card.getByText('Signed out', { exact: true })).toBeVisible()
  await expect(
    card.getByRole('button', { name: 'Sign in on server PC', exact: true }),
  ).toBeEnabled()
  await expect(card.getByRole('button', { name: 'Sign out of ChatGPT', exact: true })).toHaveCount(
    0,
  )
  state = 'idle'
  const retryPopup = page.waitForEvent('popup')
  await card.getByRole('button', { name: 'Sign in on server PC', exact: true }).click()
  const retryConsent = await retryPopup
  await card.getByRole('button', { name: 'Cancel sign-in', exact: true }).click()
  await expect(
    card.getByRole('button', { name: 'Sign in on server PC', exact: true }),
  ).toBeEnabled()
  await retryConsent.close()
  await consent.close()
})
