/** Regression of workspace navigation, graph controls and responsive layout.
 * Run against scripts/seed_u4_evidence.py's isolated fixture, never a real vault.
 * PLAYWRIGHT_MODULE can point to the installed Playwright entry.
 */
import assert from 'node:assert/strict';
import {mkdir, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base = 'http://127.0.0.1:8797', output = '.scratch/architecture-workspace-2026-09-16/evidence/interactions'] = process.argv.slice(2);
await mkdir(output, {recursive: true});
const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context = await browser.newContext({viewport: {width: 1440, height: 900}});
const page = await context.newPage();
page.setDefaultTimeout(10000);
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
await context.route('**/api/**', route => {
  if (['GET', 'HEAD'].includes(route.request().method())) return route.continue();
  return route.fulfill({status: 403, contentType: 'application/json', body: '{"detail":"Read-only fixture check"}'});
});
const selected = () => page.locator('[role="tab"][aria-selected="true"]');
const shot = name => page.screenshot({path: resolve(output, `${name}.png`), fullPage: true});
async function check(name, action) { await action(); checks.push(name); console.log(`PASS ${name}`); }
try {
  await page.goto(`${base}/#library`, {waitUntil: 'networkidle'});
  await check('route tabs reuse views and preserve filters', async () => {
    await page.locator('#nav-graph').click();
    await page.locator('#graph-canvas .graph-node').first().waitFor();
    await page.locator('#graph-source-chips [data-source="tag"]').click();
    await page.waitForFunction(() => location.hash.includes('src='));
    const filtered = new URL(page.url()).hash;
    await page.locator('#nav-review-group > summary').click();
    await page.locator('#nav-timeline').click();
    await page.locator('#timeline-zone:visible').waitFor();
    await page.getByRole('tab', {name: '知识图谱', exact: true}).click();
    await page.waitForFunction(hash => location.hash === hash, filtered);
    await page.locator('#graph-canvas .graph-node').first().waitFor();
    assert.equal(await page.getByRole('tab', {name: '知识图谱', exact: true}).count(), 1);
    assert.equal(await page.locator('#graph-source-chips [data-source="tag"]').getAttribute('aria-pressed'), 'false');
    await page.locator('#graph-clear-filters').click();
    await page.waitForFunction(() => document.querySelector('#graph-source-chips [data-source="tag"]')?.getAttribute('aria-pressed') === 'true');
    await page.locator('#nav-graph').click();
    await page.waitForFunction(() => location.hash.startsWith('#graph') && document.querySelector('[role="tab"][aria-selected="true"]')?.textContent === '知识图谱');
  });
  await check('arrow keys, active close, inactive close and browser history', async () => {
    await selected().focus();
    await page.keyboard.press('ArrowRight');
    await page.waitForFunction(() => location.hash === '#timeline/day' && document.querySelector('[role="tab"][aria-selected="true"]')?.textContent === '时间轴');
    assert.equal(await selected().innerText(), '时间轴');
    assert.equal(await selected().evaluate(e => e === document.activeElement), true);
    await page.keyboard.press('Delete');
    await page.waitForFunction(() => location.hash.startsWith('#graph') && document.querySelector('[role="tab"][aria-selected="true"]')?.textContent === '知识图谱');
    assert.equal(await page.getByRole('tab', {name: '时间轴', exact: true}).count(), 0);
    await page.getByRole('button', {name: '关闭 文档库', exact: true}).click();
    assert.equal(await page.getByRole('tab').count(), 1);
    await page.goBack();
    await page.locator('#timeline-zone:visible').waitFor();
    assert.equal(await selected().innerText(), '时间轴');
    await page.goForward();
    await page.locator('#graph-zone:visible').waitFor();
  });
  await check('document tab resolves title and returns to graph', async () => {
    await page.evaluate(() => { location.hash = '#doc/doc-00'; });
    await page.locator('#work-zone:visible').waitFor();
    await page.waitForFunction(() => {
      const title = document.querySelector('[role="tab"][aria-selected="true"]')?.textContent;
      return title && title !== '文档';
    });
    await page.getByRole('tab', {name: '知识图谱', exact: true}).click();
    await page.locator('#graph-zone:visible').waitFor();
    await page.locator('#graph-canvas .graph-node').first().waitFor();
    await shot('desktop-graph');
  });
  await check('filter panel collapses, persists and restores canvas space', async () => {
    const before = await page.locator('#graph-canvas').boundingBox();
    await page.locator('#graph-filter-toggle').click();
    assert.equal(await page.locator('#graph-filters').isVisible(), false);
    assert.equal(await page.locator('#graph-filter-toggle').getAttribute('aria-expanded'), 'false');
    const after = await page.locator('#graph-canvas').boundingBox();
    assert.ok(after.width > before.width + 200);
    await page.reload({waitUntil: 'networkidle'});
    assert.equal(await page.locator('#graph-filters').isVisible(), false);
    await page.locator('#graph-filter-toggle').click();
  });
  await check('filter clears document focus; empty graph clears previous state', async () => {
    await page.locator('#graph-clusters-toggle').click();
    await page.locator('#graph-canvas .graph-node-document').first().waitFor();
    await page.locator('#graph-canvas .graph-node-document').first().click();
    assert.ok(await page.evaluate(() => window.__g2nGraph.focusId));
    await page.locator('#graph-tag-chips button').first().click();
    await page.waitForFunction(() => location.hash.includes('tag=') && !window.__g2nGraph.focusId);
    await context.route('**/api/graph', route => route.fulfill({contentType: 'application/json', body: JSON.stringify({empty: true, counts: {nodes: 0, documents: 0, edges: 0}, nodes: [], edges: [], clusters: [], filters: {}})}));
    await page.reload({waitUntil: 'networkidle'});
    await page.locator('#graph-empty:visible').waitFor();
    assert.deepEqual(await page.evaluate(() => window.__g2nGraph.counts), {nodes: 0, edges: 0});
    assert.ok((await page.locator('#graph-status').innerText()).includes('0 条边'));
    await context.unroute('**/api/graph');
  });
  await check('390px and 768px layouts keep canvas and controls reachable', async () => {
    for (const width of [390, 768]) {
      await page.setViewportSize({width, height: 900});
      await page.evaluate(() => {localStorage.removeItem('graph2note.sidebar-collapsed'); localStorage.removeItem('graph2note.graph-filters-collapsed');});
      await page.goto(`${base}/#graph`, {waitUntil: 'networkidle'});
      await page.reload({waitUntil: 'networkidle'});
      assert.equal(await page.locator('#graph-filters').isVisible(), false);
      await page.locator('#graph-filter-toggle').click();
      assert.equal(await page.locator('#graph-filters').isVisible(), true);
      await page.locator('#graph-source-chips [data-source="tag"]').click();
      await page.waitForFunction(() => location.hash.includes('src='));
      await page.locator('#graph-canvas .graph-node').first().waitFor();
      await shot(`${width}-filters`);
      await page.locator('#graph-filter-toggle').click();
      assert.ok((await page.locator('#graph-canvas').boundingBox()).height > 250);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await shot(`${width}-graph`);
    }
  });
  assert.deepEqual(errors, []);
} catch (error) {
  console.error(await page.evaluate(() => ({hash: location.hash, tabs: [...document.querySelectorAll('[role="tab"]')].map(e => ({text: e.textContent, selected: e.getAttribute('aria-selected')})), focus: document.activeElement?.outerHTML})));
  throw error;
} finally {
  await writeFile(resolve(output, 'results.json'), JSON.stringify({checks, errors}, null, 2));
  await browser.close();
}
