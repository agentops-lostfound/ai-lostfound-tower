/* 화면 키보드(쿼티) — 키오스크 터치 입력 + 발표용 폰 키보드 (LF-2 · 11/10 변재원)
 *
 * 한줄 설명: 입력칸을 누르면 화면 아래에 키보드가 뜨고, 손가락(터치)이나 PC 키보드로 친 글자가 그 칸에 들어간다.
 *            PC 키보드로 칠 때는 화면 키보드의 같은 키가 손가락으로 누른 것처럼 눌려 보인다(발표용).
 *
 * - 한글 두벌식(자모를 글자로 조합) · 영문 · 숫자. 한/영 전환은 [한/영] 키, PC 의 한/영 키, 오른쪽 Alt
 * - 번호 칸(type=tel · data-vk="num")은 숫자 패드, 가린 신분증 칸(data-vk="id")은 숫자 + * + -
 * - data-vk="en" 영문으로 시작, data-vk-upper 대문자로 넣기, data-vk="off" 화면 키보드 안 씀
 * - 화면 키보드가 붙은 칸은 readonly 로 둔다 → 태블릿 자체 키보드·윈도우 한글 입력기가 끼어들지 않음
 * - 11/12 바로 고치기: 칸 안을 누른 자리(깜빡이는 막대)에 넣고 그 앞을 지운다. 끌어 고른 부분은 새 글자로 바뀜. PC ←·→·Home·End·Delete
 *   전화번호는 /ui/phonefield.js 가 [010]-[1111]-[1111] 세 칸으로 나눠, 칸을 누르면 그 칸 전체가 골라져 바로 다시 입력
 *
 * 쓰는 법
 *   <script src="/ui/vkeyboard.js?v=20261111b"></script>
 *   VK.attach(document, {skin: "kiosk"})                    // 키오스크: 이 화면의 입력칸 전부
 *   VK.attach(iframe.contentDocument, {skin: "phone", mount: 틀안의_자리})   // 발표용 폰 화면(/phone)
 */
