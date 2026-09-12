/** Browser regression scenarios for the paper reading room.
 * Requires seeded test library (scripts/seed_u4_evidence.py), Playwright, Chrome.
 * Model calls, upload and save responses are intercepted; no paid calls or writes.
 */
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const [base='http://127.0.0.1:8795',out='.scratch/frontend-loop/interactions']=process.argv.slice(2);
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context=await browser.newContext({viewport:{width:1440,height:900}});
const page=await context.newPage();
page.setDefaultTimeout(10000);
const errors=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
const json=(route,data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
await context.route('**/api/**',route=>{
  if(['GET','HEAD'].includes(route.request().method())||route.request().url().endsWith('/api/repair/scan'))return route.continue();
  return json(route,{detail:'Blocked non-fixture mutation'},403);
});
async function visit(route){await page.goto(`${base}/#${route}`,{waitUntil:'networkidle'});await page.reload({waitUntil:'networkidle'});}
async function shot(name){await page.screenshot({path:resolve(out,`${name}.png`),fullPage:true});}
async function check(name,fn){await fn();checks.push(name);console.log(`PASS ${name}`);}
try {
  await check('desktop navigation, filter state and density persist',async()=>{
    await visit('library');
    assert.equal(await page.locator('.doc-card:not(.doc-card-skeleton)').count(),43,'Use the isolated 43-document fixture');
    await page.getByRole('button',{name:'最近编辑',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.doc-card').length===12);
    assert.equal(await page.getByRole('button',{name:'最近编辑',exact:true}).getAttribute('aria-pressed'),'true');
    await page.getByRole('button',{name:'舒适',exact:true}).click();
    await page.reload({waitUntil:'networkidle'});
    assert.equal(await page.locator('#library-grid').getAttribute('data-density'),'comfortable');
    await page.getByRole('button',{name:'紧凑',exact:true}).click();
    await page.locator('#nav-timeline').click();
    // The hash assignment resolves before the queued hashchange render runs, so
    // wait for the view to appear (its hook runs first) before asserting nav state.
    await page.waitForFunction(()=>location.hash==='#timeline/day'
      &&!document.querySelector('#timeline-zone').classList.contains('hidden'));
    assert.equal(await page.locator('#nav-timeline').getAttribute('aria-current'),'page');
    await page.selectOption('#timeline-group','week');
    await page.waitForFunction(()=>location.hash==='#timeline/week');
  });
  await check('keyboard skip link preserves current route and primary hover stays readable',async()=>{
    await visit('tags');
    await page.reload({waitUntil:'networkidle'});
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('.skip-link').evaluate(e=>e===document.activeElement),true);
    await page.keyboard.press('Enter');
    assert.ok(page.url().endsWith('#tags'));
    assert.equal(await page.locator('#content').evaluate(e=>e===document.activeElement),true);
    await page.locator('#nav-upload').hover();
    const color=await page.locator('#nav-upload').evaluate(e=>getComputedStyle(e).color);
    assert.equal(color,'rgb(255, 255, 255)');
  });
  await check('mobile navigation can expand, switch views and collapse',async()=>{
    await page.setViewportSize({width:390,height:900});
    await page.evaluate(()=>localStorage.removeItem('graph2note.sidebar-collapsed'));
    await visit('library');
    assert.equal(await page.locator('#app-sidebar').isVisible(),false);
    await page.getByRole('button',{name:'展开侧栏',exact:true}).click();
    assert.equal(await page.locator('#app-sidebar').isVisible(),true);
    await page.locator('#nav-ask').click();
    await page.waitForFunction(()=>location.hash==='#ask');
    await page.getByRole('button',{name:'折叠侧栏',exact:true}).click();
    assert.equal(await page.locator('#app-sidebar').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await shot('mobile-ask');
  });
  await check('retryable failures recover on all seven data views',async()=>{
    const cases=[['library','**/api/documents'],['timeline/day','**/api/timeline?*'],['graph','**/api/graph'],['dashboard','**/api/stats'],['inbox','**/api/inbox'],['settings','**/api/llm/settings'],['tags','**/api/tags/groups']];
    for(const [view,pattern] of cases){
      const fail=route=>json(route,{detail:'测试：服务暂不可用'},503);
      await page.route(pattern,fail);
      await visit(view);
      await page.locator('.view-error:visible').waitFor();
      assert.ok((await page.locator('.view-error:visible').innerText()).includes('服务暂不可用'),view);
      if(view==='library')assert.equal(await page.locator('#library-empty').isVisible(),false);
      await shot(`error-${view.replaceAll('/','-')}`);
      await page.unroute(pattern,fail);
      await page.getByRole('button',{name:'重新加载',exact:true}).click();
      await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('.view-error:visible').count(),0,view);
    }
  });
  await check('graph zoom, filters, keyboard node access and label bounds',async()=>{
    await page.setViewportSize({width:1440,height:900});
    await visit('graph');
    await page.locator('#graph-canvas .graph-node').first().waitFor();
    const old=Number(await page.locator('#graph-canvas').getAttribute('data-zoom'));
    await page.locator('#graph-zoom-in').click();
    assert.ok(Number(await page.locator('#graph-canvas').getAttribute('data-zoom'))>old);
    await page.locator('#graph-fit').click();
    assert.equal(Number(await page.locator('#graph-canvas').getAttribute('data-zoom')),1);
    const source=page.locator('#graph-source-chips [data-source="tag"]');
    await source.click();await page.waitForFunction(()=>document.querySelector('#graph-source-chips [data-source="tag"]')?.getAttribute('aria-pressed')==='false');
    await page.locator('#graph-clear-filters').click();
    await page.waitForLoadState('networkidle');
    const bounds=await page.locator('#graph-canvas').evaluate(svg=>[...svg.querySelectorAll('g.graph-node')].map(n=>{
      const t=n.querySelector('text'),circle=[...n.querySelectorAll('circle')].at(-1);
      return t&&circle?{label:t.textContent,width:t.getBBox().width,diameter:2*Number(circle.getAttribute('r'))}:null;
    }).filter(Boolean));
    assert.ok(bounds.every(b=>b.width<=b.diameter+40),JSON.stringify(bounds));
    await shot('desktop-graph');
  });
  await check('editor panes, information panel and save feedback at two sizes',async()=>{
    let saved;
    await page.route('**/api/documents/doc-00/markdown',route=>{saved=route.request().postDataJSON();return json(route,{ok:true});});
    await visit('doc/doc-00');
    await page.locator('#md-editor').waitFor();
    await page.locator('#md-editor').fill('# 浏览器验收材料\n\n仅用于界面验证，不写入文档库。');
    await page.waitForFunction(()=>document.querySelector('#save-indicator').textContent.startsWith('已保存'));
    assert.ok(saved.markdown.includes('浏览器验收材料'));
    await shot('desktop-editor');
    await page.locator('#doc-panel-toggle').click();
    assert.equal(await page.locator('#doc-side-panel').isVisible(),true);
    await page.locator('#doc-panel-close').click();
    assert.equal(await page.locator('#doc-side-panel').isVisible(),false);
    await page.setViewportSize({width:390,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    const panes=await page.locator('.panes').evaluate(e=>({client:e.clientHeight,scroll:e.scrollHeight}));
    assert.ok(panes.client>100&&panes.scroll>panes.client,'Stacked panes must be scrollable');
    await shot('mobile-editor');
    await page.unroute('**/api/documents/doc-00/markdown');
  });
  await check('PDF upload status, failure details and document link (mocked transport)',async()=>{
    await page.route('**/api/pdf',route=>route.request().method()==='POST'?json(route,{pdf_id:'ui-fixture'}):route.fallback());
    await page.route('**/api/pdf/ui-fixture',route=>json(route,{filename:'界面验收.pdf',status:'done',total_pages:2,max_page_attempts:3,retryable:true,running:false,counts:{success:1,failed:1},pages:[{page_index:0,status:'success',document_id:'doc-00'},{page_index:1,status:'failed',error:'测试：识别服务暂不可用',attempts:1,retryable:true}]}));
    await visit('upload');
    await page.locator('#pdf-input').setInputFiles({name:'界面验收.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4 UI fixture')});
    await page.locator('#pdf-list .pdf-row').first().waitFor();
    assert.equal(await page.locator('#pdf-list .pdf-row').count(),2);
    assert.ok((await page.locator('#pdf-list').innerText()).includes('识别服务暂不可用'));
    assert.equal(await page.locator('#pdf-retry').isVisible(),true);
    await shot('mobile-pdf-status');
    await page.locator('#pdf-list a').first().click();
    await page.waitForFunction(()=>location.hash==='#doc/doc-00');
  });
  await check('Q&A waiting, error, retry and cited answer (mocked transport)',async()=>{
    let calls=0;
    await page.route('**/api/pdf/ask',async route=>{
      calls++;
      if(calls===1)return json(route,{detail:'测试：连接中断'},503);
      const request=route.request().postDataJSON();
      return json(route,{session_id:request.session_id,answer:'这是用于界面验收的回答。结论对应原文第一页。',status:'answered',retrieved:1,citations:[{document_id:'doc-00',pdf_name:'界面验收.pdf',page_number:1,page_index:0,source_page_url:'/api/documents/doc-00/source-page'}]});
    });
    await visit('ask');
    await page.locator('#pdf-qa-input').fill('这份材料的核心观点是什么？');
    await page.locator('#pdf-qa-form button').click();
    await page.locator('.ask-retry').waitFor();
    await page.locator('.ask-retry').click();
    await page.locator('.ask-citation').waitFor();
    assert.equal(calls,2);
    assert.ok((await page.locator('.ask-citation').innerText()).includes('p1'));
    await shot('mobile-ask-answer');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  });
  assert.deepEqual(errors,[]);
} finally {
  await writeFile(resolve(out,'results.json'),JSON.stringify({checks,errors},null,2));
  await browser.close();
}
