// 챗봇 화면 무작위 시험(11/13) — 관제탑을 가상 시연으로 켠 뒤(TOWER_SIM=1, 포트 8100) `node tools/chat_ui_fuzz.js 회차 시드`. Playwright 필요.
// 통합 화면(/showcase)의 휴대폰 틀·역 키오스크 틀에서 챗봇을 무작위로 조작하고, 조작마다 화면 규칙(키보드가 입력칸을 가리지 않음 등)을 검사한다
const { chromium } = require('playwright');
const ROUNDS = Number(process.argv[2] || 100), SEED0 = Number(process.argv[3] || 1);
const TA = 'textarea[aria-label="질문 입력"]';
const QS = ['gbeovhs dlfgdjqjfuTdjdy', 'flqqka ckwdkwnj', 'qhwhqoxjfl dlTdjdy?', 'gosemzmfla', 'djelfh rkdy', 'cnlth', 'wnxns anfrjs tlsrh', 'dkssud', '12345', 'ghkstod', 'qkaans tlrks', 'dlfgdjqjfls anfrjs ckwrl', 'rjawjd gbeovhs', 'Qkfrks flqqka', 'wlrkq', 'USB', 'dnlcl djelsi', 'tlsqnswmd vlfdygo?'];
function rng(seed) { let a = seed >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
(async () => {
  const b = await chromium.launch();
  const fails = [], counts = {};
  let steps = 0, sent = 0;
  for (let round = 0; round < ROUNDS; round++) {
    const R = rng(SEED0 * 1000 + round), pick = (xs) => xs[Math.floor(R() * xs.length)];
    const kiosk = round % 4 === 3;                 // 4번에 한 번은 역 키오스크 틀의 AI 안내
    const vw = pick([1918, 1600, 1366, 1280]), vh = kiosk ? pick([1078, 960, 900, 768, 720]) : pick([1078, 1000, 960, 900]);
    const ctx = await b.newContext({viewport: {width: vw, height: vh}}); const pg = await ctx.newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e).slice(0, 160)));
    const where = `r${round} ${kiosk ? '키오스크' : '휴대폰'} ${vw}x${vh}`;
    const fail = (rule, more) => { fails.push(`${where} · ${rule}${more ? ' · ' + more : ''}`); counts[rule] = (counts[rule] || 0) + 1; };
    try {
      await pg.goto(`http://127.0.0.1:8100/showcase?scene=${kiosk ? 'found' : 'lostweb'}&cam=demo`); await pg.waitForTimeout(1800);
      const outer = pg.frameLocator(kiosk ? '#fFound' : '#fLost');
      const app = kiosk ? outer : outer.frameLocator('#app');
      const kb = kiosk ? outer.locator('.vk').first() : outer.locator('#kbslot .vk');
      const screen = kiosk ? pg.locator('#fFound') : outer.locator('.screen');
      const box = async (loc) => { try { return await loc.boundingBox({timeout: 1200}); } catch (e) { return null; } };
      const kbOn = () => kb.evaluate(e => e.classList.contains('vk-on')).catch(() => false);
      const panelOpen = async () => (await app.locator('.panel').count()) > 0 && await app.locator('.panel').isVisible().catch(() => false);
      const msgs = () => app.locator('.panel .msg, .panel .bubble, .panel [data-role]').count().catch(() => 0);
      const open = async () => { if (await panelOpen()) return; const pill = app.locator('.pill'); if (await pill.isVisible().catch(() => false)) await pill.click(); else await app.locator(kiosk ? '#chatOpen, [data-chatbot-open], .launcher' : '[data-chatbot-open]').first().click(); await pg.waitForTimeout(700); };
      const check = async (act) => {
        steps++;
        if (errs.length) { fail('페이지 오류', errs.shift()); }
        const on = await kbOn(), po = await panelOpen();
        if (po) {
          const k = await box(kb), p = await box(app.locator('.panel')), i = await box(app.locator(TA)), s = await box(app.locator('.send')), sc = await box(screen);
          if (on && k && i && s && (i.y + i.height > k.y + 1 || s.y + s.height > k.y + 1)) fail('키보드가 입력칸·보내기를 가림', `${act} · 입력칸 아래 ${Math.round(i.y + i.height)} > 키보드 위 ${Math.round(k.y)}`);
          if (on && k && p && p.y + p.height > k.y + 1) fail('창이 키보드 밑으로 들어감', act);
          if (p && sc && (p.y < sc.y - 1 || p.x < sc.x - 1 || p.x + p.width > sc.x + sc.width + 1 || p.y + p.height > sc.y + sc.height + 1)) fail('창이 화면 밖으로 나감', act);
          if (i && sc && !(i.width > 60)) fail('입력칸이 너무 좁음', act);
        }
        if (!kiosk && !on) { const h = await outer.locator('#app').evaluate(e => [e.offsetHeight, e.parentElement.clientHeight]).catch(() => null); if (h && Math.abs(h[0] - (h[1] - 44)) > 2) fail('키보드가 닫혔는데 화면 높이가 안 돌아옴', `${act} · ${h}`); }
        const now = await pg.locator('#agNow').innerText().catch(() => ''), chatTab = await pg.locator('#agSeg button[data-g="chat"]').getAttribute('aria-pressed').catch(() => null);
        const g = await pg.evaluate(() => { const b = document.querySelector('#agSeg button.on, #agSeg button[aria-selected="true"], #agSeg button[aria-pressed="true"]'); return b ? b.dataset.g : ''; }).catch(() => '');
        if (g === 'chat' && /키오스크에서 물건을 접수하면/.test(now)) fail('챗봇 그림인데 관제탑 안내 문구', act);
        const log = await pg.locator('#agLog').innerText().catch(() => '');
        if (/proposal_check|path: \[|generation_status|routing: /.test(log)) fail('에이전트 기록에 내부용 글', act);
        if (/(^|\s)0ms/.test(log)) fail('에이전트 기록에 0ms', act);
      };
      await open(); await check('열기');
      const n = 6 + Math.floor(R() * 7);
      for (let st = 0; st < n; st++) {
        const act = pick(['input', 'input', 'type', 'type', 'send', 'send', 'enterkey', 'vkkey', 'chip', 'chip', 'size', 'min', 'close', 'body', 'tab', 'scene']);
        try {
          if (act !== 'close' && act !== 'scene') await open();
          if (act === 'input') { await app.locator(TA).click({timeout: 2500}); await pg.waitForTimeout(450); if (!(await kbOn())) fail('입력칸을 눌렀는데 키보드가 안 올라옴', `단계 ${st}`); }
          else if (act === 'type') { await app.locator(TA).click({timeout: 2500}); await pg.waitForTimeout(350); const before = await app.locator(TA).inputValue(); await pg.keyboard.type(pick(QS), {delay: 8}); await pg.waitForTimeout(200); const after = await app.locator(TA).inputValue(); if (after === before) fail('PC 키보드로 쳤는데 글자가 안 들어감', `단계 ${st}`); else if (/[ㄱ-ㅎㅏ-ㅣ]{2}/.test(after.slice(before.length))) fail('한글이 조합되지 않고 낱자로 들어감', JSON.stringify(after.slice(before.length))); }
          else if (act === 'send') { const v = await app.locator(TA).inputValue(); const m0 = await msgs(); await app.locator('.send').click({timeout: 2500}); await pg.waitForTimeout(v.trim() ? 2600 : 400); if (v.trim()) { sent++; if (await msgs() <= m0) fail('보냈는데 대화가 늘지 않음', v.slice(0, 12)); } }
          else if (act === 'enterkey') { await app.locator(TA).click({timeout: 2500}); await pg.waitForTimeout(350); await pg.keyboard.type(pick(QS), {delay: 8}); const m0 = await msgs(); await kb.locator('.vk-done').first().click({timeout: 2000}); await pg.waitForTimeout(2600); sent++; if (await msgs() <= m0) fail('화면 [↵]로 보냈는데 대화가 늘지 않음'); }
          else if (act === 'vkkey') { await app.locator(TA).click({timeout: 2500}); await pg.waitForTimeout(400); const keys = kb.locator('button'); const c = await keys.count(); const before = await app.locator(TA).inputValue(); if (c > 12) { await keys.nth(Math.floor(R() * 10)).click({timeout: 2000}); await pg.waitForTimeout(200); const after = await app.locator(TA).inputValue(); if (after === before) fail('화면 키를 눌렀는데 글자가 안 들어감'); } }
          else if (act === 'chip') { const chips = app.locator('.panel button:visible').filter({hasNotText: /^(보내기|✕|대화 지우기)$/}); const c = await chips.count(); const cand = []; for (let x = 0; x < c; x++) { const cl = await chips.nth(x).getAttribute('class') || ''; if (!/icon|send|grip/.test(cl)) cand.push(x); } if (cand.length) { await chips.nth(pick(cand)).click({timeout: 2500}).catch(() => {}); await pg.waitForTimeout(2200); } }
          else if (act === 'size') { await app.locator('.icon.size').click({timeout: 2500}); await pg.waitForTimeout(400); }
          else if (act === 'min') { await app.locator('.icon.min').click({timeout: 2500}); await pg.waitForTimeout(400); }
          else if (act === 'close') { if (await panelOpen()) { await app.locator('.icon.close').click({timeout: 2500}); await pg.waitForTimeout(400); if (await kbOn()) fail('창을 닫았는데 키보드가 남음'); } }
          else if (act === 'body') { const p = await box(app.locator('.panel')); if (p) { await pg.mouse.click(p.x + p.width / 2, p.y + Math.min(140, p.height / 2)); await pg.waitForTimeout(350); } }
          else if (act === 'tab') { await pg.locator('#agSeg button').nth(Math.floor(R() * 2)).click(); await pg.waitForTimeout(300); }
          else if (act === 'scene') { await pg.locator(`.scenes button[data-scene="${pick(['pickup', 'found', 'lost'])}"]`).click(); await pg.waitForTimeout(600); await pg.locator(`.scenes button[data-scene="${kiosk ? 'found' : 'lost'}"]`).click(); await pg.waitForTimeout(1200); }
        } catch (e) { fail('조작 실패', `${act} · ${String(e).split('\n')[0].slice(0, 110)}`); }
        await check(act);
      }
    } catch (e) { fail('회차 실패', String(e).split('\n')[0].slice(0, 140)); }
    await ctx.close();
  }
  await b.close();
  console.log(`회차 ${ROUNDS} · 조작 ${steps} · 보낸 질문 ${sent} · 어긋남 ${fails.length}`);
  console.log(JSON.stringify(counts, null, 1));
  console.log(fails.slice(0, 25).join('\n'));
})();
