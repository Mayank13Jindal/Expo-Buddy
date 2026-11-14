import { test, expect } from '@playwright/test'

test('agent token is shown once, activity is visible, and revocation blocks access', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page.goto('/settings')
  await page.getByText('Agent access (Hermes)', { exact: true }).click()
  await page.getByRole('button', { name: 'New agent token', exact: true }).click()
  const name = `Fictional Hermes ${Date.now()}`
  await page.getByLabel('Agent name', { exact: true }).fill(name)
  await page.getByRole('button', { name: 'Create token', exact: true }).click()
  const value = await page.getByLabel('Agent token', { exact: true }).inputValue()
  expect(value).toMatch(/^expo_/)
  await page.getByRole('button', { name: 'I have saved it', exact: true }).click()
  expect(await page.getByLabel('Agent token', { exact: true }).count()).toBe(0)
  const status = await page.evaluate(async value => (await fetch('/mcp', { method:'POST',headers: { Authorization:'Bearer '+value,'Content-Type':'application/json',Accept:'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/list',params:{}}) })).status, value)
  expect(status).toBe(200)
  await page.getByRole('button', { name:`Revoke ${name}`,exact:true }).click()
  await expect(page.getByRole('status')).toContainText('Agent token revoked.')
  expect(await page.evaluate(async value => (await fetch('/mcp', { method:'POST',headers:{Authorization:'Bearer '+value,'Content-Type':'application/json'},body:'{}' })).status,value)).toBe(401)
})
