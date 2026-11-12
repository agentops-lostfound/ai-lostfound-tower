const { chromium } = require('playwright'); const fs = require('fs');
(async () => { const [dir, out, ...ids] = process.argv.slice(2); fs.mkdirSync(out,{recursive:true});
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  const head = `<style>@font-face{font-family:'Noto Sans KR';src:local('Noto Sans CJK KR')}*{box-sizing:border-box;margin:0}body{margin:0}section{position:relative;width:1920px;height:1080px;overflow:hidden}aside{display:none}</style>`;
  for (const id of ids) { await p.setContent('<!doctype html><html><head>'+head+'</head><body>'+fs.readFileSync(dir+'/'+id+'.html','utf8')+'</body></html>');
    await p.evaluate(() => document.querySelectorAll('x-embed').forEach(e => { const f=document.createElement('iframe'); f.setAttribute('style', e.getAttribute('style')+';border:0'); f.srcdoc='<!doctype html><meta charset=utf-8>'+e.innerHTML; e.replaceWith(f); }));
    await p.waitForTimeout(1200); await p.screenshot({ path: `${out}/${id}.png` }); }
  await b.close(); })();
