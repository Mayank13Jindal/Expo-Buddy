import { test, expect } from '@playwright/test'

test('owner can link a company, add a sourced person and personal note, and edit by keyboard', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Password', { exact: true }).fill('fake-e2e-password-123')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your expo library.' })).toBeVisible()
  const id = await page.evaluate(async () => {
    const headers = {'Content-Type':'application/json','X-CSRF-Token':document.cookie.split('; ').find(value=>value.startsWith('expo_csrf='))!.split('=')[1]}
    const preference = await (await fetch('/api/v1/preferences')).json()
    const session = await (await fetch('/api/v1/upload-sessions',{method:'POST',headers,body:JSON.stringify({expo_id:preference.active_expo_id})})).json()
    const bytes=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='),x=>x.charCodeAt(0))
    const form=new FormData();form.set('file',new Blob([bytes],{type:'image/png'}),'FICTIONAL-MANUAL.png');form.set('client_uuid',crypto.randomUUID())
    return (await (await fetch(`/api/v1/upload-sessions/${session.id}/files`,{method:'POST',headers:{'X-CSRF-Token':headers['X-CSRF-Token']},body:form})).json()).document.id as string
  })
  await page.goto(`/documents/${id}`)
  await page.getByRole('button', { name: 'Link a company', exact: true }).click()
  const company = `Fictional Manual Company ${Date.now()}`
  await page.getByLabel('Or create company', { exact: true }).fill(company)
  await page.getByRole('button', { name: 'Link company', exact: true }).click()
  await expect(page.getByRole('heading', { name: company, exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Add a person', exact: true }).click()
  await page.getByLabel('Full name', { exact: true }).fill('Fictional Test Person')
  await page.getByLabel('Designation', { exact: true }).fill('Example role')
  await page.getByLabel('Phone', { exact: true }).fill('+910000000001')
  await page.getByLabel('Source document (optional)', { exact: true }).selectOption(id)
  await page.getByRole('button', { name: 'Save person', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Fictional Test Person', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Company details & history' }).click()
  await page.getByLabel('New company note', { exact: true }).fill('FICTIONAL manual orchid note')
  await page.getByRole('button', { name: 'Add note', exact: true }).click()
  await expect(page.getByText('FICTIONAL manual orchid note', { exact: true })).toBeVisible()
  if (test.info().project.name === 'desktop') {
    await page.getByRole('heading', {name:company,level:1,exact:true}).click()
    await page.keyboard.press('e')
    await expect(page.getByRole('dialog', { name: 'Edit company', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
})
