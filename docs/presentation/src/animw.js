// x-embed 를 iframe 으로 바꿔 시간대별로 찍기
const { chromium } = require('playwright'); const fs = require('fs');
(async () => {
  const [dir, out] = process.argv.slice(2); fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  const head = `<style>@font-face{font-family:'Noto Sans KR';src:local('Noto Sans CJK KR')}*{box-sizing:border-box;margin:0}body{margin:0}section{position:relative;width:1920px;height:1080px;overflow:hidden}aside{display:none}ul{padding-left:1.2em}</style>`;
  for (const [id, times] of JSON.parse(process.argv[4])) {
    let html = fs.readFileSync(dir + '/' + id + '.html', 'utf8');
    await p.setContent('<!doctype html><html><head>' + head + '</head><body>' + html + '</body></html>');
    await p.evaluate(() => { document.querySelectorAll('x-embed').forEach(e => { const f = document.createElement('iframe'); f.setAttribute('style', e.getAttribute('style') + ';border:0;background:transparent'); f.srcdoc = '<!doctype html><meta charset=utf-8><style>*{letter-spacing:.11em!important}</style>' + e.innerHTML; e.replaceWith(f); });
      document.querySelectorAll('x-connector').forEach(c => c.remove()); });
    let t0 = 0;
    for (const t of times) { await p.waitForTimeout((t - t0) * 1000); t0 = t; await p.screenshot({ path: `${out}/${id}_${t}s.png` }); }
  }
  await b.close();
})();
