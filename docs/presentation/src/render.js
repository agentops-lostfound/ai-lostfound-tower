// 슬라이드 html 들을 1920x1080 으로 그려 png 로 저장 (확인용)
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
(async () => {
  const dir = process.argv[2], out = process.argv[3], ids = JSON.parse(fs.readFileSync(path.join(dir, '../deck.json'))).order;
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  const head = `<style>td,th{padding:inherit}@font-face{font-family:'Noto Sans KR';src:local('Noto Sans CJK KR');font-weight:100 900}
  @font-face{font-family:'JetBrains Mono';src:local('DejaVu Sans Mono')}
  *{box-sizing:border-box;margin:0} body{margin:0} section{position:relative;width:1920px;height:1080px;overflow:hidden}
  ul{padding-left:1.2em} aside{display:none} img:not([src]){display:block}
  x-connector,x-icon,x-shape{display:block}</style>`;
  const report = [];
  for (const [i, id] of ids.entries()) {
    const html = fs.readFileSync(path.join(dir, id + '.html'), 'utf8');
    await p.setContent('<!doctype html><html><head>' + head + '</head><body>' + html + '</body></html>');
    await p.evaluate(() => {
      document.querySelectorAll('x-connector').forEach(c => { const g=(k)=>parseFloat(c.getAttribute(k)); const x1=g('x1'),y1=g('y1'),x2=g('x2'),y2=g('y2'); const col=c.style.color||'#888'; const sv=document.createElementNS('http://www.w3.org/2000/svg','svg'); sv.setAttribute('style','position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none'); sv.innerHTML=`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${col}" stroke-width="${parseFloat(c.style.borderWidth)||2}" ${c.style.borderStyle==='dashed'?'stroke-dasharray="10 8"':''}/><circle cx="${x2}" cy="${y2}" r="6" fill="${col}"/>`; c.replaceWith(sv); });
      document.querySelectorAll('x-shape').forEach(c => { c.style.display='block'; c.style.clipPath='polygon(0 25%,60% 25%,60% 0,100% 50%,60% 100%,60% 75%,0 75%)'; });
      document.querySelectorAll('x-icon').forEach(c => { c.style.display='block'; c.style.background='currentColor'; c.style.clipPath='polygon(20% 10%,90% 50%,20% 90%)'; });
    }); await p.waitForTimeout(150);
    // 넘침 검사: 섹션 밖(920 아래 · 1792 오른쪽)으로 나간 글자 요소
    const bad = await p.evaluate(() => { const r = []; document.querySelectorAll('section h1,section h2,section h3,section p,section li,section td').forEach(e => { const b = e.getBoundingClientRect(); if (b.bottom > 1016 + 1 && !/bottom/.test(e.getAttribute('style')||'')) r.push('아래넘침 ' + Math.round(b.bottom) + ' ' + e.textContent.slice(0, 20)); if (b.right > 1800) r.push('오른쪽넘침 ' + Math.round(b.right) + ' ' + e.textContent.slice(0, 20)); if (e.scrollWidth > e.clientWidth + 2 && e.clientWidth) r.push('글자잘림 ' + e.textContent.slice(0, 20)); }); return r; });
    if (bad.length) report.push(id + ': ' + bad.join(' | '));
    await p.screenshot({ path: path.join(out, String(i + 1).padStart(2, '0') + '_' + id + '.png') });
  }
  console.log(report.join('\n') || '넘침 없음');
  await b.close();
})();
