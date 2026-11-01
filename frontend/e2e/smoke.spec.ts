import { expect, test } from '@playwright/test'

const username = process.env.E2E_USERNAME
const password = process.env.E2E_PASSWORD

test('login, token e alerta funcionam em viewport móvel e notebook', async ({ page }) => {
  test.skip(!username || !password, 'Defina E2E_USERNAME e E2E_PASSWORD para usar o backend local.')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/login')
  await page.getByLabel('Usuário').fill(username!)
  await page.getByLabel('Senha').fill(password!)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL('/')
  const mainNav = page.locator('nav[aria-label="Navegação principal"]').first()
  await expect(mainNav.locator('a')).toHaveCount(4)
  expect(await mainNav.locator('a').evaluateAll(links => links.map(link => link.getAttribute('aria-label')))).toEqual([
    'Dashboard', 'Compre agora', 'Alertas', 'Configurações',
  ])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Abrir menu' }).click()
  await page.locator('nav[aria-label="Navegação principal"]:visible').last().getByRole('link', { name: 'Compre agora' }).click()
  const opportunity = page.locator('main a[aria-label][href^="/tokens/"]').first()
  await expect(opportunity).toBeVisible()
  await opportunity.click()
  await expect(page).toHaveURL(/\/tokens\/solana\/.+/)
  await page.goto('/tokens')
  const tokenLink = page.locator('tbody a[href^="/tokens/"]').first()
  await expect(tokenLink).toBeVisible()
  await tokenLink.click()
  const alertsResponse = await page.request.get('/api/v1/alerts?status=open&severity=high&severity=critical&page_size=10')
  const alerts = await alertsResponse.json() as { items: Array<{ title: string; link: string | null; token: { address: string } | null }> }
  const linkedAlert = alerts.items.find(alert => alert.link?.startsWith('/tokens/') && alert.token)
  test.skip(!linkedAlert, 'A API local não retornou alerta ligado a um token.')
  await page.getByRole('button', { name: /Alertas prioritários/ }).click()
  const alertLink = page.getByRole('button').filter({ hasText: linkedAlert!.title }).first()
  await expect(alertLink).toBeVisible()
  await alertLink.click()
  await expect(page).toHaveURL(new RegExp(`${linkedAlert!.token!.address}$`))
  await page.setViewportSize({ width: 1366, height: 768 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
