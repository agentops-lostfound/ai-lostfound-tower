// 모든 x-embed: 시간대별로 보이는 요소가 embed 영역 밖으로 나가는지 검사
const { chromium } = require('playwright'); const fs = require('fs');
(async () => {
  const dir = process.argv[2]; const ids = JSON.parse(fs.readFileSync(dir + '/../deck.json')).order;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  for (const id of ids) {
    const html = fs.readFileSync(dir + '/' + id + '.html', 'utf8');
    const embeds = [...html.matchAll(/<x-embed style="([^"]*)">([\s\S]*?)<\/x-embed>/g)];
    for (const [k, m] of embeds.entries()) {
      const w = +m[1].match(/width:(\d+)px/)[1], h = +m[1].match(/height:(\d+)px/)[1];
      await p.setViewportSize({ width: w, height: h });
      await p.setContent('<!doctype html><meta charset=utf-8>' + m[2]);
      const found = new Set();
      for (let t = 0; t < 18; t += 0.25) {
        const r = await p.evaluate(([t, w, h]) => {
          document.getAnimations().forEach(a => { a.pause(); a.currentTime = t * 1000; });
          const out = [];
          for (const el of document.body.querySelectorAll('*')) {
            if (el.tagName === 'svg' || el.closest('svg')) continue;
            let o = 1, e = el; while (e && e !== document.body) { o *= +getComputedStyle(e).opacity; e = e.parentElement; }
            if (o < 0.15) continue;
            const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
            const over = Math.max(-r.top, -r.left, r.bottom - h, r.right - w);
            if (over > 0.5) out.push((el.className || el.tagName) + ' ' + (el.textContent || '').slice(0, 12) + ' ' + Math.round(over) + 'px');
          }
          return out;
        }, [t, w, h]);
        r.forEach(x => found.add(x));
      }
      if (found.size) console.log(id, '#' + k, [...found].slice(0, 8).join(' | '));
    }
  }
  await b.close();
})();
