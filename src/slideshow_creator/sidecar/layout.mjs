export function textCollisions(rects) {
  const issues = [];
  for (let i=0;i<rects.length;i++) for (let j=i+1;j<rects.length;j++) {
    const a=rects[i],b=rects[j];
    const w=Math.min(a.right,b.right)-Math.max(a.left,b.left);
    const h=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
    const area=Math.min((a.right-a.left)*(a.bottom-a.top),(b.right-b.left)*(b.bottom-b.top));
    if (w>3 && h>3 && w*h>area*0.04) issues.push(`Overlapping diagram labels: ${a.text.slice(0,70)} / ${b.text.slice(0,70)}`);
  }
  return issues;
}

export async function inspectSvg(page, svg) {
  await page.setContent(svg);
  await page.evaluate(()=>document.fonts.ready);
  const rects=await page.evaluate(()=>[...document.querySelectorAll('svg text')].map(el=>{
    const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,text:el.textContent.trim()};
  }).filter(r=>r.text && r.right>r.left && r.bottom>r.top));
  return textCollisions(rects);
}
