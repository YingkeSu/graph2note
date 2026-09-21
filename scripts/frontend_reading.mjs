// Isolated browser fixtures; no upload, model calls, or persistent mutations.
import assert from 'node:assert/strict';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import {mkdir,writeFile} from 'node:fs/promises';
const [base='http://127.0.0.1:8796',out='.scratch/ui-polish-2026-09-16/reading-checks']=process.argv.slice(2);await mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
try {
for(const width of [1440,768,390]) {
 const page=await browser.newPage({viewport:{width,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/papers/ui-fixture/view',r=>r.fulfill({json:{document_id:'ui-fixture',doc_kind:'paper',meta:{title:'知识结构与研究笔记：论文阅读界面验证',authors:['界面验收示例'],year:2026,abstract:'此内容为界面验收数据，用于检查长文排版、章节导航和参考文献的可达性，不代表真实研究结论。',keywords:['阅读排版','知识结构']},sections:Array.from({length:8},(_,i)=>({level:1,title:`${i+1} ${['研究背景','阅读与标注','知识组织','材料分析'][i%4]}`,text:'这是用于长文阅读验收的示例段落。阅读界面需要让内容成为视觉中心，同时保持目录清晰、段落舒展，并能顺畅到达文末。'.repeat(7),page_start:i+1,page_end:i+1})),references:[{title:'界面验收参考条目',authors:['测试作者'],year:2026,raw:'用于检查参考文献区域的测试内容。'}]}}));
 await page.goto(`${base}/#paper/ui-fixture`,{waitUntil:'networkidle'});
 await page.screenshot({path:`${out}/${width}-paper.png`});
 const initial=await page.locator('#paper-zone').evaluate(e=>({client:e.clientHeight,scroll:e.scrollHeight,overflow:getComputedStyle(e).overflowY}));
 await page.locator('[data-paper-section="7"]').click();await page.waitForTimeout(1600);
 const nav=await page.locator('#paper-section-7').evaluate(e=>({y:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom}));
 await page.locator('#paper-zone').evaluate(e=>e.scrollTop=e.scrollHeight);await page.waitForTimeout(100);
 const reference=await page.locator('#paper-references-zone').evaluate(e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom}));
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 assert.equal(initial.overflow,'auto','Paper must own its scroll container');
 assert.ok(initial.scroll>initial.client && initial.client<900,'Long paper must have a bounded reading viewport');
 assert.ok(nav.y>=0 && nav.y<900,'Last chapter is reachable through the directory');
 assert.ok(reference.top>=0 && reference.bottom<=900,'Bibliography must be fully reachable');
 assert.equal(overflow,false);assert.deepEqual(errors,[]);
 await page.screenshot({path:`${out}/${width}-paper-end.png`});
 results.push({width,initial,nav,reference,errors,overflow});
 await page.close();
}
} finally { await browser.close(); }
await writeFile(`${out}/paper-check.json`,JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
