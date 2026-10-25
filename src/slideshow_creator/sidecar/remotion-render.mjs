import {readFile, writeFile, mkdir, rm} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition, ensureBrowser} from '@remotion/renderer';

const chunks=[]; for await (const chunk of process.stdin) chunks.push(chunk);
const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
if (!Array.isArray(input.slides) || input.slides.length < 1 || input.slides.length > 40) throw new Error('Expected 1–40 slides');
const outputDir = input.outputDir;
await mkdir(join(outputDir,'assets'),{recursive:true});
const props = {slides:input.slides, theme:input.theme};
const serveUrl = await bundle({entryPoint:join(dirname(fileURLToPath(import.meta.url)),'composition.jsx'), onProgress:()=>{}});
const browserExecutable = process.env.REMOTION_BROWSER_EXECUTABLE || (await ensureBrowser()).path;
try {
  const composition = await selectComposition({serveUrl,id:'NotebookerSlideshow',inputProps:props,browserExecutable});
  await renderMedia({serveUrl,composition,inputProps:props,codec:'h264',outputLocation:join(outputDir,'slideshow.mp4'),browserExecutable,concurrency:2,crf:24});
  const frames=[];
  for (let i=0;i<input.slides.length;i++) {
    const filename=`assets/slide-${String(i+1).padStart(2,'0')}.png`;
    await renderStill({serveUrl,composition,inputProps:props,frame:i*180+30,output:join(outputDir,filename),browserExecutable,imageFormat:'png'});
    frames.push(filename);
  }
  // Visual QA inspects each rendered frame; enforce text density separately.
  const overflow=[];
  // Rendered stills are the canonical slides. Detect text budget violations as
  // well; visual QA inspects every rendered frame independently afterwards.
  input.slides.forEach((slide,i)=>{
    const words=[slide.title,slide.subtitle,slide.body,...(slide.bullets||[]),slide.caption].filter(Boolean).join(' ').split(/\s+/).length;
    if (words>85 || slide.title?.length>160 || (slide.bullets||[]).length>6) overflow.push(`Slide ${i+1} is too dense (${words} visible words)`);
  });
  const images=await Promise.all(frames.map(async p=>`data:image/png;base64,${(await readFile(join(outputDir,p))).toString('base64')}`));
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const html=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(input.title)}</title><style>body{margin:0;background:#102a23;color:#f4f8f6;font-family:Arial}main{max-width:1400px;margin:auto;padding:24px}video,img{width:100%;display:block}nav{display:flex;gap:12px;margin:20px 0}button{font:inherit;padding:10px 18px}figure{margin:0}figcaption{padding:12px}section[hidden]{display:none}</style><main><h1>${escape(input.title)}</h1><nav><button id="prev">Previous</button><button id="next">Next</button><span id="count"></span></nav>${images.map((image,i)=>`<section ${i?'hidden':''}><figure><img src="${image}" alt="${escape(input.slides[i].title)}"><figcaption>${escape(input.slides[i].notes||'')}</figcaption></figure></section>`).join('')}</main><script>let i=0;const slides=[...document.querySelectorAll('section')];function show(n){i=(n+slides.length)%slides.length;slides.forEach((s,j)=>s.hidden=j!==i);document.getElementById('count').textContent=(i+1)+' / '+slides.length}document.getElementById('prev').onclick=()=>show(i-1);document.getElementById('next').onclick=()=>show(i+1);document.onkeydown=e=>{if(e.key==='ArrowRight')show(i+1);if(e.key==='ArrowLeft')show(i-1)};show(0)</script></html>`;
  await writeFile(join(outputDir,'slideshow.html'),html);
  await writeFile(join(outputDir,'layout-review.json'),JSON.stringify({overflow,frames},null,2));
  process.stdout.write('\nNOTEBOOKER_RESULT:'+JSON.stringify({frames,overflow}));
} finally {
  await rm(serveUrl,{recursive:true,force:true});
}
