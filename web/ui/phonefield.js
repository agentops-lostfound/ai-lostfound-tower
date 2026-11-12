/* 전화번호 세 칸 입력 — [010]-[1111]-[1111] (LF-2 · 11/12 변재원)
 *
 * 한줄 설명: 전화번호 칸 하나를 세 칸으로 나눠, 틀린 칸을 누르면 그 칸이 통째로 골라져 바로 다시 칠 수 있게 한다.
 *
 * 왜: 11/12 발표 검토 — 01011111111 처럼 잘못 넣으면 화면 키보드는 끝에서만 지워져 앞의 010 을 고치려면 다 지워야 했다.
 * - 칸이 차면 다음 칸으로 넘어가고, 빈 칸 맨 앞에서 지우기를 누르면 앞 칸으로 돌아간다(/ui/vkeyboard.js 'vk-back-empty')
 * - 원래 입력칸은 숨겨 두고 값(010-1111-1111)을 계속 맞춰 넣는다 → 화면 코드는 예전처럼 원래 칸의 value 를 읽고 지우면 된다
 *
 * 쓰는 법: <input type="tel" id="cphone" data-phone> 다음에 <script src="/ui/phonefield.js?v=20261112a"></script>
 *          (나중에 만든 칸은 PhoneField.enhance(칸))
 */
(function () {
  "use strict";
  if (window.PhoneField) return;
  const SIZES = [3, 4, 4];
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  const digits = (s) => String(s || "").replace(/\D/g, "");

  function css(doc) {
    if (doc.getElementById("phf-style")) return;
    const st = doc.createElement("style"); st.id = "phf-style";
    st.textContent = ".phf{display:flex;align-items:center;gap:8px;width:100%;box-sizing:border-box}" +
      ".phf input{flex:4 1 0;min-width:0;text-align:center;letter-spacing:.06em;margin:0!important}.phf input:first-child{flex-grow:3}" +
      ".phf .phf-dash{flex:0 0 auto;font-size:1.4em;color:var(--ui-text-3,#8b95a1)}";
    doc.head.appendChild(st);
  }

  function enhance(orig) {
    if (!orig || orig.dataset.phfOn) return;
    orig.dataset.phfOn = "1";
    const doc = orig.ownerDocument;
    css(doc);
    const box = doc.createElement("div"); box.className = "phf"; box.setAttribute("role", "group");
    box.setAttribute("aria-label", orig.getAttribute("placeholder") || "전화번호");
    const segs = SIZES.map((n, i) => {
      const s = doc.createElement("input");
      s.type = "tel"; s.inputMode = "numeric"; s.maxLength = n; s.autocomplete = "off"; s.dataset.vk = "num";
      s.placeholder = i === 0 ? "010" : "0000"; s.setAttribute("aria-label", `전화번호 ${i + 1}번째 칸`);
      s.className = orig.className;
      return s;
    });
    segs.forEach((s, i) => { if (i) { const d = doc.createElement("span"); d.className = "phf-dash"; d.textContent = "-"; box.appendChild(d); } box.appendChild(s); });
    orig.insertAdjacentElement("afterend", box);
    orig.hidden = true; orig.tabIndex = -1; orig.dataset.vk = "off";

    const joined = () => segs.map((s) => desc.get.call(s)).filter(Boolean).join("-");
    const fill = (v) => {                                            // 원래 칸에 값을 넣으면(지우기 포함) 세 칸도 맞춤
      let d = digits(v);
      segs.forEach((s, i) => { desc.set.call(s, d.slice(0, SIZES[i])); d = d.slice(SIZES[i]); });
    };
    Object.defineProperty(orig, "value", {
      configurable: true,
      get() { return desc.get.call(orig); },
      set(v) {
        desc.set.call(orig, v);
        if (digits(v) !== segs.map((s) => desc.get.call(s)).join("")) fill(v);   // 화면 코드가 꾸미기만 했으면 칸은 그대로
      },
    });
    const sync = () => { desc.set.call(orig, joined()); orig.dispatchEvent(new Event("input", { bubbles: true })); };
    const selectAll = (s) => {
      const v0 = desc.get.call(s);                                 // 그 사이에 입력이 들어왔으면 고르지 않음(첫 글자가 바뀌지 않게)
      setTimeout(() => {
        if (desc.get.call(s) !== v0 || s.ownerDocument.activeElement !== s) return;
        try { s.setSelectionRange(0, v0.length); s.dispatchEvent(new Event("select", { bubbles: true })); } catch (_) {}
      }, 0);
    };
    let backing = null;                                            // 지우기로 앞 칸에 돌아온 칸은 통째로 고르지 않음

    segs.forEach((s, i) => {
      let fresh = false;
      s.addEventListener("focus", () => { if (backing === s) { backing = null; return; } fresh = true; selectAll(s); });
      s.addEventListener("pointerup", () => { if (fresh) selectAll(s); fresh = false; });   // 누른 칸은 통째로 골라 바로 다시 입력
      s.addEventListener("input", () => {
        const d = digits(desc.get.call(s)).slice(0, SIZES[i]);
        if (d !== desc.get.call(s)) desc.set.call(s, d);
        sync();
        if (d.length === SIZES[i] && segs[i + 1] && (s.selectionStart ?? d.length) >= d.length) {
          const nx = segs[i + 1]; nx.focus(); if (desc.get.call(nx)) selectAll(nx);
        }
      });
      s.addEventListener("vk-back-empty", () => {                   // 칸 맨 앞에서 지우기 → 앞 칸 끝으로
        if (!segs[i - 1]) return;
        const pv = segs[i - 1]; backing = pv; pv.focus();
        const n = desc.get.call(pv).length;
        try { pv.setSelectionRange(n, n); } catch (_) {}
        setTimeout(() => { try { pv.setSelectionRange(n, n); pv.dispatchEvent(new Event("select", { bubbles: true })); } catch (_) {} }, 0);
      });
      s.addEventListener("paste", (e) => {                           // 번호 통째로 붙여넣기 → 세 칸에 나눠 넣음
        const t = digits((e.clipboardData || window.clipboardData || { getData: () => "" }).getData("text"));
        if (t.length <= SIZES[i]) return;
        e.preventDefault(); e.stopImmediatePropagation();
        fill(t.slice(0, 11)); sync();
      }, true);
    });
    fill(desc.get.call(orig));
    return segs;
  }

  function scan(doc) { doc.querySelectorAll("input[data-phone]").forEach(enhance); }
  window.PhoneField = { enhance, scan };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => scan(document));
  else scan(document);
})();