(function () {
  "use strict";
  if (window.VK) return;

  // ── 한글 조합 ─────────────────────────────────────────────
  const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
  const JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ";
  const JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"];
  const V_COMB = { "ㅗㅏ": "ㅘ", "ㅗㅐ": "ㅙ", "ㅗㅣ": "ㅚ", "ㅜㅓ": "ㅝ", "ㅜㅔ": "ㅞ", "ㅜㅣ": "ㅟ", "ㅡㅣ": "ㅢ" };
  const J_COMB = { "ㄱㅅ": "ㄳ", "ㄴㅈ": "ㄵ", "ㄴㅎ": "ㄶ", "ㄹㄱ": "ㄺ", "ㄹㅁ": "ㄻ", "ㄹㅂ": "ㄼ", "ㄹㅅ": "ㄽ", "ㄹㅌ": "ㄾ", "ㄹㅍ": "ㄿ", "ㄹㅎ": "ㅀ", "ㅂㅅ": "ㅄ" };
  const split = (tbl) => Object.fromEntries(Object.entries(tbl).map(([k, v]) => [v, [k[0], k[1]]]));
  const V_SPLIT = split(V_COMB), J_SPLIT = split(J_COMB);
  const isVowel = (c) => JUNG.includes(c);
  const isCons = (c) => CHO.includes(c) || (JONG.includes(c) && c !== "");
  const syl = (c) => { const n = c.charCodeAt(0) - 0xac00; return n >= 0 && n < 11172 ? { cho: CHO[Math.floor(n / 588)], jung: JUNG[Math.floor((n % 588) / 28)], jong: JONG[n % 28] } : null; };
  const make = (cho, jung, jong) => String.fromCharCode(0xac00 + CHO.indexOf(cho) * 588 + JUNG.indexOf(jung) * 28 + JONG.indexOf(jong || ""));

  /** 조합 중인 끝 글자(last)에 자모 j 를 더한 결과 문자열(1~2글자) */
  function addJamo(last, j) {
    const s = last ? syl(last) : null;
    if (isCons(j)) {
      if (s && !s.jong && JONG.includes(j)) return make(s.cho, s.jung, j);              // 가 + ㄱ → 각
      if (s && s.jong && J_COMB[s.jong + j]) return make(s.cho, s.jung, J_COMB[s.jong + j]);   // 갈 + ㄱ → 갉
      return (last || "") + j;
    }
    if (s) {
      if (!s.jong && V_COMB[s.jung + j]) return make(s.cho, V_COMB[s.jung + j], "");    // 고 + ㅏ → 과
      if (s.jong) {                                                                   // 각 + ㅏ → 가가 / 갉 + ㅏ → 갈가
        const [keep, move] = J_SPLIT[s.jong] || ["", s.jong];
        if (CHO.includes(move)) return make(s.cho, s.jung, keep) + make(move, j, "");
      }
      return last + j;
    }
    if (last && CHO.includes(last)) return make(last, j, "");                          // ㄱ + ㅏ → 가
    if (last && isVowel(last) && V_COMB[last + j]) return V_COMB[last + j];
    return (last || "") + j;
  }

  /** 조합 중인 끝 글자를 한 단계 지우기(각 → 가 → ㄱ → 없음) */
  function backJamo(last) {
    const s = syl(last);
    if (!s) return V_SPLIT[last] ? V_SPLIT[last][0] : "";
    if (s.jong) return make(s.cho, s.jung, J_SPLIT[s.jong] ? J_SPLIT[s.jong][0] : "");
    if (V_SPLIT[s.jung]) return make(s.cho, V_SPLIT[s.jung][0], "");
    return s.cho;
  }

  // ── 자판 ────────────────────────────────────────────────
  const ROWS = [
    { codes: ["KeyQ", "KeyW", "KeyE", "KeyR", "KeyT", "KeyY", "KeyU", "KeyI", "KeyO", "KeyP"], en: "qwertyuiop", ko: "ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔ", koS: "ㅃㅉㄸㄲㅆㅛㅕㅑㅒㅖ" },
    { codes: ["KeyA", "KeyS", "KeyD", "KeyF", "KeyG", "KeyH", "KeyJ", "KeyK", "KeyL"], en: "asdfghjkl", ko: "ㅁㄴㅇㄹㅎㅗㅓㅏㅣ", koS: "ㅁㄴㅇㄹㅎㅗㅓㅏㅣ" },
    { codes: ["KeyZ", "KeyX", "KeyC", "KeyV", "KeyB", "KeyN", "KeyM"], en: "zxcvbnm", ko: "ㅋㅌㅊㅍㅠㅜㅡ", koS: "ㅋㅌㅊㅍㅠㅜㅡ" },
  ];
  const DIGITS = { codes: ["Digit1", "Digit2", "Digit3", "Digit4", "Digit5", "Digit6", "Digit7", "Digit8", "Digit9", "Digit0", "Minus"], ch: "1234567890-" };
  const SYM2 = "-/:;()@&\"'".split("");
  const SYM3 = ".,?!*#~".split("");
  const PHYS_SYM = { Period: ".", Comma: ",", Slash: "/", Minus: "-", Semicolon: ";", Quote: "'" };
  const PHYS_SHIFT = { Digit1: "!", Digit2: "@", Digit3: "#", Digit7: "&", Digit8: "*", Digit9: "(", Digit0: ")", Slash: "?", Semicolon: ":", Quote: "\"" };

  const CSS = `
.vk{position:fixed;left:0;right:0;bottom:0;z-index:2147483000;user-select:none;-webkit-user-select:none;touch-action:manipulation;
  font-family:var(--ui-font,Pretendard,"Malgun Gothic",system-ui,sans-serif);transform:translateY(105%);transition:transform .18s ease}
.vk.vk-on{transform:none}
.vk .vk-rows{display:flex;flex-direction:column;gap:var(--vk-gap)}
.vk .vk-row{display:flex;gap:var(--vk-gap);justify-content:center}
.vk button{all:unset;box-sizing:border-box;position:relative;display:flex;align-items:center;justify-content:center;flex:1 1 0;min-width:0;
  height:var(--vk-h);border-radius:var(--vk-r);background:var(--vk-key);color:var(--vk-fg);font-size:var(--vk-fs);font-weight:500;
  box-shadow:0 1px 0 var(--vk-shadow);cursor:pointer;transition:transform .06s,background .06s}
.vk button.vk-fn{background:var(--vk-fn);font-size:calc(var(--vk-fs)*.72);font-weight:600}
.vk button.vk-wide{flex-grow:1.6}.vk button.vk-space{flex-grow:5}.vk button.vk-done{background:var(--vk-accent);color:#fff}
.vk button.vk-down{transform:scale(.94);background:var(--vk-down)}
.vk button.vk-hit::after{content:"";position:absolute;width:44px;height:44px;border-radius:50%;background:var(--vk-touch);
  animation:vk-touch .32s ease-out forwards;pointer-events:none}
@keyframes vk-touch{from{transform:scale(.3);opacity:.9}to{transform:scale(1.4);opacity:0}}
.vk .vk-pop{position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);min-width:100%;padding:6px 10px;border-radius:10px;
  background:var(--vk-key);color:var(--vk-fg);font-size:calc(var(--vk-fs)*1.4);box-shadow:0 4px 14px rgba(0,0,0,.25);pointer-events:none}
.vk .vk-bar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:4px 12px;padding:0 4px;font-size:15px;color:var(--vk-sub)}
.vk .vk-bar b{color:var(--vk-fg)}
.vk-kiosk{--vk-h:62px;--vk-r:12px;--vk-gap:8px;--vk-fs:24px;--vk-key:var(--ui-surface,#fff);--vk-fn:var(--ui-fill-hover,#e8ebed);
  --vk-fg:var(--ui-text,#191f28);--vk-sub:var(--ui-text-3,#6b7684);--vk-accent:var(--ui-primary,#f06a00);--vk-down:var(--ui-primary-soft,#fff1e5);
  --vk-shadow:rgba(0,0,0,.18);--vk-touch:rgba(49,130,246,.35);background:var(--ui-fill,#f2f4f6);border-top:1px solid var(--ui-line,#e5e8eb);
  padding:12px max(12px,env(safe-area-inset-right,0px)) calc(12px + env(safe-area-inset-bottom,0px)) max(12px,env(safe-area-inset-left,0px));
  box-shadow:0 -6px 24px rgba(0,0,0,.18)}
.vk-kiosk .vk-rows{max-width:1100px;margin:0 auto}
.vk-kiosk.vk-pad .vk-rows{max-width:520px}
.vk-phone{position:absolute;--vk-h:42px;--vk-r:6px;--vk-gap:6px;--vk-fs:19px;--vk-key:#fff;--vk-fn:#abb0ba;--vk-fg:#000;--vk-sub:#5b6270;
  --vk-accent:#f06a00;--vk-down:#d0d4db;--vk-shadow:rgba(0,0,0,.35);--vk-touch:rgba(0,0,0,.18);background:#d1d4db;padding:8px 4px 26px}
.vk-phone .vk-row.vk-r2{padding:0 5%}
.vk-phone.vk-pad{--vk-h:48px}
@media (prefers-color-scheme:dark){.vk-phone{--vk-key:#6b6b6f;--vk-fn:#464649;--vk-fg:#fff;--vk-sub:#c7c7cc;--vk-down:#8a8a8f;background:#2b2b2e}}
.vk-target-on{outline:3px solid var(--ui-primary,#f06a00)!important;outline-offset:1px}
.vk-caret{position:absolute;width:2px;background:var(--ui-primary,#f06a00);pointer-events:none;z-index:2147482999;animation:vk-blink 1s steps(1) infinite}
@keyframes vk-blink{50%{opacity:0}}
`;

  // ── 키보드 하나(문서 하나에 붙음) ─────────────────────────
  function attach(doc, opt) {
    opt = Object.assign({ skin: "kiosk", mount: null }, opt || {});
    const host = opt.mount ? opt.mount.ownerDocument : doc;          // 키보드가 그려질 문서(폰 화면은 바깥 틀)
    if (!host.getElementById("vk-style")) {
      const st = host.createElement("style"); st.id = "vk-style"; st.textContent = CSS; host.head.appendChild(st);
    }
    if (doc !== host && !doc.getElementById("vk-style")) {            // 폰 화면: iframe 안 입력칸 테두리용
      const st = doc.createElement("style"); st.id = "vk-style"; st.textContent = ".vk-target-on{outline:3px solid #f06a00!important;outline-offset:1px}"; doc.head.appendChild(st);
    }
    const kb = host.createElement("div");
    kb.className = "vk vk-" + opt.skin;
    kb.setAttribute("role", "group"); kb.setAttribute("aria-label", "화면 키보드");
    (opt.mount || host.body).appendChild(kb);

    const st = { el: null, ko: true, shift: false, layer: "abc", comp: false, kind: "text", pos: 0 };
    // 11/12 바로 고치기: 예전에는 늘 끝에만 넣고 끝에서만 지웠다(01011111111 의 010 을 고치려면 다 지워야 했음) →
    //   칸을 누른 자리(커서)에 넣고 그 앞 글자를 지운다. readonly 칸은 브라우저가 커서를 그리지 않아 깜빡이는 막대를 직접 그린다
    const caret = doc.createElement("i"); caret.className = "vk-caret"; caret.hidden = true;
    if (!doc.getElementById("vk-caret-style")) {
      const cs = doc.createElement("style"); cs.id = "vk-caret-style";
      cs.textContent = ".vk-caret{position:absolute;width:2px;background:#f06a00;pointer-events:none;z-index:2147482999;animation:vk-blink 1s steps(1) infinite}@keyframes vk-blink{50%{opacity:0}}";
      doc.head.appendChild(cs);
    }
    doc.body.appendChild(caret);
    let measureCtx = null;
    const keyEls = {};                                               // 실제 키 코드 → 화면 키(PC 키보드 눌림 표시)

    function kindOf(el) {
      const d = (el.dataset && el.dataset.vk) || "";
      if (d === "id") return "id";
      if (d === "num" || el.type === "tel" || el.inputMode === "numeric" || el.inputMode === "tel") return "num";
      return "text";
    }
    function usable(el) {
      if (!el || !el.tagName) return false;
      if (el.dataset && el.dataset.vk === "off") return false;
      if (el.tagName === "TEXTAREA") return !el.disabled;
      if (el.tagName !== "INPUT" || el.disabled) return false;
      return ["text", "tel", "search", "", "number"].includes((el.getAttribute("type") || "").toLowerCase());
    }

    function btn(label, cls, onPress, code) {
      const b = host.createElement("button");
      b.tabIndex = -1;                                               // 11/12 화면 글쇠는 Tab 순서에 넣지 않음(손가락용)
      b.type = "button"; b.textContent = label; if (cls) b.className = cls;
      b.addEventListener("pointerdown", (e) => { e.preventDefault(); press(b, onPress, true); });
      b.addEventListener("mousedown", (e) => e.preventDefault());           // 입력칸 초점 유지
      if (code) (keyEls[code] = keyEls[code] || []).push(b);
      return b;
    }
    function row(cls) { const r = host.createElement("div"); r.className = "vk-row " + (cls || ""); return r; }

    function render() {
      kb.innerHTML = ""; for (const k in keyEls) delete keyEls[k];
      kb.classList.toggle("vk-pad", st.kind !== "text");
      const rows = host.createElement("div"); rows.className = "vk-rows";
      if (opt.skin === "kiosk") {                                   // 지금 입력 언어 안내(키보드 폭에 맞춤)
        const bar = host.createElement("div"); bar.className = "vk-bar";
        bar.innerHTML = `<span>${st.kind === "text" ? (st.ko ? "<b>한글</b> 입력 중 · 영문은 [한/영]" : "<b>영문</b> 입력 중 · 한글은 [한/영]") : "<b>숫자</b> 입력"}</span><span>PC 키보드로 쳐도 들어가요</span>`;
        rows.appendChild(bar);
      }
      if (st.kind !== "text") {                                     // 숫자 패드
        const keys = st.kind === "id" ? ["123", "456", "789", "*0-"] : ["123", "456", "789", "-0"];
        keys.forEach((line) => { const r = row(); [...line].forEach((c) => r.appendChild(btn(c, "", () => put(c), c === "-" ? "Minus" : c === "*" ? "Asterisk" : "Digit" + c))); rows.appendChild(r); });
        const r = row(); r.appendChild(btn("지우기", "vk-fn", back, "Backspace")); r.appendChild(btn("완료", "vk-fn vk-done", () => done(true), "Enter")); rows.appendChild(r);
        kb.appendChild(rows); return;
      }
      if (opt.skin === "kiosk") {                                   // 키오스크: 숫자 줄 늘 보임
        const r = row(); DIGITS.codes.forEach((code, i) => r.appendChild(btn(DIGITS.ch[i], "", () => put(DIGITS.ch[i]), code))); rows.appendChild(r);
      }
      if (st.layer === "sym") {                                      // 폰: 숫자·기호 층
        const r1 = row(); DIGITS.codes.slice(0, 10).forEach((code, i) => r1.appendChild(btn(DIGITS.ch[i], "", () => put(DIGITS.ch[i]), code))); rows.appendChild(r1);
        const r2 = row(); SYM2.forEach((c) => r2.appendChild(btn(c, "", () => put(c), symCode(c)))); rows.appendChild(r2);
        const r3 = row(); SYM3.forEach((c) => r3.appendChild(btn(c, "", () => put(c), symCode(c)))); r3.appendChild(btn("⌫", "vk-fn vk-wide", back, "Backspace")); rows.appendChild(r3);
      } else {
        ROWS.forEach((R, ri) => {
          const r = row("vk-r" + (ri + 1));
          if (ri === 2) r.appendChild(btn(st.shift ? "⬆" : "⇧", "vk-fn vk-wide", toggleShift, "ShiftLeft"));
          R.codes.forEach((code, i) => {
            const ch = st.ko ? (st.shift ? R.koS : R.ko)[i] : (st.shift ? R.en[i].toUpperCase() : R.en[i]);
            r.appendChild(btn(ch, "", () => put(ch, true), code));
          });
          if (ri === 2) r.appendChild(btn("⌫", "vk-fn vk-wide", back, "Backspace"));
          rows.appendChild(r);
        });
      }
      const r = row();
      if (opt.skin === "phone") r.appendChild(btn(st.layer === "sym" ? "가A" : "!#1", "vk-fn vk-wide", () => { st.layer = st.layer === "sym" ? "abc" : "sym"; render(); }));
      r.appendChild(btn(st.ko ? "한/영" : "영/한", "vk-fn vk-wide", toggleLang, "Lang1"));
      r.appendChild(btn(opt.skin === "phone" ? "" : "띄어쓰기", "vk-space", () => put(" "), "Space"));
      if (opt.skin === "kiosk") { r.appendChild(btn(".", "", () => put("."), "Period")); r.appendChild(btn(",", "", () => put(","), "Comma")); }
      else r.appendChild(btn(".", "", () => put("."), "Period"));
      r.appendChild(btn(opt.skin === "phone" ? "↵" : "완료", "vk-fn vk-done vk-wide", () => done(true), "Enter"));
      rows.appendChild(r);
      kb.appendChild(rows);
    }
    function symCode(c) { return Object.keys(PHYS_SYM).find((k) => PHYS_SYM[k] === c) || ("Sym" + c); }

    function press(b, fn, touch) {
      b.classList.add("vk-down"); if (touch) { b.classList.remove("vk-hit"); void b.offsetWidth; b.classList.add("vk-hit"); }
      if (opt.skin === "phone" && !b.classList.contains("vk-fn") && !b.classList.contains("vk-space") && b.textContent) {
        const p = host.createElement("span"); p.className = "vk-pop"; p.textContent = b.textContent; b.appendChild(p);
        setTimeout(() => p.remove(), 160);
      }
      setTimeout(() => b.classList.remove("vk-down"), 140);
      setTimeout(() => b.classList.remove("vk-hit"), 340);
      fn();
    }

    // ── 커서(넣을 자리) ──
    const KEEP = /[0-9A-Za-z가-힣ㄱ-ㅣ]/;                           // 칸이 값을 다시 꾸밀 때(전화번호 - 넣기) 셀 글자
    function sel() {
      const el = st.el, n = el.value.length;
      let a = typeof el.selectionStart === "number" ? el.selectionStart : n, b = typeof el.selectionEnd === "number" ? el.selectionEnd : n;
      a = Math.max(0, Math.min(a, n)); b = Math.max(a, Math.min(b, n));
      return [a, b];
    }
    function setCaret(pos) {
      const el = st.el; if (!el) return;
      st.pos = Math.max(0, Math.min(pos, el.value.length));
      try { el.setSelectionRange(st.pos, st.pos); } catch (_) {}
      drawCaret();
    }
    function drawCaret() {
      const el = st.el;
      if (!el || el.tagName !== "INPUT" || !el.isConnected) { caret.hidden = true; return; }
      const cs = (doc.defaultView || window).getComputedStyle(el);
      measureCtx = measureCtx || doc.createElement("canvas").getContext("2d");
      measureCtx.font = cs.font || `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const r = el.getBoundingClientRect(), view = doc.defaultView || window;
      const pl = parseFloat(cs.paddingLeft) || 0, bl = parseFloat(cs.borderLeftWidth) || 0;
      const full = measureCtx.measureText(el.value).width, inner = r.width - pl - (parseFloat(cs.paddingRight) || 0) - bl * 2;
      let x = measureCtx.measureText(el.value.slice(0, st.pos)).width;
      if (cs.textAlign === "center") x += Math.max(0, (inner - full) / 2);
      else if (cs.textAlign === "right" || cs.textAlign === "end") x += Math.max(0, inner - full);
      x -= el.scrollLeft || 0;
      const h = Math.min(r.height * 0.6, (parseFloat(cs.fontSize) || 20) * 1.25);
      caret.style.left = (r.left + view.scrollX + bl + pl + Math.max(0, Math.min(x, inner)) - 1) + "px";
      caret.style.top = (r.top + view.scrollY + (r.height - h) / 2) + "px";
      caret.style.height = h + "px";
      caret.hidden = false;
    }
    function setValue(v, pos) {
      const el = st.el; if (!el) return false;
      const max = el.maxLength > 0 ? el.maxLength : 0;
      if (max && v.length > max) return false;
      if (pos === undefined) pos = v.length;
      const want = KEEP.test(v) ? [...v.slice(0, pos)].filter((c) => KEEP.test(c)).length : pos;
      el.value = (el.dataset && "vkUpper" in el.dataset) ? v.toUpperCase() : v;
      el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
      const now = el.value;                                          // 칸이 값을 다시 꾸몄으면(010-1111-…) 같은 글자 뒤로
      if (now !== v && KEEP.test(now)) {
        let k = 0, i = 0;
        for (; i < now.length && k < want; i++) if (KEEP.test(now[i])) k++;
        pos = i;
      }
      if (st.el === el) setCaret(Math.min(pos, el.value.length));
      return true;
    }
    function put(ch, letter) {
      if (!st.el) return;
      const v = st.el.value, [a, b] = sel();
      const head = v.slice(0, a), tail = v.slice(b);
      if (letter && st.ko && /[ㄱ-ㅣ]/.test(ch)) {
        const comp = st.comp && a === b && a === st.pos;
        const last = comp ? head.slice(-1) : "";
        const mid = addJamo(last, ch), front = (comp ? head.slice(0, -1) : head) + mid;
        if (setValue(front + tail, front.length)) st.comp = true;
      } else if (setValue(head + ch + tail, a + ch.length)) st.comp = false;
      if (st.shift) { st.shift = false; render(); }
    }
    function back() {
      if (!st.el) return;
      const v = st.el.value, [a, b] = sel();
      if (a !== b) { setValue(v.slice(0, a) + v.slice(b), a); st.comp = false; return; }
      if (a === 0) { st.el.dispatchEvent(new CustomEvent("vk-back-empty", { bubbles: true })); return; }   // 맨 앞에서 지우기(전화번호 칸 → 앞 칸으로)
      const prev = v[a - 1];
      if (st.comp && a === st.pos && /[가-힣ㄱ-ㅣ]/.test(prev)) {
        const bj = backJamo(prev); setValue(v.slice(0, a - 1) + bj + v.slice(a), a - 1 + bj.length); st.comp = !!bj;
      } else {
        let cut = a - 1;
        if (!KEEP.test(prev) && cut > 0 && /\d/.test(v[cut - 1]) && st.kind === "num") cut--;   // 010-|1111 에서 지우면 - 와 0 을 함께
        setValue(v.slice(0, cut) + v.slice(a), cut); st.comp = false;
      }
    }
    function move(d) { if (!st.el) return; const [a, b] = sel(); st.comp = false; setCaret(d < 0 ? (a === b ? a - 1 : a) : (a === b ? b + 1 : b)); }
    function toggleShift() { st.shift = !st.shift; render(); }
    function toggleLang() { st.ko = !st.ko; st.comp = false; st.layer = "abc"; render(); }
    function done(fromTouch) {
      const el = st.el;
      if (el && fromTouch === true)                                  // 화면 [완료]/[↵]: 챗봇 보내기처럼 Enter 를 기다리는 칸도 동작하게
        el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, composed: true }));
      hide();
      if (el) { el.dispatchEvent(new Event("change", { bubbles: true })); el.blur(); }
    }

    function show(el) {
      // 11/13 이미 이 칸에 키보드가 올라와 있으면 그대로 둔다 — 같은 칸에 초점이 다시 오면(창 크기가 바뀔 때 등) 조합 중이던 한글이 끊겨 'ㅎㅐㄴ드크림'처럼 들어갔다
      if (st.el === el && kb.classList.contains("vk-on")) return;
      if (st.el && st.el !== el) st.el.classList.remove("vk-target-on");
      st.el = el; st.comp = false; st.shift = false; st.layer = "abc";
      st.kind = kindOf(el);
      st.ko = !(el.dataset && el.dataset.vk === "en");
      el.readOnly = true; el.setAttribute("inputmode", "none"); el.classList.add("vk-target-on");
      render(); kb.classList.add("vk-on");
      setTimeout(() => { if (st.el === el) { const [a, b] = sel(); st.pos = b; if (a === b) drawCaret(); else caret.hidden = true; } }, 0);
      if (!opt.mount) {                                             // 키오스크: 키보드에 칸이 가리지 않게
        // 11/12 교육원: 화면 전체(body)와 단계 카드(section) 둘 다에 키보드 높이만큼 여백을 넣어, 카드가 키보드 밑까지 길어지고
        //   [보내기]를 보이려 카드를 올리다 전화번호 칸이 카드 위로 잘렸다. 또 칸을 옮기면 '원래 여백' 기록이 늘어난 값으로 덮여
        //   키보드를 닫아도 카드 아래 흰 빈칸이 남았다 → body 만 띄우고, 그래도 카드가 키보드 밑으로 이어질 때만 그 넘친 만큼 카드에 여백
        restorePads();
        host.body.style.paddingBottom = kb.offsetHeight + "px";
        const box = scrollBox(el, true);
        if (box && box !== host.body && box !== host.documentElement) {
          const over = box.getBoundingClientRect().bottom - kbTop();
          if (over > 0) { box.dataset.vkPad = box.style.paddingBottom || "-"; box.style.paddingBottom = Math.ceil(over) + "px"; }
        }
        setTimeout(() => keepVisible(el), 50);
        notify(kb.offsetHeight);
      } else {                                                      // 폰 화면
        // 11/13 진짜 휴대폰처럼: 키보드가 올라오면 화면(틀 안 iframe) 높이를 그만큼 줄인다 — 전에는 페이지 아래에 여백만 넣어
        //   화면에 고정된 창(챗봇 창 등)이 키보드 밑에 깔려 입력칸·[보내기]가 가려졌다. 높이가 줄면 그 창이 스스로 키보드 위로 맞춰진다
        const win = doc.defaultView, fe = win && win.frameElement;
        if (fe && opt.mount !== host.body) {
          if (fe.dataset.vkFull == null) { fe.dataset.vkFull = String(fe.offsetHeight); fe.dataset.vkH = fe.style.height || "-"; }
          fe.style.height = Math.max(120, Number(fe.dataset.vkFull) - kb.offsetHeight) + "px";
        } else doc.body.style.paddingBottom = kb.offsetHeight + "px";
        setTimeout(() => {
          if (st.el !== el) return;
          if (!fe) { el.scrollIntoView({ block: "center", behavior: "smooth" }); return; }
          // 칸이 줄어든 화면 안에 다 보이면 그대로 둔다(고정된 창 안의 칸을 맞추려고 뒤 페이지를 움직이지 않게). 안 보일 때만 가운데로
          const r = el.getBoundingClientRect(), h = win.innerHeight;
          if (r.top >= 8 && r.bottom <= h - 8) return;
          win.scrollBy({ top: r.top + r.height / 2 - h / 2, behavior: "smooth" });
        }, 60);
      }
    }
    // 11/10 사람 조작 시뮬레이션: 본센터 키오스크에서 번호를 넣고 [물건 꺼내기]를 누르면 키보드가 단추를 덮고 있어
    // 첫 번째 누름이 키보드만 닫고 두 번째에야 눌렸다 → 칸 바로 뒤의 주 단추까지 키보드 위로 보이게 올린다
    function scrollBox(el, any) {                                  // any: 아직 넘치지 않아도 스크롤 가능한 상자(여백을 넣기 전)
      for (let n = el.parentElement; n; n = n.parentElement) {
        const cs = (n.ownerDocument.defaultView || window).getComputedStyle(n);
        if (/(auto|scroll)/.test(cs.overflowY) && (any || n.scrollHeight > n.clientHeight)) return n;
      }
      return null;
    }
    function kbTop() {                                              // 다 올라온 키보드의 위쪽(움직이는 중이어도)
      const view = doc.defaultView || window;
      return view.innerHeight - kb.offsetHeight;
    }
    function restorePads() {
      host.querySelectorAll("[data-vk-pad]").forEach((b) => { b.style.paddingBottom = b.dataset.vkPad === "-" ? "" : b.dataset.vkPad; delete b.dataset.vkPad; });
    }
    function nextAction(el) {
      const area = el.closest("form, section, [id]") || el.parentElement;
      const all = [...area.querySelectorAll("button")].filter((b) => b.offsetParent && !kb.contains(b));
      return all.find((b) => el.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) || null;
    }
    // 11/12: 보이는 칸 = 스크롤 상자(단계 카드) 안 ∩ 키보드 위. 칸은 늘 그 안에, 다음 단추까지 함께 들어가면 단추도
    function keepVisible(el) {
      if (st.el !== el) return;
      const view = (el.ownerDocument.defaultView || window);
      const box = scrollBox(el);
      const br = box ? box.getBoundingClientRect() : { top: 0, bottom: view.innerHeight };
      const top = Math.max(0, br.top) + 8, bottom = Math.min(br.bottom, kbTop()) - 8;
      if (bottom - top < 40) return;
      const r = el.getBoundingClientRect(), btn = nextAction(el);
      const b = btn && btn.getBoundingClientRect();
      let delta;
      if (b && b.bottom - r.top <= bottom - top) delta = Math.max(b.bottom - bottom, Math.min(0, r.top - top));   // 칸~단추가 다 들어감
      else delta = r.top + r.height / 2 - (top + bottom) / 2;                                                   // 칸만 가운데로
      if (r.top - delta < top) delta = r.top - top;                   // 칸 위가 잘리지 않게
      if (Math.abs(delta) < 1) return;
      if (box) box.scrollTop += delta; else view.scrollBy(0, delta);
    }
    // 11/13 화면에 고정된 창(챗봇 창)이 키보드 밑에 깔리지 않게: 키보드 높이를 알린다(창이 스스로 그 위로 맞춤 — web/chat-widget/widget.js)
    function notify(h) {
      try { const w = doc.defaultView; if (!w) return; w.__vkHeight = h; w.dispatchEvent(new w.CustomEvent("vk:resize", { detail: { height: h } })); } catch (_) { /* 알리지 못해도 키보드는 그대로 동작 */ }
    }
    function hide() {
      kb.classList.remove("vk-on"); caret.hidden = true;
      if (!opt.mount) notify(0);
      restorePads();
      if (st.el) st.el.classList.remove("vk-target-on");
      st.el = null; st.comp = false;
      host.body.style.paddingBottom = ""; if (doc !== host) doc.body.style.paddingBottom = "";
      const fe = doc.defaultView && doc.defaultView.frameElement;    // 11/13 폰 화면: 줄였던 화면 높이를 되돌림
      if (fe && fe.dataset.vkFull != null) { fe.style.height = fe.dataset.vkH === "-" ? "" : fe.dataset.vkH; delete fe.dataset.vkFull; delete fe.dataset.vkH; }
    }

    const target = (e) => (e.composedPath ? e.composedPath()[0] : e.target);
    // 11/12 Tab 으로 칸을 벗어나면(다른 단추로 초점) 키보드와 아래 여백을 닫는다 — 전에는 그대로 남아 화면 아래가 비어 보였다
    doc.addEventListener("focusin", (e) => { const el = target(e); if (usable(el)) show(el); else if (st.el && !kb.contains(el)) hide(); }, true);
    doc.addEventListener("pointerdown", (e) => {                    // 다른 곳을 누르면 닫기
      const el = target(e);
      // 11/13 바로 닫으면 화면 높이·챗봇 창이 그 순간 되돌아가며 누르던 단추([보내기])가 손가락 밑에서 움직여 눌림이 사라졌다
      //   → 그 누름(click)이 끝난 뒤에 닫는다. 0.7초 안에 click 이 없으면(끌기 등) 그냥 닫는다
      if (st.el && !usable(el) && !kb.contains(el)) {
        const was = st.el; let t = 0;
        const close = () => { doc.removeEventListener("click", close, true); clearTimeout(t); setTimeout(() => { if (st.el === was) hide(); }, 0); };
        doc.addEventListener("click", close, true); t = setTimeout(close, 700);
      }
      // 11/13 초점이 이미 그 칸에 있으면 focusin 이 다시 오지 않는다(답을 받은 뒤·다른 곳을 눌러 키보드만 닫힌 뒤) → 칸을 누르면 언제나 키보드를 올림
      else if (!st.el && usable(el) && !kb.contains(el)) show(el);
    }, true);
    // 11/12 칸 안을 누르면 그 자리로 커서(브라우저가 정한 선택을 읽음). 글자를 끌어 고르면 고른 부분을 바꿈
    const follow = (e) => { const el = target(e); if (st.el && el === st.el) setTimeout(() => { if (st.el !== el) return; const [a, b] = sel(); st.comp = false; st.pos = b; if (a === b) drawCaret(); else caret.hidden = true; }, 0); };
    doc.addEventListener("pointerup", follow, true);
    doc.addEventListener("select", follow, true);
    (doc.defaultView || window).addEventListener("resize", () => { if (st.el) drawCaret(); });
    doc.addEventListener("scroll", () => { if (st.el) drawCaret(); }, true);

    // 11/11 Ctrl+V 붙여넣기: 화면 키보드 칸은 readonly 라 브라우저가 붙여넣기를 막는다(Ctrl+C 는 됨) →
    // paste 사건에서 글자를 꺼내 칸 종류에 맞게 걸러 직접 넣는다. 찾기 번호처럼 복사해 온 값을 키오스크·폰 칸에 넣을 때
    doc.addEventListener("paste", (e) => {
      const el = target(e);
      if (!st.el || (el !== st.el && !st.el.contains(el))) return;
      let text = ((e.clipboardData || window.clipboardData) && (e.clipboardData || window.clipboardData).getData("text")) || "";
      text = text.replace(/[\r\n\t]+/g, " ").trim();
      if (st.kind === "num") text = text.replace(/[^0-9-]/g, "");
      else if (st.kind === "id") text = text.replace(/[^0-9*-]/g, "");
      e.preventDefault();
      if (!text) return;
      const el2 = st.el, max = el2.maxLength > 0 ? el2.maxLength : 0, [a, b] = sel(), v = el2.value;
      const room = max ? Math.max(0, max - (v.length - (b - a))) : text.length;
      st.comp = false; setValue(v.slice(0, a) + text.slice(0, room) + v.slice(b), a + Math.min(room, text.length));
    }, true);

    // PC 키보드 → 같은 화면 키를 눌러 보이며 입력
    // 11/12 Esc = 키보드 닫기(입력한 글자는 그대로). 화면 글쇠를 누른 뒤나 바깥 틀(통합 화면)에 초점이 있어도 닫히게
    //   칸이 든 문서·키보드가 그려진 문서·그 바깥 틀 문서(같은 주소일 때만) 모두에서 듣는다
    const onEsc = (e) => { if (e.key === "Escape" && st.el && e.isTrusted) { e.preventDefault(); e.stopPropagation(); done(); } };
    const escDocs = new Set([doc, host]);
    [doc, host].forEach((d) => { try { const w = d.defaultView; if (w && w.parent && w.parent !== w && w.parent.document) escDocs.add(w.parent.document); } catch (_) { /* 다른 주소 틀 */ } });
    escDocs.forEach((d) => d.addEventListener("keydown", onEsc, true));
    doc.addEventListener("keydown", (e) => {
      if (!e.isTrusted || !st.el || e.ctrlKey || e.metaKey || (e.altKey && e.code !== "AltRight")) return;
      if (target(e) !== st.el && !st.el.contains(target(e))) return;
      const code = e.code;
      const flash = (c) => (keyEls[c] || []).forEach((b) => press(b, () => {}, false));
      let handled = true;
      if (code === "Lang1" || e.key === "HangulMode" || code === "AltRight") { flash("Lang1"); toggleLang(); }
      else if (code === "Backspace") { flash("Backspace"); back(); }
      else if (code === "Enter" || code === "NumpadEnter") { flash("Enter"); done(); }
      else if (code === "Space") { flash("Space"); put(" "); }
      else if (code === "ArrowLeft" || code === "ArrowRight") move(code === "ArrowLeft" ? -1 : 1);
      else if (code === "Home" || code === "End") { st.comp = false; setCaret(code === "Home" ? 0 : st.el.value.length); }
      else if (code === "Delete") { const [a, b] = sel(), v = st.el.value; if (a < v.length || a !== b) { st.comp = false; setValue(v.slice(0, a) + v.slice(a === b ? a + 1 : b), a); } }
      else if (code === "ShiftLeft" || code === "ShiftRight" || code === "CapsLock" || code === "Tab" || code.startsWith("Arrow")) {
        handled = code !== "Tab";
      } else if (st.kind !== "text") {
        const c = (e.key === "*" || code === "NumpadMultiply") ? "*"                 // Shift+8 = * (숫자 8 보다 먼저)
          : e.shiftKey ? "" : /^Digit\d$|^Numpad\d$/.test(code) ? code.slice(-1) : (code === "Minus" || code === "NumpadSubtract") ? "-" : "";
        if (c && (c !== "*" || st.kind === "id")) { flash(c === "-" ? "Minus" : c === "*" ? "Asterisk" : "Digit" + c); put(c); }
      } else {
        const R = ROWS.find((r) => r.codes.includes(code));
        if (R) {
          if (st.layer === "sym") { st.layer = "abc"; render(); }
          const i = R.codes.indexOf(code), sh = e.shiftKey;
          const ch = st.ko ? (sh ? R.koS : R.ko)[i] : (sh ? R.en[i].toUpperCase() : R.en[i]);
          if (sh && !st.shift) { st.shift = true; render(); }
          flash(code); put(ch, true);
          if (st.shift) { st.shift = false; render(); }
        } else if (/^Digit\d$|^Numpad\d$/.test(code) && !e.shiftKey) {
          if (opt.skin === "phone" && st.layer !== "sym") { st.layer = "sym"; render(); }
          const d = code.slice(-1); flash("Digit" + d); put(d);
        } else {
          const c = e.shiftKey ? PHYS_SHIFT[code] : (PHYS_SYM[code] || (code === "NumpadDecimal" ? "." : ""));
          if (c) {
            if (opt.skin === "phone" && st.layer !== "sym" && c !== ".") { st.layer = "sym"; render(); }
            flash(symCode(c)); put(c);
          } else handled = false;
        }
      }
      if (handled) e.preventDefault();
    }, true);

    return { el: kb, hide, show: (el) => usable(el) && show(el), state: st, caret: () => st.pos };
  }

  window.VK = { attach, _hangul: { addJamo, backJamo } };
})();
