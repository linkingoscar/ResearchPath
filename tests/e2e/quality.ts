import AxeBuilder from '@axe-core/playwright'
import { expect, type Locator, type Page } from '@playwright/test'

const RESIZE_OBSERVER_LOOP_ERROR = 'ResizeObserver loop completed with undelivered notifications.'
const RESIZE_OBSERVER_COUNTER = '__researchPathClassifiedResizeObserverLoopErrors'
const RESIZE_OBSERVER_EVENTS = '__researchPathClassifiedResizeObserverEvents'

interface PageFailureMonitorOptions {
  classifyModelCanvasResizeLoop?: boolean
}

export async function expectNoSeriousAccessibilityViolations(page: Page) {
  const scan = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  const blocking = scan.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  )
  expect(blocking).toEqual([])
}

export async function installPageFailureMonitor(
  page: Page,
  options: PageFailureMonitorOptions = {},
) {
  if (options.classifyModelCanvasResizeLoop) {
    await page.addInitScript(({ message, counter, eventsKey }) => {
      window.addEventListener('error', (event) => {
        const modelCanvasIsVisible = document.querySelector('.react-flow') !== null
        const isClassifiedBrowserNotification = event.message === message
          && modelCanvasIsVisible
        if (!isClassifiedBrowserNotification) return

        const state = window as typeof window & Record<string, unknown>
        state[counter] = Number(state[counter] ?? 0) + 1
        const events = Array.isArray(state[eventsKey]) ? state[eventsKey] : []
        state[eventsKey] = [...events, {
          timestamp: performance.now(),
          href: window.location.href,
          viewport: { width: window.innerWidth, height: window.innerHeight },
          source: { filename: event.filename, line: event.lineno, column: event.colno },
          userAgent: navigator.userAgent,
        }].slice(-20)
        // Resize Observer specifies this ErrorEvent when observations are
        // deferred to the next rendering loop. In this test only, React Flow's
        // model canvas may emit it while Chromium applies fitView or a viewport change.
        // Stop Vite's dev overlay from upgrading that classified browser
        // notification; every other page/console error remains fatal below.
        event.preventDefault()
        event.stopImmediatePropagation()
      }, { capture: true })
    }, {
      message: RESIZE_OBSERVER_LOOP_ERROR,
      counter: RESIZE_OBSERVER_COUNTER,
      eventsKey: RESIZE_OBSERVER_EVENTS,
    })
  }

  const runtimeErrors: string[] = []
  const consoleErrors: string[] = []
  const unexpectedHttpErrors: string[] = []
  const failedRequests: string[] = []
  const pendingStudyContextConflicts = new Map<string, number>()

  page.on('pageerror', error => runtimeErrors.push(error.message))
  page.on('console', message => {
    if (message.type() !== 'error') return
    // Chromium duplicates HTTP failures here without the request URL. The response
    // listener below owns HTTP classification so failures retain method and path.
    if (/^Failed to load resource: the server responded with a status of \d{3}/.test(message.text())) return
    consoleErrors.push(message.text())
  })
  page.on('response', response => {
    const status = response.status()
    const method = response.request().method()
    const url = new URL(response.url())
    const studyContextSave = method === 'PUT'
      && /^\/api\/v1\/projects\/[^/]+\/study-context$/.test(url.pathname)
    if (studyContextSave && status === 409) {
      pendingStudyContextConflicts.set(
        url.pathname,
        (pendingStudyContextConflicts.get(url.pathname) ?? 0) + 1,
      )
      return
    }
    if (studyContextSave && status >= 200 && status < 300) {
      const pending = pendingStudyContextConflicts.get(url.pathname) ?? 0
      if (pending === 1) pendingStudyContextConflicts.delete(url.pathname)
      if (pending > 1) pendingStudyContextConflicts.set(url.pathname, pending - 1)
    }
    if (status < 400) return
    const expectedColdStartNotFound = status === 404
      && method === 'GET'
      && url.pathname === '/api/v1/projects/default/study-context'
    if (!expectedColdStartNotFound) {
      unexpectedHttpErrors.push(`${status} ${method} ${url.pathname}`)
    }
  })
  page.on('requestfailed', request => {
    const pathname = new URL(request.url()).pathname
    const errorText = request.failure()?.errorText ?? 'unknown'
    const expectedCompletedProgressStreamClose = request.method() === 'GET'
      && /^\/api\/v1\/analyses\/[^/]+\/progress$/.test(pathname)
      && errorText === 'net::ERR_ABORTED'
    const expectedStaticNavigationAbort = request.method() === 'GET'
      && errorText === 'net::ERR_ABORTED'
      // Vite/Chromium can cancel an in-flight module while a route, reload, or
      // lazy boundary replaces it. A later module request must still succeed;
      // HTTP errors and aborted API calls remain fatal below.
      && /^\/(?:src|@vite|node_modules|assets)\//.test(pathname)
    if (!expectedCompletedProgressStreamClose && !expectedStaticNavigationAbort) {
      failedRequests.push(`${request.method()} ${pathname}: ${errorText}`)
    }
  })

  return {
    async expectClean() {
      // A finite count is renderer-speed dependent: hosted Chromium may emit one
      // notification for fitView and two for the viewport transition. Correctness
      // is quiescence after the final interaction, not a machine-specific total.
      const resizeObserverState = await page.evaluate(async ({ counter, eventsKey }) => {
        const state = window as typeof window & Record<string, unknown>
        let previousCount = Number(state[counter] ?? 0)
        let quietFrames = 0
        let observedFrames = 0
        while (observedFrames < 16 && quietFrames < 4) {
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
          const currentCount = Number(state[counter] ?? 0)
          quietFrames = currentCount === previousCount ? quietFrames + 1 : 0
          previousCount = currentCount
          observedFrames += 1
        }
        return {
          count: previousCount,
          quietFrames,
          observedFrames,
          events: Array.isArray(state[eventsKey]) ? state[eventsKey] : [],
        }
      }, { counter: RESIZE_OBSERVER_COUNTER, eventsKey: RESIZE_OBSERVER_EVENTS })
      const unrecoveredStudyContextConflicts = Array.from(
        pendingStudyContextConflicts.entries(),
        ([pathname, count]) => `409 PUT ${pathname} (${count} conflict${count === 1 ? '' : 's'} without a successful retry)`,
      )
      expect(runtimeErrors).toEqual([])
      expect(unexpectedHttpErrors).toEqual([])
      expect(unrecoveredStudyContextConflicts).toEqual([])
      expect(failedRequests).toEqual([])
      expect(consoleErrors).toEqual([])
      expect(
        resizeObserverState.quietFrames,
        `ResizeObserver notifications did not quiesce: ${JSON.stringify(resizeObserverState)}`,
      ).toBe(4)
    },
  }
}

export async function expectNoHorizontalOverflow(page: Page) {
  const overflowAudit = await page.evaluate(() => ({
    hasOverflow: document.documentElement.scrollWidth > window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    offenders: Array.from(document.querySelectorAll<HTMLElement>('body *'))
      .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 12)
      .map((element) => ({
        tag: element.tagName,
        className: element.className,
        right: Math.round(element.getBoundingClientRect().right),
        width: Math.round(element.getBoundingClientRect().width),
      })),
  }))
  expect(overflowAudit.hasOverflow, JSON.stringify(overflowAudit)).toBe(false)
}

export async function expectPrdBreakpointUsability(page: Page, primaryControl: Locator) {
  for (const width of [1024, 760, 420]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(primaryControl).toBeVisible()
    await primaryControl.focus()
    await expect(primaryControl).toBeFocused()
    await expectNoHorizontalOverflow(page)
    await expectNoSeriousAccessibilityViolations(page)
  }
}
