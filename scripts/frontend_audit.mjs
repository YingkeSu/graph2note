/** Read-only route audit. Supply PLAYWRIGHT_MODULE when playwright is not locally installed.
 * node scripts/frontend_audit.mjs http://127.0.0.1:8794 .scratch/frontend-loop/evidence
 * Uses isolated browser context; never submits uploads, LLM calls or mutations.
 */
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base = 'http://127.0.0.1:8794', output = '.scratch/frontend-loop/evidence', mode = 'app'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
const results = [];
const routes = ['library','timeline/day','graph','dashboard','inbox','tags','ask','settings','vault-export','upload','repair'];
try {
  for (const width of [1440,768,390]) {
    const context = await browser.newContext({viewport:{width,height:900}});
    const page = await context.newPage();
    let errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    for (const route of routes) {
      errors=[];
      await page.goto(`${base}/#${route}`,{waitUntil:'networkidle',timeout:30000});
      await page.waitForTimeout(350);
      const metrics=await page.evaluate(()=>{
        const visible=e=>e.getClientRects().length>0;
        return {title:document.title, hash:location.hash,
          headings:[...document.querySelectorAll('main h2')].filter(visible).map(e=>e.textContent.trim()),
          overflow:document.documentElement.scrollWidth>innerWidth,
          clipped:[...document.querySelectorAll('header button,header input, main button,main input, main select')].filter(visible).filter(e=>{const r=e.getBoundingClientRect();return r.right>innerWidth+1||r.left<0}).slice(0,20).map(e=>({id:e.id,text:e.textContent.trim().slice(0,60)}))};
      });
      const filename=`${width}-${route.replaceAll('/','-')}.png`;
      await page.screenshot({path:resolve(output,filename),fullPage:true});
      results.push({route,width,...metrics,errors:[...errors],screenshot:filename});
    }
    await context.close();
  }
  for (const name of mode === '--prototypes' ? ['a-studio','b-reading','c-index'] : []) {
    const page=await browser.newPage({viewport:{width:1440,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(pathToFileURL(resolve('.scratch/frontend-loop/design-demos',`${name}.html`)).href);
    await page.screenshot({path:resolve(output,`${name}.png`)});
    await page.getByRole('button',{name:'今日新增',exact:true}).click();
    if(await page.getByRole('button',{name:'今日新增',exact:true}).getAttribute('aria-pressed')!=='true')throw Error('Filter state failed');
    await page.getByRole('button',{name:'上传手稿',exact:true}).click();
    if(!(await page.locator('#notice').innerText()).includes('初稿'))throw Error('Preview disclosure missing');
    await page.setViewportSize({width:390,height:900});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    await page.screenshot({path:resolve(output,`${name}-mobile.png`),fullPage:true});
    results.push({prototype:name,width:390,overflow,errors});
    await page.close();
  }
} finally {
  await writeFile(resolve(output,'audit.json'),JSON.stringify(results,null,2));
  await browser.close();
}
const findings=results.filter(r=>r.overflow||r.clipped?.length||r.errors.length);
console.log(JSON.stringify({checks:results.length,findings:findings.map(({route,prototype,width,overflow,clipped,errors})=>({route,prototype,width,overflow,clipped,errors}))},null,2));
process.exitCode=findings.length?1:0;
