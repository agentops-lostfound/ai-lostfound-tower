/* AI 분실물 챗봇 위젯 (LF-5, 11/5) — 화면에 한 줄로 붙인다:
 *   <script src="/chat-widget/widget.js" defer></script>
 * 열기: data-chatbot-open 속성이 있는 버튼을 누르거나, 그런 버튼이 없으면 오른쪽 아래 동그란 버튼이 자동으로 생긴다.
 * 스크립트 태그 옵션
 *   data-launcher="auto"(기본: 열기 버튼이 없을 때만 동그란 버튼) | "always" | "off"
 *   data-spacer="off"     동그란 버튼이 보일 때 페이지 끝에 버튼만큼 빈 칸을 두는 것을 끔(기본: 둠)
 *   11/8 가림 줄이기: 넓은 화면(1024px 이상)은 오른쪽 옆 패널로 열고 body 오른쪽 여백으로 본문을 밀어냄(닫으면 원래 값으로),
 *   좁은 화면은 아래 시트 + 어두운 막(밖을 누르거나 Esc = 닫기). 동그란 버튼은 아래로 내리는 동안 잠깐 숨고, 휴대폰 폭에서는 아이콘만
 *   data-api="http://…"  챗봇 API 주소(기본: 이 스크립트를 내려준 서버 = 관제탑)
 *   data-title="AI 안내 도우미"
 *   data-mode="kiosk"     공용 키오스크용(11/6): 글자·버튼을 크게, 창을 닫으면 대화를 바로 지움
 *   data-mode="staff"     직원 관리자 화면용(11/6): 이용 안내 + "오늘 반환 실패 원인?" 같은 관제 질문(관리자 로그인 필요, LangManus 구조 분석 에이전트)
 *   data-idle-reset="90"  아무 조작이 없으면 N초 뒤 대화를 지우고 창을 닫음(다음 사람에게 앞사람 대화가 보이지 않게). kiosk 기본 90, 웹은 0(끔)
 * 코드에서: window.LostFoundChat.open() / close() / toggle()
 * 대화 내용은 이 화면에만 있고 저장하지 않는다(새로 고침하면 사라짐). 스타일은 Shadow DOM 안에 가둬 화면 디자인을 건드리지 않는다.
 * 11/8 디자인 개편: 색·글꼴은 공통 토큰(/ui/theme.css 의 --ui-*)을 따른다(없는 화면은 대체값). 화면이 라이트/다크를 바꾸면(html data-theme) 위젯도 같이 바뀐다.
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
  var STAFF = opt("mode", "web") === "staff";
  var TITLE = opt("title", STAFF ? "관제 도우미" : "AI 안내 도우미");
  var STAFF_CHIPS = [{ text: "오늘 반환 현황 요약해줘" }, { text: "최근 반환 실패 원인 알려줘" }, { text: "챗봇 처리 시간 분석해줘" }];
  var LAUNCHER = opt("launcher", "auto");
  var KIOSK = opt("mode", "web") === "kiosk";
  var IDLE_S = Math.max(0, Math.min(3600, parseInt(opt("idle-reset", KIOSK ? "90" : "0"), 10) || 0));
  var idleTimer = null;
  // 11/8 가림 줄이기: 넓은 화면(1024px 이상)에서는 오른쪽 옆 패널로 열고 본문을 그 폭만큼 밀어낸다
  var DOCK_QUERY = "(min-width:1024px)", DOCK_W = KIOSK ? 480 : 400;
  var SPACER = opt("spacer", "auto") !== "off";   // data-spacer="off" 면 페이지 끝 빈 칸을 만들지 않음
  var MAX_LEN = 500, MAX_HISTORY = 4, MAX_MESSAGES = 40, MAX_ANSWER = 300;
  // 11/7 대화 기억: 웹·관리자 화면은 같은 브라우저 탭을 닫기 전까지(sessionStorage) 대화를 기억한다. 서버에는 저장하지 않는다.
  // 키오스크는 여러 사람이 쓰므로 저장하지 않는다(기존처럼 창을 닫거나 조작이 없으면 지움)
  var STORE_KEY = "lf-chat:" + location.pathname;
  function storeGet() {
    if (KIOSK) return null;
    try { var v = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null"); return v && Array.isArray(v.history) && Array.isArray(v.msgs) ? v : null; } catch (e) { return null; }
  }
  // 11/7 Langfuse: 같은 화면 대화를 한 묶음(session)으로 보기 위한 무작위 번호. 개인정보 없음, "대화 지우기"를 누르면 새 번호
  var sessionId = null;
  function newSessionId() {
    var r = "";
    try { r = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()); } catch (e) { r = String(Math.random()).slice(2) + Date.now(); }
    return "s-" + r.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40);
  }
  function getSessionId() {
    if (sessionId) return sessionId;
    var saved = storeGet();
    sessionId = (saved && typeof saved.sid === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(saved.sid)) ? saved.sid : newSessionId();
    return sessionId;
  }
  function storeSet(v) {
    if (KIOSK) return;
    try { if (v) sessionStorage.setItem(STORE_KEY, JSON.stringify(v)); else sessionStorage.removeItem(STORE_KEY); } catch (e) { /* 저장 못 해도 대화는 계속 */ }
  }

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:var(--ui-font,'Pretendard Variable','Pretendard','Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',system-ui,sans-serif);letter-spacing:-.01em}",
    "/* 11/8 디자인 개편: 위젯 토큰은 공통 토큰(--ui-*)을 따른다. 공통 파일이 없는 화면은 괄호 안 대체값을 쓴다 */",
    ".wrap{color-scheme:light;--bg:var(--ui-surface,#ffffff);--fg:var(--ui-text,#191f28);--muted:var(--ui-text-2,#4e5968);--faint:var(--ui-text-3,#8b95a1);--line:var(--ui-line,#e5e8eb);--soft:var(--ui-fill,#f2f4f6);--soft-hover:var(--ui-fill-hover,#e8ebed);--accent:var(--ui-primary,#3182f6);--accent-hover:var(--ui-primary-hover,#1b64da);--accent-soft:var(--ui-primary-soft,#e8f3ff);--accent-fg:var(--ui-on-primary,#ffffff);--user:var(--ui-primary,#3182f6);--user-fg:var(--ui-on-primary,#ffffff);--bot:var(--ui-fill,#f2f4f6);--ok:var(--ui-ok,#03b26c);--warn:var(--ui-warn,#e58a00);--warn-bg:var(--ui-warn-soft,#fff4e0);--err:var(--ui-err,#f04452);--ring:0 0 0 0 transparent;--shadow:0 16px 48px rgba(0,0,0,.12),0 2px 8px rgba(0,0,0,.06)}",
    "/* 다크: 화면이 data-theme=dark 를 고른 경우 + data-theme 없이 OS 가 다크인 경우(.wrap[data-theme] 는 화면의 html 값을 그대로 옮긴 것) */",
    "@media (prefers-color-scheme:dark){.wrap:not([data-theme=light]){color-scheme:dark;--bg:var(--ui-surface,#1c1c21);--fg:var(--ui-text,#f2f3f5);--muted:var(--ui-text-2,#b0b4bc);--faint:var(--ui-text-3,#7e838c);--line:var(--ui-line,#2e2e36);--soft:var(--ui-fill,#2a2a32);--soft-hover:var(--ui-fill-hover,#33333c);--accent:var(--ui-primary,#4593fc);--accent-hover:var(--ui-primary-hover,#6aa8fd);--accent-soft:var(--ui-primary-soft,#1b2a40);--accent-fg:var(--ui-on-primary,#ffffff);--user:var(--ui-primary,#4593fc);--user-fg:var(--ui-on-primary,#ffffff);--bot:var(--ui-fill,#2a2a32);--ok:var(--ui-ok,#20c47f);--warn:var(--ui-warn,#f0a33a);--warn-bg:var(--ui-warn-soft,#362a14);--err:var(--ui-err,#ff5f6d);--ring:0 0 0 1px rgba(255,255,255,.07);--shadow:0 16px 48px rgba(0,0,0,.55)}}",
    ".wrap[data-theme=dark]{color-scheme:dark;--bg:var(--ui-surface,#1c1c21);--fg:var(--ui-text,#f2f3f5);--muted:var(--ui-text-2,#b0b4bc);--faint:var(--ui-text-3,#7e838c);--line:var(--ui-line,#2e2e36);--soft:var(--ui-fill,#2a2a32);--soft-hover:var(--ui-fill-hover,#33333c);--accent:var(--ui-primary,#4593fc);--accent-hover:var(--ui-primary-hover,#6aa8fd);--accent-soft:var(--ui-primary-soft,#1b2a40);--accent-fg:var(--ui-on-primary,#ffffff);--user:var(--ui-primary,#4593fc);--user-fg:var(--ui-on-primary,#ffffff);--bot:var(--ui-fill,#2a2a32);--ok:var(--ui-ok,#20c47f);--warn:var(--ui-warn,#f0a33a);--warn-bg:var(--ui-warn-soft,#362a14);--err:var(--ui-err,#ff5f6d);--ring:0 0 0 1px rgba(255,255,255,.07);--shadow:0 16px 48px rgba(0,0,0,.55)}",
    "/* 11/8 가림 줄이기: 닫힌 단추는 내릴 때 잠깐 숨고(.tuck) 페이지 끝에 단추만큼 빈 칸(host 높이)을 둔다.",
    "   연 창은 좁은 화면(1023px 이하)에서 아래 시트 + 뒤 어둡게(밖을 누르면 닫힘), 넓은 화면(1024px 이상)에서 오른쪽 옆 패널(본문을 패널 폭만큼 밀어냄) */",
    ".launcher{position:fixed;right:max(20px,env(safe-area-inset-right,0px));bottom:max(20px,env(safe-area-inset-bottom,0px));z-index:2147483000;width:60px;height:60px;border-radius:50%;border:0;background:var(--accent);color:var(--accent-fg);box-shadow:var(--ring),var(--shadow);cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:0;font-size:11.5px;font-weight:700;line-height:1.1;transition:background-color .15s,transform .2s,opacity .2s}",
    ".launcher svg{width:22px;height:22px;flex:none}",
    ".launcher:hover{background:var(--accent-hover)}",
    ".launcher:active{transform:scale(.96)}",
    ".launcher.tuck{transform:translateY(calc(100% + 32px));opacity:0;pointer-events:none}",
    ".wrap.open .launcher{display:none}",
    ".launcher:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}",
    ".scrim{position:fixed;inset:0;z-index:2147483000;background:var(--ui-scrim,rgba(0,0,0,.36));display:none}",
    ".wrap.open .scrim{display:block}",
    ".panel{position:fixed;left:0;right:0;bottom:0;margin:0 auto;z-index:2147483001;width:min(640px,100%);height:min(85vh,680px);max-height:calc(100% - 24px);display:flex;flex-direction:column;background:var(--bg);color:var(--fg);border:0;border-radius:24px 24px 0 0;box-shadow:var(--ring),var(--shadow);overflow:hidden;font-size:15px;line-height:1.55;padding-bottom:env(safe-area-inset-bottom,0px)}",
    ".panel::before{content:'';flex:none;align-self:center;width:40px;height:4px;border-radius:999px;background:var(--line);margin-top:10px}",
    ".panel[hidden],.launcher[hidden]{display:none}",
    ".wrap.kiosk .panel{width:min(760px,100%);height:min(88vh,880px);font-size:19px}",
    ".wrap.kiosk .launcher{width:96px;height:96px;font-size:16px}",
    ".wrap.kiosk .launcher svg{width:34px;height:34px}",
    ".wrap.kiosk .chip{font-size:18px;padding:16px 18px}",
    ".wrap.kiosk textarea{font-size:19px}",
    ".wrap.kiosk .send{font-size:18px;padding:0 24px;height:56px}",
    ".wrap.kiosk .foot,.wrap.kiosk .foot button{font-size:15px}",
    ".wrap.kiosk .welcome,.wrap.kiosk .card{font-size:18px}",
    ".wrap.kiosk header h2{font-size:21px}",
    ".wrap.kiosk header .mode{font-size:15px}",
    ".wrap.kiosk .badge,.wrap.kiosk details,.wrap.kiosk .retry{font-size:15px}",
    ".wrap.kiosk .icon{width:52px;height:52px;font-size:22px}",
    "@media (max-width:480px){.launcher{width:52px;height:52px;right:max(16px,env(safe-area-inset-right,0px));bottom:max(16px,env(safe-area-inset-bottom,0px))}.launcher .txt{display:none}.launcher svg{width:24px;height:24px}.wrap.kiosk .launcher{width:72px;height:72px}.panel{height:min(88vh,640px)}}",
    "@media (min-width:1024px){.wrap.open .scrim{display:none}.panel,.wrap.kiosk .panel{left:auto;right:0;top:0;bottom:0;margin:0;width:" + DOCK_W + "px;height:auto;max-height:none;border-radius:0;padding-bottom:0;box-shadow:-1px 0 0 var(--line),-16px 0 40px rgba(0,0,0,.06)}.panel::before{display:none}}",
    ".icon.close{width:44px;height:44px;font-size:17px}",
    ".wrap.kiosk .icon.close{width:56px;height:56px;font-size:22px}",
    "header{display:flex;align-items:center;gap:12px;padding:18px 14px 12px 20px}",
    "header .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px color-mix(in srgb,var(--ok) 18%,transparent);flex:none}",
    "header .dot.off{background:var(--faint);box-shadow:none}",
    "header h2{margin:0;font-size:17px;font-weight:700;letter-spacing:-.02em;flex:1;min-width:0;color:var(--fg)}",
    "header .mode{display:block;font-size:12.5px;font-weight:500;color:var(--faint);letter-spacing:0;margin-top:1px}",
    ".icon{border:0;background:var(--soft);color:var(--muted);width:36px;height:36px;border-radius:50%;cursor:pointer;font-size:15px;flex:none;display:grid;place-items:center;transition:background-color .15s}",
    ".icon:hover{background:var(--soft-hover);color:var(--fg)}",
    ".log{flex:1;overflow-y:auto;padding:8px 16px 16px;display:flex;flex-direction:column;gap:14px;overscroll-behavior:contain}",
    ".welcome{background:var(--soft);border-radius:20px;padding:18px;font-size:15px;color:var(--fg);line-height:1.6}",
    ".welcome p{margin:0 0 14px}",
    ".chips{display:flex;flex-direction:column;gap:8px}",
    ".choices{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px}",
    ".choice{font:inherit;font-size:.9em;font-weight:600;padding:8px 14px;border-radius:999px;border:0;background:var(--accent-soft);color:var(--accent);cursor:pointer;transition:background-color .15s,color .15s}",
    ".choice:hover{background:var(--accent);color:var(--accent-fg)}",
    ".chip{text-align:left;border:0;background:var(--bg);color:var(--fg);border-radius:14px;padding:12px 14px;font-size:14.5px;font-weight:600;line-height:1.4;cursor:pointer;transition:background-color .15s,color .15s}",
    ".chip:hover{background:var(--accent-soft);color:var(--accent)}",
    ".msg{display:flex;flex-direction:column;max-width:88%;gap:8px}",
    ".msg.user{align-self:flex-end;align-items:flex-end}",
    ".bubble{padding:11px 15px;border-radius:20px;white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere}",
    ".user .bubble{background:var(--user);color:var(--user-fg);border-bottom-right-radius:6px}",
    ".bot .bubble{background:var(--bot);color:var(--fg);border-bottom-left-radius:6px}",
    ".bot.pending .bubble{color:var(--faint)}",
    ".bot.error .bubble{color:var(--err)}",
    ".badges{display:flex;flex-wrap:wrap;gap:6px}",
    ".badge{font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;background:var(--soft);color:var(--muted);border:0}",
    ".badge.warn{background:var(--warn-bg);color:var(--warn)}",
    ".cards{display:grid;gap:6px;width:100%}",
    ".card{display:flex;justify-content:space-between;align-items:center;gap:8px;border:0;border-radius:14px;padding:11px 14px;background:var(--soft);font-size:14px}",
    ".card span{color:var(--faint);font-size:13px}",
    "details{font-size:13px;color:var(--muted);width:100%}",
    "summary{cursor:pointer;color:var(--accent);font-weight:600}",
    "details ul{margin:8px 0 0;padding-left:18px}",
    "details li{margin-bottom:8px}",
    "blockquote{margin:4px 0 0;padding-left:10px;border-left:3px solid var(--line);color:var(--faint)}",
    "a{color:var(--accent)}",
    ".retry{align-self:flex-start;border:0;background:var(--soft);color:var(--fg);border-radius:999px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer}",
    ".retry:hover{background:var(--soft-hover)}",
    "form{padding:10px 14px 14px;display:flex;flex-direction:column;gap:8px}",
    ".row{display:flex;gap:8px;align-items:flex-end}",
    "textarea{flex:1;min-width:0;resize:none;border:1.5px solid transparent;border-radius:16px;padding:12px 14px;font-size:15px;line-height:1.45;max-height:120px;min-height:48px;background:var(--soft);color:var(--fg);outline:none;transition:border-color .15s,background-color .15s}",
    "textarea::placeholder{color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    "textarea:focus{border-color:var(--accent);background:var(--bg)}",
    ".send{border:0;border-radius:16px;background:var(--accent);color:var(--accent-fg);font-size:15px;font-weight:700;padding:0 18px;height:48px;cursor:pointer;flex:none;transition:background-color .15s,opacity .15s}",
    ".send:hover{background:var(--accent-hover)}",
    ".send:disabled{opacity:.4;cursor:default}",
    ".foot{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--faint);padding:0 4px}",
    ".foot button{border:0;background:none;color:var(--muted);font-size:12px;cursor:pointer;padding:0;text-decoration:underline;text-underline-offset:2px}",
    ".sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}",
    "@media (prefers-reduced-motion:reduce){*{transition:none!important}}"
  ].join("\n");

  var host, root, wrap, panel, launcher, scrim, log, form, input, sendBtn, countEl, modeEl, dotEl, statusEl;
  var mqDock = null, pushed = null, lastY = 0, tuckTimer = null;
  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12a8 8 0 1 1 3.3 6.5L4 19.5l1-3.4A7.9 7.9 0 0 1 4 12z"/><path d="M8.5 11h.01M12 11h.01M15.5 11h.01"/></svg>';
  var busy = false, history = [], suggestions = [], lastFocus = null, loadedOnce = false;
  var activeRequest = null, conversationVersion = 0, statusLoading = false;

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
    wrap = el("div", KIOSK ? "wrap kiosk" : "wrap");

    launcher = el("button", "launcher");
    launcher.type = "button";
    launcher.innerHTML = ICON;
    launcher.append(el("span", "txt", "AI 챗봇"));   // 휴대폰 폭에서는 글자 없이 아이콘만
    launcher.setAttribute("aria-label", TITLE + " 열기");
    launcher.hidden = true;
    launcher.addEventListener("click", function () { toggle(); });

    // 좁은 화면 시트 뒤 어두운 막 — 누르면 닫힘(넓은 화면 옆 패널에서는 안 보임)
    scrim = el("div", "scrim");
    scrim.setAttribute("aria-hidden", "true");
    scrim.addEventListener("click", function () { closePanel(); });

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
    var close = el("button", "icon close", "✕");
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
    wrap.append(launcher, scrim, panel);
    root.append(style, wrap);
    document.body.appendChild(host);
    watchTheme();

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
    // Esc = 닫기: 창 안에 초점이 없어도(시트 밖을 본 뒤) 닫히도록 문서 전체에서 받는다
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel && !panel.hidden) closePanel(); });
    // 공용 기기: 창 안에서 무엇이든 조작하면 무입력 시계를 다시 잰다
    ["pointerdown", "keydown", "input", "wheel"].forEach(function (t) { panel.addEventListener(t, touchIdle, { passive: true }); });
    showWelcome();
    restoreChat();
  }

  // 11/8 디자인 개편: 화면 <html data-theme="light|dark">(/ui/theme.js 전환 버튼)를 위젯 안쪽(.wrap)에도 옮겨 적는다.
  // Shadow DOM 안 CSS 는 바깥 html 속성을 직접 볼 수 없어서다. 값이 없으면 "auto" → OS 밝기 설정을 따른다
  function syncTheme() {
    var de = document.documentElement;
    var t = de && de.getAttribute ? de.getAttribute("data-theme") : null;
    wrap.setAttribute("data-theme", t === "light" || t === "dark" ? t : "auto");
  }
  function watchTheme() {
    syncTheme();
    if (typeof MutationObserver === "function" && document.documentElement) {
      new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
  }

  function restoreChat() {
    // 새로고침 전 대화 다시 그리기(글만 — 후보 카드·근거 펼치기는 다시 그리지 않음)
    var saved = storeGet();
    if (!saved || !saved.msgs.length) return;
    var welcome = log.querySelector(".welcome");
    if (welcome) welcome.remove();
    saved.msgs.forEach(function (x) { if (x && (x.r === "user" || x.r === "bot") && typeof x.t === "string") line(x.r, x.t); });
    history = saved.history.filter(function (h) { return h && typeof h.q === "string"; }).slice(-MAX_HISTORY);
  }

  function showWelcome() {
    var box = el("div", "welcome");
    box.append(el("p", null, STAFF
      ? "직원용 관제 도우미예요. 반환 현황·실패 원인·로봇·챗봇 처리 시간을 관제 기록으로 계산해 보고해요(LangManus 구조 분석 에이전트). 이용 안내 질문도 그대로 답해요."
      : "안녕하세요. 분실물 찾는 방법, 본센터 방문, 필요한 준비물 같은 이용 안내를 도와드려요. 잃어버린 물건(품목·색)을 말씀하시면 보관 중인 후보도 찾아볼게요."));
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
    (STAFF ? STAFF_CHIPS : suggestions.slice(0, 3)).forEach(function (s) {
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

  function api(path, body, controller) {
    var init = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
    controller = controller || new AbortController();
    init.signal = controller.signal;
    var timer = setTimeout(function () { controller.abort(); }, STAFF ? 60000 : 30000);   // 관제 분석은 모델을 두 번 불러 더 걸림
    return fetch(API + path, init).then(function (r) {
      return r.json().catch(function () { throw new Error("서버 응답을 읽지 못했어요. 다시 시도해 주세요."); }).then(function (data) {
        if (!r.ok) {
          var d = data && data.detail;
          var msg = typeof d === "string" ? d : r.status === 503 ? "챗봇이 아직 준비되지 않았어요. 잠시 뒤 다시 시도해 주세요." : "요청을 처리하지 못했어요.";
          throw new Error(msg);
        }
        if (!data || typeof data !== "object" || Array.isArray(data) ||
            (path === "/chat/questions" && (typeof data.answer !== "string" || !data.answer.trim() ||
              !Array.isArray(data.sources || []) || !Array.isArray(data.candidates || []) ||
              !(data.sources || []).every(function (s) { return s && typeof s === "object" && !Array.isArray(s); }) ||
              !(data.candidates || []).every(function (c) { return c && typeof c === "object" && !Array.isArray(c); })))) {
          throw new Error("서버 응답 형식을 확인하지 못했어요. 다시 시도해 주세요.");
        }
        return data;
      });
    }).catch(function (err) {
      if (controller.signal.aborted) throw new Error("응답 시간이 길어 요청을 멈췄어요. 잠시 후 다시 시도해 주세요.");
      if (err instanceof TypeError) throw new Error("서버에 연결하지 못했어요. 인터넷 연결이나 관제탑 상태를 확인해 주세요.");
      throw err;
    }).finally(function () { clearTimeout(timer); });
  }

  function badgeText(res) {
    if (res.agent === "ops") return res.ops_used_llm && res.ops_used_llm.length ? "관제 분석 · AI 보고" : "관제 분석 · 계산 보고";
    if (res.agent === "search" || res.agent === "both") return res.database_mode === "demo_sqlite" ? "가상 DB 시연" : "물건 검색 안내";
    if (res.generation_used) return "문서 검색 + AI 답변";
    if (res.status === "answered") return res.sources && res.sources.length ? "문서 근거 안내" : "대화 안내";
    if (res.status === "partial" || res.status === "policy_pending") return "확정 안내가 필요한 내용";
    if (res.status === "clarification_needed") return "조금 더 알려 주세요";
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

    // 11/6 되묻기(유도 질문): 고를 수 있는 답을 버튼으로. 누르면 그 글자로 바로 질문
    var choices = Array.isArray(res.choices) ? res.choices.filter(function (c) { return typeof c === "string" && c.trim() && c.length <= 40; }).slice(0, 4) : [];
    if (choices.length) {
      var row = el("div", "choices");
      choices.forEach(function (c) {
        var btn = el("button", "choice", c);
        btn.type = "button";
        btn.addEventListener("click", function () { if (!busy) send(c); });
        row.append(btn);
      });
      m.append(row);
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

  function send(text, suggestionId, retryHistory) {
    var q = (text || "").trim();
    if (busy || !q) return;
    if (q.length > MAX_LEN) { statusEl.textContent = "질문을 500자 이하로 줄여 주세요. 입력한 내용은 그대로 남겨 뒀어요."; return; }
    var welcome = root.querySelector(".welcome");
    if (welcome) welcome.remove();
    var userLine = line("user", q);
    if (input.value.trim() === q) input.value = "";
    input.dispatchEvent(new Event("input"));
    var pending = line("bot pending", "질문을 확인하고 있어요…");
    setBusy(true);
    statusEl.textContent = "답변 준비 중";
    var body = { question: q, history: (retryHistory || history).slice(-MAX_HISTORY) };
    if (suggestionId) body.suggestion_id = suggestionId;
    body.session_id = getSessionId();
    if (STAFF) body.mode = "staff";
    var request = { controller: new AbortController(), version: conversationVersion };
    activeRequest = request;
    api("/chat/questions", body, request.controller).then(function (res) {
      if (activeRequest !== request) return;
      var answerText = res.answer || "답변을 만들지 못했어요. 질문을 조금 바꿔 다시 물어봐 주세요.";
      history = body.history.concat([{ q: q, a: String(res.answer || "").slice(0, MAX_ANSWER) }]).slice(-MAX_HISTORY);
      pending.remove();
      var m = line("bot", answerText);
      var saved = storeGet() || { history: [], msgs: [] };
      saved.history = history;
      saved.sid = getSessionId();
      saved.msgs = saved.msgs.concat([{ r: "user", t: q }, { r: "bot", t: answerText }]).slice(-MAX_MESSAGES);
      storeSet(saved);
      addExtras(m, res);
      statusEl.textContent = res.agent === "ops" ? "관제 기록 기준 · 직원 전용" :
        res.agent === "search" || res.agent === "both" ? "후보는 본인 물건 확정이 아니에요" : "안내 완료 · 근거를 펼쳐 볼 수 있어요";
      scroll();
    }).catch(function (err) {
      if (activeRequest !== request) return;
      pending.remove();
      var m = line("bot error", err.message);
      var retry = el("button", "retry", "다시 보내기");
      retry.type = "button";
      retry.addEventListener("click", function () { if (busy || request.version !== conversationVersion) return; m.remove(); userLine.remove(); send(q, suggestionId, body.history); });
      m.append(retry);
      statusEl.textContent = "전송하지 못했어요";
    }).finally(function () {
      if (activeRequest !== request) return;
      activeRequest = null;
      setBusy(false);
      touchIdle();   // 답을 읽는 시간부터 다시 잰다
      if (!panel.hidden && (document.activeElement === host || document.activeElement === input)) input.focus();
    });
  }

  function touchIdle() {
    if (!IDLE_S) return;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () {
      if (log && log.querySelector(".msg")) resetChat(true);   // 대화가 있을 때만 지움
      closePanel();
    }, IDLE_S * 1000);
  }

  function resetChat(silent) {
    var previous = activeRequest;
    activeRequest = null;
    conversationVersion++;
    if (previous) previous.controller.abort();
    setBusy(false);
    history = [];
    storeSet(null);
    sessionId = null;
    input.value = "";
    input.dispatchEvent(new Event("input"));
    log.replaceChildren();
    showWelcome();
    statusEl.textContent = "이 화면의 대화를 지웠어요";
    if (silent !== true) input.focus();
  }

  function loadStatus() {
    if (statusLoading) return;
    statusLoading = true;
    api("/chat/health").then(function (h) {
      if (!h.ready) { loadedOnce = false; modeEl.textContent = "준비 중 — 관제탑 확인 필요"; dotEl.className = "dot off"; return; }
      dotEl.className = "dot";
      modeEl.textContent = STAFF ? (h.staff_ops ? "이용 안내 + 관제 분석(직원)" : "이용 안내 — 관제 분석은 관제탑에서만") : h.search_mode === "demo_sqlite" ? "이용 안내 + 가상 물건 검색" : h.search_mode === "postgres" ? "이용 안내 + 본인인증 후 물건 검색" : "이용 안내";
      return api("/chat/suggestions").then(function (s) { suggestions = (s && s.items) || []; renderChips(); });
    }).catch(function () { loadedOnce = false; modeEl.textContent = "연결 확인 필요"; dotEl.className = "dot off"; })
      .finally(function () { statusLoading = false; });
  }

  // ── 11/8 가림 줄이기 ─────────────────────────────────────────
  function isDocked() { return !!(mqDock && mqDock.matches); }
  // 넓은 화면에서 창이 열려 있으면 body 오른쪽 여백을 패널 폭만큼 준다. 원래 인라인 값을 기억했다가 그대로 되돌린다
  function layout() {
    var b = document.body;
    if (!b || !b.style) return;
    var want = !!panel && !panel.hidden && isDocked();
    if (want && !pushed) { pushed = { mr: b.style.marginRight || "" }; b.style.marginRight = DOCK_W + "px"; }
    else if (!want && pushed) { b.style.marginRight = pushed.mr; pushed = null; }
  }
  // 떠 있는 단추가 보이는 화면: 위젯 자리(host)를 페이지 맨 끝의 빈 칸으로 써서, 끝까지 내리면 마지막 버튼·글이 단추에 가리지 않게
  function updateSpacer() {
    if (!host || !host.style) return;
    var need = SPACER && launcher && !launcher.hidden;
    if (!need) { host.style.display = ""; host.style.height = ""; host.style.flex = ""; return; }
    var h = 92;
    try {
      var cs = getComputedStyle(launcher);
      h = Math.ceil((launcher.offsetHeight || 60) + (parseFloat(cs.bottom) || 20) + 12);
    } catch (e) { /* 계산 못 하면 기본 92px */ }
    host.style.display = "block"; host.style.height = h + "px"; host.style.flex = "none";
  }
  // 아래로 내리는 동안 단추를 잠깐 숨기고, 멈추거나 위로 올리거나 맨 끝에 닿으면 다시 보인다
  function onScroll() {
    if (!launcher || launcher.hidden) return;
    var y = window.pageYOffset || 0;
    var de = document.documentElement;
    var atEnd = de && y + window.innerHeight >= de.scrollHeight - 4;
    if (y > lastY + 4 && !atEnd) launcher.classList.add("tuck");
    else if (y < lastY - 4 || atEnd) launcher.classList.remove("tuck");
    lastY = y;
    clearTimeout(tuckTimer);
    tuckTimer = setTimeout(function () { launcher.classList.remove("tuck"); }, 1200);
  }
  function watchLayout() {
    if (typeof window.matchMedia === "function") {
      mqDock = window.matchMedia(DOCK_QUERY);
      if (mqDock.addEventListener) mqDock.addEventListener("change", layout); else if (mqDock.addListener) mqDock.addListener(layout);
    }
    if (typeof window.addEventListener === "function") {
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", updateSpacer);
    }
  }

  function openPanel() {
    if (!panel) build();
    if (!panel.hidden) return;
    lastFocus = document.activeElement;
    panel.hidden = false;
    wrap.classList.add("open"); // 창이 열리면 동그란 버튼은 숨긴다(창의 ✕·시트 밖 누르기·Esc 로 닫음)
    layout();
    launcher.setAttribute("aria-expanded", "true");
    if (!loadedOnce) { loadedOnce = true; loadStatus(); }
    touchIdle();
    setTimeout(function () { if (!panel.hidden) input.focus(); }, 0);
  }

  function closePanel() {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    wrap.classList.remove("open");
    layout();
    launcher.setAttribute("aria-expanded", "false");
    if (KIOSK) { clearTimeout(idleTimer); if (log && log.querySelector(".msg")) resetChat(true); }  // 공용 기기는 닫으면 바로 지움
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
  }

  function toggle() { if (!panel || panel.hidden) openPanel(); else closePanel(); }

  function init() {
    build();
    var hasOpener = !!document.querySelector("[data-chatbot-open]");
    launcher.hidden = LAUNCHER === "off" || (LAUNCHER === "auto" && hasOpener);
    watchLayout();
    updateSpacer();
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
