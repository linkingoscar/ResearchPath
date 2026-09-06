import { expect, test } from '@playwright/test'
import { openAuthenticatedPage } from './session'
import {
  expectNoHorizontalOverflow,
  expectPrdBreakpointUsability,
  expectNoSeriousAccessibilityViolations,
  installPageFailureMonitor,
} from './quality'

test('@smoke @a11y PRD workbench shell is keyboard-first, responsive, and free of global glass', async ({ page }) => {
  const failures = await installPageFailureMonitor(page)
  await openAuthenticatedPage(page)
  await page.getByRole('button', { name: /导入数据并开始分析/ }).click()

  const dataTab = page.getByRole('tab', { name: '数据', exact: true })
  const analysisTab = page.getByRole('tab', { name: '分析', exact: true })
  const outputTab = page.getByRole('tab', { name: '输出', exact: true })
  await expect(dataTab).toHaveAttribute('aria-selected', 'true')
  await expect(analysisTab).toHaveAttribute('aria-selected', 'false')
  await expect(outputTab).toHaveAttribute('aria-selected', 'false')

  const shellDecoration = await page.evaluate(() => {
    const read = (selector: string) => {
      const element = document.querySelector<HTMLElement>(selector)
      if (!element) throw new Error(`missing ${selector}`)
      const style = getComputedStyle(element)
      return {
        backdropFilter: style.backdropFilter,
        webkitBackdropFilter: style.getPropertyValue('-webkit-backdrop-filter'),
      }
    }
    return { header: read('.app-header'), navigation: read('.workspace-nav') }
  })
  expect(shellDecoration.header.backdropFilter).toBe('none')
  expect(shellDecoration.navigation.backdropFilter).toBe('none')
  expect(['', 'none']).toContain(shellDecoration.header.webkitBackdropFilter)
  expect(['', 'none']).toContain(shellDecoration.navigation.webkitBackdropFilter)

  await dataTab.focus()
  await page.keyboard.press('End')
  await expect(outputTab).toHaveAttribute('aria-selected', 'true')
  await expect(outputTab).toBeFocused()
  await page.keyboard.press('Home')
  await expect(dataTab).toHaveAttribute('aria-selected', 'true')
  await expect(dataTab).toBeFocused()

  const skipLink = page.locator('.skip-link')
  await skipLink.focus()
  await expect(skipLink).toBeFocused()
  await skipLink.press('Enter')
  await expect(page.locator('#workspace-panel-data')).toBeFocused()

  await expectNoSeriousAccessibilityViolations(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await expectNoHorizontalOverflow(page)
  await expect(page.locator('#primary-workspace-nav')).toBeVisible()
  await expectNoSeriousAccessibilityViolations(page)
  await failures.expectClean()
})

test('@smoke @a11y dense workspaces remain usable at PRD breakpoints', async ({ page }) => {
  const failures = await installPageFailureMonitor(page)
  await openAuthenticatedPage(page)
  await page.getByRole('button', { name: /导入数据并开始分析/ }).click()
  await page.getByRole('button', { name: '一键导入经典问卷示例项目' }).click()
  await expect(page.getByRole('heading', { name: '当前数据' })).toBeVisible()

  await expectPrdBreakpointUsability(page, page.getByRole('searchbox', { name: '查找案例' }))
  await page.getByRole('tab', { name: '分析', exact: true }).click()
  await expectPrdBreakpointUsability(page, page.getByRole('button', { name: '配置描述统计' }))
  await page.getByRole('tab', { name: '输出', exact: true }).click()
  await expectPrdBreakpointUsability(page, page.getByRole('searchbox', { name: '搜索输出' }))
  await failures.expectClean()
})
