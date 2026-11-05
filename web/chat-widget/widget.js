/* AI 분실물 챗봇 위젯 (LF-5, 11/5) — 화면에 한 줄로 붙인다:
 *   <script src="/chat-widget/widget.js" defer></script>
 * 열기: data-chatbot-open 속성이 있는 버튼을 누르거나, 그런 버튼이 없으면 오른쪽 아래 동그란 버튼이 자동으로 생긴다.
 * 스크립트 태그 옵션
 *   data-launcher="auto"(기본: 열기 버튼이 없을 때만 동그란 버튼) | "always" | "off"
 *   data-api="http://…"  챗봇 API 주소(기본: 이 스크립트를 내려준 서버 = 관제탑)
 *   data-title="AI 안내 도우미"
 * 코드에서: window.LostFoundChat.open() / close() / toggle()
 * 대화 내용은 이 화면에만 있고 저장하지 않는다(새로 고침하면 사라짐). 스타일은 Shadow DOM 안에 가둬 화면 디자인을 건드리지 않는다.
 */
(function () {
  "use strict";
  if (window.LostFoundChat) return; // 두 번 붙여도 하나만

  var script = document.currentScript || document.querySelector('script[src*="chat-widget/widget.js"]');
  var opt = function (name, fallback) {
    var v = script && script.getAttribute("data-" + name);
    return v == null || v === "" ? fallback : v;
  };
  var API = opt("api", script && script.src ? new URL(script.src, location.href).origin : location.origin).replace(/\/+$/, "");
  var TITLE = opt("title", "AI 안내 도우미");
  var LAUNCHER = opt("launcher", "auto");
  var MAX_LEN = 500, MAX_HISTORY = 4, MAX_MESSAGES = 40;

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:'Pretendard','Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',system-ui,sans-serif}",
    ".wrap{--bg:#ffffff;--fg:#1d2433;--muted:#5d6678;--line:#dfe3ea;--soft:#f3f5f9;--accent:#1f5eff;--accent-fg:#fff;--user:#1f5eff;--user-fg:#fff;--bot:#f1f3f7;--warn:#9a5b00;--warn-bg:#fff4e0;--err:#b42318;--shadow:0 18px 48px rgba(20,32,60,.22)}",
    "@media (prefers-color-scheme:dark){.wrap{--bg:#171b24;--fg:#e8ebf2;--muted:#a3abbb;--line:#2c3344;--soft:#202634;--accent:#6e95ff;--accent-fg:#0d1220;--user:#3d6cf0;--user-fg:#fff;--bot:#232a3a;--warn:#ffcf85;--warn-bg:#3a2c12;--err:#ff8a80;--shadow:0 18px 48px rgba(0,0,0,.5)}}",
    ".launcher{position:fixed;right:max(20px,env(safe-area-inset-right,0px));bottom:max(20px,env(safe-area-inset-bottom,0px));z-index:2147483000;width:60px;height:60px;border-radius:50%;border:0;background:var(--accent);color:var(--accent-fg);box-shadow:var(--shadow);cursor:pointer;display:grid;place-items:center;font-size:13px;font-weight:700;line-height:1.1}",
    ".launcher:focus-visible,button:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}",
    ".panel{position:fixed;right:max(20px,env(safe-area-inset-right,0px));bottom:max(92px,calc(env(safe-area-inset-bottom,0px) + 92px));z-index:2147483001;width:380px;max-width:calc(100vw - 32px);height:min(600px,calc(100vh - 120px));display:flex;flex-direction:column;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);overflow:hidden;font-size:15px;line-height:1.55}",
    ".panel[hidden],.launcher[hidden]{display:none}",
    "@media (max-width:480px){.wrap.open .launcher{display:none}.panel{right:0;left:0;bottom:0;width:100%;max-width:100%;height:min(88vh,640px);border-radius:18px 18px 0 0;padding-bottom:env(safe-area-inset-bottom,0px)}}",
    "header{display:flex;align-items:center;gap:10px;padding:14px 14px 12px 18px;border-bottom:1px solid var(--line)}",
    "header .dot{width:10px;height:10px;border-radius:50%;background:#22a06b;flex:none}",
    "header .dot.off{background:#c9ccd3}",
    "header h2{margin:0;font-size:16px;font-weight:700;flex:1;min-width:0}",
    "header .mode{display:block;font-size:12px;font-weight:500;color:var(--muted)}",
    ".icon{border:0;background:transparent;color:var(--muted);width:36px;height:36px;border-radius:10px;cursor:pointer;font-size:18px;flex:none}",
    ".icon:hover{background:var(--soft);color:var(--fg)}",
    ".log{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:12px;overscroll-behavior:contain}",
    ".welcome{background:var(--soft);border-radius:14px;padding:14px;font-size:14px;color:var(--fg)}",
    ".welcome p{margin:0 0 10px}",
    ".chips{display:flex;flex-direction:column;gap:6px}",
    ".chip{text-align:left;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:10px;padding:9px 12px;font-size:14px;cursor:pointer}",
    ".chip:hover{border-color:var(--accent)}",
    ".msg{display:flex;flex-direction:column;max-width:88%;gap:6px}",
    ".msg.user{align-self:flex-end;align-items:flex-end}",
    ".bubble{padding:10px 13px;border-radius:14px;white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere}",
    ".user .bubble{background:var(--user);color:var(--user-fg);border-bottom-right-radius:4px}",
    ".bot .bubble{background:var(--bot);color:var(--fg);border-bottom-left-radius:4px}",
    ".bot.pending .bubble{color:var(--muted)}",
    ".bot.error .bubble{color:var(--err)}",
    ".badges{display:flex;flex-wrap:wrap;gap:6px}",
    ".badge{font-size:12px;padding:2px 8px;border-radius:999px;background:var(--soft);color:var(--muted);border:1px solid var(--line)}",
    ".badge.warn{background:var(--warn-bg);color:var(--warn);border-color:transparent}",
    ".cards{display:grid;gap:6px;width:100%}",
    ".card{display:flex;justify-content:space-between;gap:8px;border:1px solid var(--line);border-radius:10px;padding:8px 11px;background:var(--bg);font-size:14px}",
    ".card span{color:var(--muted);font-size:13px}",
    "details{font-size:13px;color:var(--muted);width:100%}",
    "summary{cursor:pointer}",
    "details ul{margin:6px 0 0;padding-left:18px}",
    "details li{margin-bottom:6px}",
    "blockquote{margin:4px 0 0;padding-left:8px;border-left:3px solid var(--line);color:var(--muted)}",
    "a{color:var(--accent)}",
    ".retry{align-self:flex-start;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:8px;padding:5px 10px;font-size:13px;cursor:pointer}",
    "form{border-top:1px solid var(--line);padding:10px 12px 12px;display:flex;flex-direction:column;gap:6px}",
    ".row{display:flex;gap:8px;align-items:flex-end}",
    "textarea{flex:1;min-width:0;resize:none;border:1px solid var(--line);border-radius:12px;padding:10px 12px;font-size:15px;line-height:1.45;max-height:120px;background:var(--bg);color:var(--fg)}",
    ".send{border:0;border-radius:12px;background:var(--accent);color:var(--accent-fg);font-weight:700;padding:0 16px;height:44px;cursor:pointer;flex:none}",
    ".send:disabled{opacity:.5;cursor:default}",
    ".foot{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted)}",
    ".foot button{border:0;background:none;color:var(--muted);font-size:12px;cursor:pointer;padding:0;text-decoration:underline}",
    ".sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}"
  ].join("\n");

  var host, root, wrap, panel, launcher, log, form, input, sendBtn, countEl, modeEl, dotEl, statusEl;
  var busy = false, history = [], suggestions = [], lastFocus = null, loadedOnce = false;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function build() {
    host = document.createElement("div");
    host.id = "lostfound-chat-widget";
    root = host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = CSS;
    wrap = el("div", "wrap");

    launcher = el("button", "launcher", "AI\n챗봇");
    launcher.type = "button";
    launcher.style.whiteSpace = "pre-line";
    launcher.setAttribute("aria-label", TITLE + " 열기");
    launcher.hidden = true;
    launcher.addEventListener("click", function () { toggle(); });

    panel = el("section", "panel");
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "false");
    panel.setAttribute("aria-label", TITLE);

    var header = el("header");
    dotEl = el("span", "dot off");
    var h2 = el("h2", null, TITLE);
    modeEl = el("span", "mode", "연결 확인 중…");
    h2.appendChild(modeEl);
    var close = el("button", "icon", "✕");
    close.type = "button";
    close.setAttribute("aria-label", "챗봇 닫기");
    close.addEventListener("click", function () { closePanel(); });
    header.append(dotEl, h2, close);

    log = el("div", "log");
    log.setAttribute("role", "log");
    log.setAttribute("aria-live", "polite");

    form = el("form");
    var row = el("div", "row");
    input = el("textarea");
    input.rows = 1;
    input.maxLength = MAX_LEN;
    input.placeholder = "궁금한 점을 적어 주세요 (예: 검정 지갑 찾아줘)";
    input.setAttribute("aria-label", "질문 입력");
    sendBtn = el("button", "send", "보내기");
    sendBtn.type = "submit";
    row.append(input, sendBtn);
    var foot = el("div", "foot");
    statusEl = el("span", null, "후보는 본인 물건 확정이 아니에요");
    var right = el("span");
    countEl = el("span", null, "0/" + MAX_LEN);
    var clear = el("button", null, "대화 지우기");
    clear.type = "button";
    clear.style.marginLeft = "10px";
    clear.addEventListener("click", resetChat);
    right.append(countEl, clear);
    foot.append(statusEl, right);
    form.append(row, foot);

    panel.append(header, log, form);
    wrap.append(launcher, panel);
    root.append(style, wrap);
    document.body.appendChild(host);

    form.addEventListener("submit", function (e) { e.preventDefault(); send(input.value); });
    input.addEventListener("input", function () {
      countEl.textContent = input.value.length + "/" + MAX_LEN;
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });
    input.addEventListener("keydown", function (e) {
      if (e.isComposing || e.keyCode === 229) return; // 한글 조합 중 Enter 는 글자 확정용
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
    });
    panel.addEventListener("keydown", function (e) { if (e.key === "Escape") closePanel(); });
    showWelcome();
  }

  function showWelcome() {
    var box = el("div", "welcome");
    box.append(el("p", null, "안녕하세요. 분실물 찾는 방법, 본센터 방문, 필요한 준비물 같은 이용 안내를 도와드려요. 잃어버린 물건(품목·색)을 말씀하시면 보관 중인 후보도 찾아볼게요."));
    var chips = el("div", "chips");
    chips.setAttribute("data-chips", "");
    box.append(chips);
    log.append(box);
    renderChips();
  }

  function renderChips() {
    var chips = root.querySelector("[data-chips]");
    if (!chips) return;
    chips.replaceChildren();
    suggestions.slice(0, 3).forEach(function (s) {
      var b = el("button", "chip", s.text);
      b.type = "button";
      b.addEventListener("click", function () { send(s.text, s.id); });
      chips.append(b);
    });
  }

  function scroll() { log.scrollTop = log.scrollHeight; }

  function line(role, text) {
    var m = el("div", "msg " + role);
    m.append(el("div", "bubble", text));
    log.append(m);
    var msgs = log.querySelectorAll(".msg");
    if (msgs.length > MAX_MESSAGES) msgs[0].remove();
    scroll();
    return m;
  }

  function api(path, body) {
    var init = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
    return fetch(API + path, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var d = data && data.detail;
          var msg = typeof d === "string" ? d : r.status === 503 ? "챗봇이 아직 준비되지 않았어요. 잠시 뒤 다시 시도해 주세요." : "요청을 처리하지 못했어요.";
          throw new Error(msg);
        }
        return data;
      });
    }, function () { throw new Error("서버에 연결하지 못했어요. 인터넷 연결이나 관제탑 상태를 확인해 주세요."); });
  }

  function badgeText(res) {
    if (res.agent === "search" || res.agent === "both") return res.database_mode === "demo_sqlite" ? "가상 DB 시연" : "물건 검색 안내";
    if (res.generation_used) return "문서 검색 + AI 답변";
    if (res.status === "answered") return res.sources && res.sources.length ? "문서 근거 안내" : "대화 안내";
    if (res.status === "partial" || res.status === "policy_pending") return "확정 안내가 필요한 내용";
    return "질문을 조금 더 구체적으로";
  }

  function addExtras(m, res) {
    var badges = el("div", "badges");
    var b = el("span", "badge" + (res.status === "policy_pending" || res.status === "partial" ? " warn" : ""), badgeText(res));
    badges.append(b);
    if (res.context_used) badges.append(el("span", "badge", "앞선 질문을 이어서 이해했어요"));
    m.append(badges);

    var cands = res.candidates || [];
    if (cands.length) {
      var cards = el("div", "cards");
      cands.forEach(function (c) {
        var card = el("div", "card");
        var name = [c.color, c.category === "모형폰" ? "휴대폰(팀 분류: 모형폰)" : c.category].filter(Boolean).join(" ");
        card.append(el("strong", null, name), el("span", null, "후보 " + c.candidate_no));
        cards.append(card);
      });
      m.append(cards);
    }

    var sources = res.sources || [];
    if (sources.length) {
      var det = el("details");
      det.append(el("summary", null, "안내 근거 " + sources.length + "개 보기"));
      var ul = el("ul");
      sources.forEach(function (s) {
        var li = el("li");
        var url = null;
        try { url = new URL(s.url, location.href); } catch (e) { url = null; }
        if (url && url.protocol === "https:" && url.hostname === "github.com") {
          var a = el("a", null, s.title || url.href);
          a.href = url.href; a.target = "_blank"; a.rel = "noopener noreferrer";
          li.append(a);
        } else {
          li.append(el("strong", null, s.title || "프로젝트 문서"));
        }
        if (s.evidence) li.append(el("blockquote", null, s.evidence));
        ul.append(li);
      });
      det.append(ul);
      m.append(det);
    }
  }

  function setBusy(v) {
    busy = v;
    sendBtn.disabled = v;
    input.setAttribute("aria-busy", String(v));
  }

  function send(text, suggestionId) {
    var q = (text || "").trim();
    if (busy || !q) return;
    if (q.length > MAX_LEN) q = q.slice(0, MAX_LEN);
    var welcome = root.querySelector(".welcome");
    if (welcome) welcome.remove();
    line("user", q);
    input.value = "";
    input.dispatchEvent(new Event("input"));
    var pending = line("bot pending", "질문을 확인하고 있어요…");
    setBusy(true);
    statusEl.textContent = "답변 준비 중";
    var body = { question: q, history: history.slice(-MAX_HISTORY) };
    if (suggestionId) body.suggestion_id = suggestionId;
    api("/chat/questions", body).then(function (res) {
      history = history.concat([q]).slice(-MAX_HISTORY);
      pending.remove();
      var m = line("bot", res.answer || "답변을 만들지 못했어요. 질문을 조금 바꿔 다시 물어봐 주세요.");
      addExtras(m, res);
      statusEl.textContent = res.agent === "search" || res.agent === "both" ? "후보는 본인 물건 확정이 아니에요" : "안내 완료 · 근거를 펼쳐 볼 수 있어요";
      scroll();
    }, function (err) {
      pending.remove();
      var m = line("bot error", err.message);
      var retry = el("button", "retry", "다시 보내기");
      retry.type = "button";
      retry.addEventListener("click", function () { m.remove(); var u = log.querySelectorAll(".msg.user"); if (u.length) u[u.length - 1].remove(); send(q, suggestionId); });
      m.append(retry);
      statusEl.textContent = "전송하지 못했어요";
    }).then(function () { setBusy(false); input.focus(); });
  }

  function resetChat() {
    if (busy) return;
    history = [];
    log.replaceChildren();
    showWelcome();
    statusEl.textContent = "이 화면의 대화를 지웠어요";
    input.focus();
  }

  function loadStatus() {
    api("/chat/health").then(function (h) {
      if (!h.ready) { modeEl.textContent = "준비 중 — 관제탑 확인 필요"; dotEl.className = "dot off"; return; }
      dotEl.className = "dot";
      modeEl.textContent = h.search_mode === "demo_sqlite" ? "이용 안내 + 가상 물건 검색" : h.search_mode === "postgres" ? "이용 안내 + 본인인증 후 물건 검색" : "이용 안내";
      return api("/chat/suggestions").then(function (s) { suggestions = (s && s.items) || []; renderChips(); });
    }).catch(function () { modeEl.textContent = "연결 확인 필요"; dotEl.className = "dot off"; });
  }

  function openPanel() {
    if (!panel) build();
    if (!panel.hidden) return;
    lastFocus = document.activeElement;
    panel.hidden = false;
    wrap.classList.add("open"); // 휴대폰 폭에서는 창이 화면을 덮으므로 동그란 버튼을 숨긴다(창의 ✕ 로 닫음)
    launcher.setAttribute("aria-expanded", "true");
    if (!loadedOnce) { loadedOnce = true; loadStatus(); }
    setTimeout(function () { input.focus(); }, 0);
  }

  function closePanel() {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    wrap.classList.remove("open");
    launcher.setAttribute("aria-expanded", "false");
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
  }

  function toggle() { if (!panel || panel.hidden) openPanel(); else closePanel(); }

  function init() {
    build();
    var hasOpener = !!document.querySelector("[data-chatbot-open]");
    launcher.hidden = LAUNCHER === "off" || (LAUNCHER === "auto" && hasOpener);
    // 화면이 나중에 만든 버튼도 동작하도록 문서 전체에서 클릭을 받는다
    document.addEventListener("click", function (e) {
      var t = e.target && e.target.closest && e.target.closest("[data-chatbot-open]");
      if (t) { e.preventDefault(); toggle(); }
    });
  }

  window.LostFoundChat = { open: openPanel, close: closePanel, toggle: toggle };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
