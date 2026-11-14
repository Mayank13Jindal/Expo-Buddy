import { test, expect } from '@playwright/test'

test.skip(
  !process.env.AUDIT_GROUP_FIXTURES,
  'Requires the isolated synthetic grouping fixtures in the audit report',
)

test('grouping combines, reorders, splits, confirms and undoes synthetic pages', async ({
  page,
}, info) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  await page
    .getByLabel('Active expo')
    .selectOption({ label: 'AUDIT grouping final ' + info.project.name })
  await page.getByRole('link', { name: /Check photo groups/ }).click()
  await expect(page.getByLabel('Select document')).toHaveCount(2)
  await page.getByLabel('Select document').nth(0).check()
  await page.getByLabel('Select document').nth(1).check()
  const combined = page.waitForResponse((r) => r.url().endsWith('/grouping/combine'))
  await page.getByRole('button', { name: 'Combine (2)', exact: true }).click()
  const combinedId = (await (await combined).json()).action_id
  await expect(page.getByLabel('Select document')).toHaveCount(1)
  await page.getByRole('button', { name: 'Move page 2 up', exact: true }).click()
  await page.getByRole('button', { name: 'Undo last change', exact: true }).click()
  await page.getByRole('button', { name: 'Split page', exact: true }).first().click()
  await expect(page.getByLabel('Select document')).toHaveCount(2)
  await page.getByRole('button', { name: 'Undo last change', exact: true }).click()
  await expect(page.getByLabel('Select document')).toHaveCount(1)
  // A later page edit must prevent undoing an older combine.
  const undone = await page.evaluate(async (id) => {
    const csrf = document.cookie
      .split('; ')
      .find((value) => value.startsWith('expo_csrf='))!
      .split('=')[1]
    return (
      await fetch('/api/v1/grouping/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ action_id: id }),
      })
    ).status
  }, combinedId)
  expect(undone).toBe(409)
  await page.reload()
  await expect(page.getByLabel('Select document')).toHaveCount(1)
  for (const name of ['Each file separate', 'Confirm all & start AI']) {
    await page.getByRole('button', { name, exact: true }).click()
    await page.getByRole('button', { name: 'Undo last change', exact: true }).click()
    await expect(page.getByLabel('Select document')).toHaveCount(1)
  }
  await page.getByRole('button', { name: 'Confirm & start AI', exact: true }).first().click()
  await page.getByRole('button', { name: 'Undo last change', exact: true }).click()
  await expect(page.getByLabel('Select document')).toHaveCount(1)
})
