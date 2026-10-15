/* Standalone Chromium fixture validation. This never connects to Codex/CDP. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(__dirname, 'output');
fs.mkdirSync(output, {recursive:true});
const script = fs.readFileSync(path.join(root, 'userscript/usage-status.js'), 'utf8').replace('/*__PAIRING_CONFIG__*/null', JSON.stringify({endpoint:'http://127.0.0.1:48763',token:'synthetic-only-token'}));
const totals = {input:100000,cacheRead:60000,cacheWrite:0,output:10000,reasoning:4000,total:110000};
const base = {
 schemaVersion:'1',date:'2026-10-14',timezone:'Asia/Shanghai',generatedAt:'2026-10-14T02:00:00Z',lastSuccessfulScanAt:'2026-10-14T02:00:00Z',
 sourceScope:{homes:1},dataStatus:'complete',priceStatus:'complete',pricing:{verifiedAt:'2026-10-14',priceVersion:'synthetic-prices',tier:'Standard'},
 totals,totalCostUSD:'0.186',knownSubtotalUSD:'0.186',pricedTokens:110000,unpricedTokens:0,
 models:[{modelId:'gpt-6.1-sol',totals,pricingModelId:'gpt-6.1-sol',knownSubtotalUSD:'0.186',costUSD:'0.186',pricedTokens:110000,unpricedTokens:0,
  reasons:[],rateContexts:['short'],rates:{short:{uncachedInput:'2',cacheReadInput:'.1',cacheWriteInput:'2.5',output:'10'},long:{thresholdInputTokens:272000,rates:{uncachedInput:'4',cacheReadInput:'.2',cacheWriteInput:'5',output:'15'}}}}],internalModels:[],diagnostics:[]
};
async function main() {
 const browser = await chromium.launch({headless:true, channel:process.env.TEST_BROWSER_CHANNEL || 'msedge'});
 const results = [];
 try {
  for (const theme of ['light','dark']) for (const scale of [1,1.25,1.5]) {
   const context = await browser.newContext({viewport:{width:1000,height:800},deviceScaleFactor:scale,colorScheme:theme});
   const page = await context.newPage();
   await page.clock.install({time:new Date('2026-10-14T02:00:00Z')});
   let data=structuredClone(base),fail=false,calls=0;
   await page.route('http://127.0.0.1:48000/**', route => route.fulfill({contentType:'text/html; charset=utf-8',body:`<html data-theme="${theme}"><body style="margin:0"><header style="position:fixed;top:0;right:0;height:32px;display:flex"><button aria-label="Minimize" style="width:46px">—</button><button style="width:46px">□</button><button style="width:46px">×</button></header><aside style="width:240px;height:90vh"></aside><main>Standalone synthetic UI test</main></body></html>`}));
   await page.route('http://127.0.0.1:48763/**', route => {
    calls++; assert.equal(route.request().headers().authorization,'Bearer synthetic-only-token');
    return fail ? route.abort() : route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
   });
   await page.goto('http://127.0.0.1:48000/');
   await page.evaluate(() => {
    window.testCleanups=[];
    window.__codexPlusUserScripts={currentKey:'fixture',registerCleanup:fn=>window.testCleanups.push(fn)};
    window.testTimers=new Set();
    const set=window.setTimeout.bind(window),clear=window.clearTimeout.bind(window);
    window.setTimeout=(fn,ms,...rest)=> {let id=set(()=> {window.testTimers.delete(id);fn(...rest)},ms);window.testTimers.add(id);return id};
    window.clearTimeout=id=> {window.testTimers.delete(id);clear(id)};
    window.testListeners=new Map();
    for (const target of [window,document]) {
     const add=target.addEventListener.bind(target),remove=target.removeEventListener.bind(target);
     target.addEventListener=(type,fn,opts)=> {if(window.testTracking&&['pointerdown','keydown','resize','online','securitypolicyviolation'].includes(type))window.testListeners.set(fn,type);add(type,fn,opts)};
     target.removeEventListener=(type,fn,opts)=> {window.testListeners.delete(fn);remove(type,fn,opts)};
    }
   });
   await page.evaluate(`window.testTracking=true;${script};window.testTracking=false;`);
   await page.getByRole('button',{name:/今日 110.0K/}).waitFor();
   const dockBox=await page.locator('#codex-usage-status').boundingBox();
   const minimize=await page.getByRole('button',{name:'Minimize',exact:true}).boundingBox();
   assert.ok(dockBox.y>=0&&dockBox.y+dockBox.height<=33);
   assert.ok(Math.abs(minimize.x-(dockBox.x+dockBox.width)-8)<2);
   assert.equal(await page.locator('#codex-usage-status').evaluate(n=>n.parentElement.tagName),'BODY');
   const gripBox=await page.getByRole('button',{name:'移动用量入口',exact:true}).boundingBox();
   await page.mouse.move(gripBox.x+gripBox.width/2,gripBox.y+gripBox.height/2);
   await page.mouse.down();await page.mouse.move(gripBox.x-90,gripBox.y+gripBox.height/2,{steps:6});await page.mouse.up();
   const movedBox=await page.locator('#codex-usage-status').boundingBox();assert.ok(movedBox.x<dockBox.x-60);
   await page.getByRole('button',{name:'移动用量入口',exact:true}).dblclick();
   const resetBox=await page.locator('#codex-usage-status').boundingBox();assert.ok(Math.abs(resetBox.x-dockBox.x)<2);
   await page.getByRole('button',{name:/今日 110.0K/}).click();
   await page.getByRole('heading',{name:'今日用量'}).waitFor();
   assert.equal(await page.locator('#codex-usage-status').count(),1);
   assert.ok((await page.locator('#card').textContent()).includes('$0.19'));
   await page.locator('details.model summary').click();
   assert.ok((await page.locator('#card').textContent()).includes('60,000'));
   const box=await page.locator('#card').boundingBox();assert.ok(box.x>=0&&box.y>=0&&box.x+box.width<=1000&&box.y+box.height<=800);
   await page.screenshot({path:path.join(output,`development-${theme}-${scale}.png`)});
   await page.keyboard.press('Escape');assert.ok(await page.locator('#card').isHidden());
   await page.getByRole('button',{name:/今日 110.0K/}).focus();await page.keyboard.press('Enter');assert.ok(await page.locator('#card').isVisible());
   await page.locator('main').click({position:{x:10,y:5}});assert.ok(await page.locator('#card').isHidden());
   // Navigation cannot move the entry into a sidebar; removal is recovered once.
   await page.evaluate(()=>{document.querySelector('aside').remove();document.querySelector('#codex-usage-status').remove()});
   await page.clock.runFor(200);assert.equal(await page.locator('#codex-usage-status').count(),1);
   for (let n=0;n<10;n++) {
    await page.evaluate(()=> {for(const fn of window.testCleanups.splice(0).reverse())fn()});
    await page.evaluate(`window.testTracking=true;${script};window.testTracking=false;`);
    await page.getByRole('button',{name:/今日 110.0K/}).waitFor();
    const state=await page.evaluate(()=>({roots:document.querySelectorAll('#codex-usage-status').length,listeners:window.testListeners.size,timers:window.testTimers.size}));
    assert.equal(state.roots,1);assert.equal(state.listeners,5);assert.equal(state.timers,1);
   }
   data={...structuredClone(base),dataStatus:'indexing'};
   await page.getByRole('button',{name:/今日 110.0K/}).click();
   await page.getByRole('button',{name:/统计中/}).waitFor();
   assert.ok((await page.locator('#card').textContent()).includes('正在索引'));
   data={...structuredClone(base),priceStatus:'partial',totalCostUSD:null,unpricedTokens:200};
   await page.getByRole('button',{name:'刷新',exact:true}).click();
   await page.getByRole('button',{name:/部分 ≈/}).waitFor();
   assert.ok((await page.locator('#card').textContent()).includes('已定价部分估算'));
   fail=true;await page.getByRole('button',{name:'刷新',exact:true}).click();
   await page.getByRole('button',{name:/旧数据/}).waitFor();
   assert.ok((await page.locator('#card').textContent()).includes('旧数据'));
   fail=false;data={...structuredClone(base),totals:{input:0,cacheRead:0,cacheWrite:0,output:0,reasoning:0,total:0},models:[],totalCostUSD:'0',knownSubtotalUSD:'0'};
   await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText('今天暂无用量').waitFor();
   data={...structuredClone(base),priceStatus:'unavailable',totalCostUSD:null,knownSubtotalUSD:null,pricedTokens:0,unpricedTokens:110000};
   await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText(/暂无匹配价格/).waitFor();
   data={...structuredClone(base),diagnostics:[{code:'price_table_stale',count:1,message:'价格核验超过30天'}]};
   await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText(/价格表过旧或更新无效/).waitFor();
   await page.evaluate(()=>window.__codexUsageStatus.destroy());
   const end=await page.evaluate(()=>({roots:document.querySelectorAll('#codex-usage-status').length,listeners:window.testListeners.size,timers:window.testTimers.size}));
   assert.deepEqual(end,{roots:0,listeners:0,timers:0});
   const before=calls;await page.clock.runFor(60000);assert.equal(calls,before);
   results.push({theme,scale,status:'passed',hotReloads:10});await context.close();
  }
  const narrowContext=await browser.newContext({viewport:{width:320,height:600}});
  const narrow=await narrowContext.newPage();
  await narrow.clock.install({time:new Date('2026-10-14T02:00:00Z')});
  await narrow.route('http://127.0.0.1:48000/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<main>Standalone narrow fixture</main>'}));
  await narrow.route('http://127.0.0.1:48763/**',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(base)}));
  await narrow.goto('http://127.0.0.1:48000/');await narrow.evaluate(script);
  await narrow.getByRole('button',{name:/今日 110.0K/}).click();
  const narrowBox=await narrow.locator('#card').boundingBox();assert.ok(narrowBox.x>=0&&narrowBox.x+narrowBox.width<=320&&narrowBox.y>=0&&narrowBox.y+narrowBox.height<=600);
  const overflow=await narrow.locator('#card').evaluate(n=>n.scrollWidth>n.clientWidth);assert.equal(overflow,false);
  await narrow.screenshot({path:path.join(output,'development-narrow.png')});await narrowContext.close();
  // A real CSP denial in a synthetic page must not be mislabeled as a stopped collector.
  const blockedContext=await browser.newContext({viewport:{width:1000,height:800}});
  const blocked=await blockedContext.newPage();
  let blockedRequests=0;
  await blocked.route('http://127.0.0.1:48000/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta http-equiv="Content-Security-Policy" content="connect-src \'none\'"><main>Isolated CSP fixture</main>'}));
  await blocked.route('http://127.0.0.1:48763/**',route=>{blockedRequests++;return route.abort()});
  await blocked.goto('http://127.0.0.1:48000/');await blocked.evaluate(script);
  await blocked.getByRole('button',{name:/页面连接受限/}).click();
  await blocked.getByText(/connect-src 安全策略阻止/).waitFor();
  assert.equal(blockedRequests,0);
  await blocked.screenshot({path:path.join(output,'development-csp-blocked.png')});await blockedContext.close();
  // The supported bridge works under unchanged connect-src 'none', with no browser fetch/token.
  const bridgeContext=await browser.newContext({viewport:{width:1000,height:800}});
  const bridgePage=await bridgeContext.newPage();
  await bridgePage.clock.install({time:new Date('2026-10-14T02:00:00Z')});
  await bridgePage.route('http://127.0.0.1:48000/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta http-equiv="Content-Security-Policy" content="connect-src \'none\'"><main>Isolated public bridge fixture</main>'}));
  await bridgePage.goto('http://127.0.0.1:48000/');
  await bridgePage.evaluate(data=>{
   window.bridgeCalls=[];window.bridgeError=null;window.syntheticSummary=data;
   window.fetch=()=>{throw new Error('Bridge must not fetch in renderer')};
   window.codexPlus={call:async(route,options)=>{
    window.bridgeCalls.push({route,options});
    if(window.bridgeError)throw new Error(window.bridgeError);
    return window.syntheticSummary;
   }};
  },base);
  const bridgeScript=fs.readFileSync(path.join(__dirname,'../userscript/usage-status.js'),'utf8').replace('/*__PAIRING_CONFIG__*/null',JSON.stringify({transport:'bridge'}));
  await bridgePage.evaluate(bridgeScript);
  await bridgePage.getByRole('button',{name:/今日 110.0K/}).click();
  assert.deepEqual((await bridgePage.evaluate(()=>window.bridgeCalls))[0],{route:'/usage-status/today',options:{includeInternal:false,includeCLI:false,includeOther:false}});
  await bridgePage.evaluate(()=>{window.bridgeError='USAGE_AUTH_FAILED'});
  await bridgePage.getByRole('button',{name:'刷新',exact:true}).click();
  await bridgePage.getByText(/配对令牌或页面来源未通过校验/).waitFor();
  await bridgePage.evaluate(()=>window.__codexUsageStatus.destroy());
  await bridgePage.evaluate(()=>{window.bridgeError='USAGE_NOT_PAIRED'});
  await bridgePage.evaluate(bridgeScript);
  await bridgePage.getByRole('button',{name:/采集器未连接/}).click();
  await bridgePage.getByText(/宿主尚未启用本地用量桥接/).waitFor();
  await bridgeContext.close();
  const zoomContext=await browser.newContext({viewport:{width:1000,height:700}});
  const zoomPage=await zoomContext.newPage();
  await zoomPage.clock.install({time:new Date('2026-10-14T02:00:00Z')});
  await zoomPage.route('http://127.0.0.1:48000/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<html style="zoom:1.25"><body style="margin:0"><header style="position:fixed;top:0;right:0;display:flex;height:32px"><button aria-label="最小化" style="width:46px">—</button><button style="width:46px">□</button><button style="width:46px">×</button></header><main>CSS zoom fixture</main></body></html>'}));
  await zoomPage.route('http://127.0.0.1:48763/**',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(base)}));
  await zoomPage.goto('http://127.0.0.1:48000/');await zoomPage.evaluate(script);
  await zoomPage.getByRole('button',{name:/今日 110.0K/}).waitFor();
  const zoomDock=await zoomPage.locator('#codex-usage-status').boundingBox(),zoomMin=await zoomPage.getByRole('button',{name:'最小化',exact:true}).boundingBox();
  assert.ok(Math.abs(zoomMin.x-zoomDock.x-zoomDock.width-8)<2);
  await zoomPage.getByRole('button',{name:/今日 110.0K/}).click();
  const zoomCard=await zoomPage.locator('#card').boundingBox();assert.ok(zoomCard.x>=0&&zoomCard.x+zoomCard.width<=1000&&zoomCard.y>=zoomDock.y+zoomDock.height&&zoomCard.y+zoomCard.height<=700);
  await zoomPage.setViewportSize({width:800,height:600});
  const resizedDock=await zoomPage.locator('#codex-usage-status').boundingBox(),resizedMin=await zoomPage.getByRole('button',{name:'最小化',exact:true}).boundingBox();
  assert.ok(Math.abs(resizedMin.x-resizedDock.x-resizedDock.width-8)<2);
  await zoomPage.screenshot({path:path.join(output,'development-css-zoom.png')});await zoomContext.close();
  fs.writeFileSync(path.join(output,'ui-results.json'),JSON.stringify({environment:'Standalone Chromium / synthetic fixture; NOT Codex integration',results},null,2));
  console.log(JSON.stringify({status:'passed',configurations:results.length,hotReloads:results.length*10}));
 } finally {await browser.close();}
}
main().catch(error=> {console.error(error);process.exitCode=1});
