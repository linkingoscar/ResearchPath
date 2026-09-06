import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { configureMethod, openDataWorkspace } from './session'
import { expectPrdBreakpointUsability, installPageFailureMonitor } from './quality'

async function importAndMeasure(page: Page) {
  await openDataWorkspace(page)
  await page.getByRole('radio', { name: /单次 \/ 横截面/ }).click()
  await page.getByRole('radio', { name: /观测相互独立/ }).click()
  await page.getByRole('radio', { name: /^观察性/ }).click()
  const confirm = page.getByRole('button', { name: '确认并保存研究结构' })
  if (await confirm.isVisible()) await confirm.click()
  await expect(page.getByText('研究结构已保存', { exact: true })).toBeVisible()
  const names = ['x1', 'x2', 'x3', 'm1', 'm2', 'm3', 'y1', 'y2', 'y3']
  const rows = Array.from({ length: 80 }, (_, i) => names.map((_, j) => {
    const x = Math.sin(i * 1.7)
    const m = 0.5 * x + Math.cos(i * 0.7)
    const y = 0.3 * x + 0.5 * m + Math.sin(i * 0.4)
    return (4 + [x, m, y][Math.floor(j / 3)] + 0.25 * Math.sin(i * (j + 2))).toFixed(5)
  }).join(','))
  await page.getByLabel('选择数据文件').setInputFiles({ name: 'research-journey.csv', mimeType: 'text/csv', buffer: Buffer.from([names.join(','), ...rows].join('\n')) })
  await page.getByRole('button', { name: '导入并创建数据版本' }).click()
  await page.getByRole('tab', { name: '变量视图', exact: true }).click()
  await expect(page.getByRole('heading', { name: '变量类型与识别' })).toBeVisible()
  for (const name of names) await page.getByLabel(`${name}的有效类型`).selectOption('continuous')
  await page.getByRole('button', { name: '保存变量类型' }).click()
  await expect(page.getByText('已人工确认')).toHaveCount(names.length)
  await page.getByRole('tab', { name: '量表', exact: true }).click()
  await expect(page.getByRole('heading', { name: '构念与量表', exact: true })).toBeVisible()
  for (let i = 0; i < 3; i++) {
    if (i) await page.getByRole('button', { name: '添加构念', exact: true }).click()
    const card = page.locator('.construct-card').nth(i)
    await card.getByLabel(`构念 ${i + 1} 名称`).fill(['自主性', '投入', '绩效'][i])
    await card.getByLabel('理论最大值').fill('7')
    for (const name of names.slice(i * 3, i * 3 + 3)) await card.getByRole('checkbox', { name: `${name} ${name}`, exact: true }).check()
  }
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && /\/measurement$/.test(response.url()))
  await page.getByRole('button', { name: '保存规则并生成量表版本' }).click()
  const response = await saved
  expect(response.ok(), await response.text()).toBeTruthy()
  await expect(page.getByRole('heading', { name: '分析方法', exact: true })).toBeVisible()
}

for (const procedure of ['描述统计', '相关分析', '分层线性回归']) {
  test(`@real-r complete research journey: upload, measurement, ${procedure}, result and verified Excel export`, async ({ page }, testInfo) => {
    test.setTimeout(150_000)
    const failures = await installPageFailureMonitor(page)
    await importAndMeasure(page)
    const methodLabel = procedure === '相关分析'
      ? '相关与偏相关'
      : procedure === '分层线性回归'
        ? '线性 / 分层回归'
        : procedure
    await configureMethod(page, methodLabel)
    if (procedure === '分层线性回归') {
      await page.getByLabel('因变量（Y）').selectOption({ label: '绩效' })
      await page.getByRole('group', { name: '区块 2：预测变量' }).getByRole('checkbox', { name: '自主性', exact: true }).check()
      await page.getByRole('group', { name: '区块 2：预测变量' }).getByRole('checkbox', { name: '投入', exact: true }).check()
    } else {
      await page.getByRole('checkbox', { name: '自主性', exact: true }).check()
      await page.getByRole('checkbox', { name: '投入', exact: true }).check()
    }
    const accepted = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/empirical-analysis'))
    await page.getByRole('button', { name: `运行${procedure}`, exact: true }).click()
    const response = await accepted
    expect(response.status()).toBe(202)
    const job = await response.json() as { id: string; reportId: string; datasetId: string; measurementVersion: number }
    expect(job.measurementVersion).toBe(1)
    await expect(page.getByRole('heading', { name: `${procedure} · 本次结果`, exact: true })).toBeVisible({ timeout: 90_000 })
    const downloadEvent = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出论文表格 Excel', exact: true }).click()
    const download = await downloadEvent
    expect(await download.failure()).toBeNull()
    expect(download.suggestedFilename()).toContain(job.reportId)
    const exported = testInfo.outputPath('research-result.xlsx')
    await download.saveAs(exported)
    const contents = execFileSync(path.resolve('.venv/Scripts/python.exe'), ['-c',
      'import sys,json,openpyxl; w=openpyxl.load_workbook(sys.argv[1],data_only=True); print(json.dumps({"sheets":w.sheetnames,"cells":[str(c) for s in w for r in s.values for c in r if c is not None]},ensure_ascii=True))', exported], { encoding: 'utf8' })
    const workbook = JSON.parse(contents) as { sheets: string[]; cells: string[] }
    expect(workbook.sheets).toContain('方法与来源')
    expect(workbook.cells.join('\n')).toContain(job.reportId)
    expect(workbook.cells.join('\n')).toContain(job.datasetId)
    expect(workbook.cells.join('\n')).toContain('自主性')
    expect(workbook.cells.some(value => /^-?\d+\.\d+$/.test(value))).toBeTruthy()
    if (procedure === '描述统计') {
      await page.getByRole('tab', { name: '输出', exact: true }).click()
      await expect(page.getByRole('heading', { name: '输出', exact: true })).toBeVisible()
      await expectPrdBreakpointUsability(page, page.getByRole('checkbox', { name: '选择最新结果用于批量导出' }))
    }
    await failures.expectClean()
  })
}
