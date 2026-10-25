import {chromium} from 'playwright';
import {ensureBrowser} from '@remotion/renderer';
import {readFile, mkdir} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const chunks=[]; for await (const chunk of process.stdin) chunks.push(chunk);
const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
const executablePath=process.env.REMOTION_BROWSER_EXECUTABLE || (await ensureBrowser()).path;
const browser=await chromium.launch({executablePath,headless:true,args:['--no-sandbox']});
const images=[], issues=[];
try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  // Generated HTML is untrusted. Do not let scripts call arbitrary network or
  // read arbitrary server files while taking a preview.
  await context.route('**/*',async route=>{
    const url=new URL(route.request().url());
    const allowedCdn=['cdn.jsdelivr.net','unpkg.com','fonts.googleapis.com','fonts.gstatic.com'];
    if (url.protocol==='data:' || (url.protocol==='file:' && resolve(decodeURIComponent(url.pathname)).startsWith(resolve(input.outputDir)+'/')) || (url.protocol==='https:' && allowedCdn.includes(url.hostname))) await route.continue();
    else await route.abort();
  });
  await mkdir(join(input.outputDir,'quality-previews'),{recursive:true});
  for (const [i,name] of input.files.entries()) {
    const path=resolve(input.outputDir,name);
    if (!path.startsWith(resolve(input.outputDir)+'/')) throw new Error('Unsafe inspection path');
    const page=await context.newPage();
    await page.goto(pathToFileURL(path).href,{waitUntil:'networkidle',timeout:30000});
    if(input.artifact && name==='quality-view.html') {
      await page.evaluate(payload=>window.postMessage(payload,'*'),input.artifact);
      await page.waitForTimeout(1500);
    }
    await page.evaluate(()=>document.fonts.ready);
    const layout=await page.evaluate(()=>({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}));
    if (layout.width>1442) issues.push(`${name} overflows horizontally`);
    if (layout.height>18000) {issues.push(`${name} exceeds visual inspection height`);await page.close();continue;}
    const filename=`quality-previews/page-${i+1}.png`;
    await page.screenshot({path:join(input.outputDir,filename),fullPage:true});
    images.push(filename);
    if (input.mobile) {
      await page.setViewportSize({width:390,height:844});
      const mobile=await page.evaluate(()=>({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight}));
      if (mobile.width>392) issues.push(`${name} overflows on mobile`);
      if(mobile.height<=18000){const filename=`quality-previews/page-${i+1}-mobile.png`;await page.screenshot({path:join(input.outputDir,filename),fullPage:true});images.push(filename);}
      else issues.push(`${name} exceeds mobile inspection height`);
    }
    await page.close();
  }
  process.stdout.write('\nNOTEBOOKER_RESULT:'+JSON.stringify({images,issues}));
} finally {await browser.close();}
