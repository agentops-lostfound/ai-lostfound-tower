/* AI 분실물 챗봇 위젯 (LF-5, 11/5) — 화면에 한 줄로 붙인다:
 *   <script src="/chat-widget/widget.js" defer></script>
 * 열기: data-chatbot-open 속성이 있는 버튼을 누르거나, 그런 버튼이 없으면 오른쪽 아래 동그란 버튼이 자동으로 생긴다.
 * 스크립트 태그 옵션
 *   data-launcher="auto"(기본: 열기 버튼이 없을 때만 동그란 버튼) | "always" | "off"
 *   data-spacer="off"     동그란 버튼이 보일 때 페이지 끝에 버튼만큼 빈 칸을 두는 것을 끔(기본: 둠)
 *   11/8 작은 떠 있는 창: 기본 오른쪽 아래 360×520(키오스크 460×640, 휴대폰 폭 600px 이하는 92vw×60vh 아래쪽).
 *   머리줄을 끌어 옮김(마우스·터치, 화면 밖으로 못 나감) · 접기(알약 모양, 새 답이 오면 점) · 구석 손잡이/작게·크게 단추로 크기 조절 · 닫기.
 *   위치·크기는 localStorage 에 기억(화면 주소별). 처음 열 때는 버튼·입력칸이 가장 적게 가려지는 구석을 고르고, 창 밖 화면은 그대로 누를 수 있다(어두운 막 없음).
 *   11/10 답은 막대가 100% 가 된 뒤에 나온다(답이 오면 남은 숫자를 최대 0.45초에 채움).
 *   11/8 진행률: 답을 기다리는 동안 말풍선 자리에 0~100% 막대(서버 단계 알림 + 최근 응답 시간으로 채운 예상치). 0.3초 안에 끝나면 보이지 않음
 *   data-api="http://…"  챗봇 API 주소(기본: 이 스크립트를 내려준 서버 = 관제탑)
 *   data-title="AI 안내 도우미"
 *   data-mode="kiosk"     공용 키오스크용(11/6): 글자·버튼을 크게, 창을 닫으면 대화를 바로 지움
 *   data-mode="staff"     직원 관리자 화면용(11/6): 이용 안내 + "오늘 반환 실패 원인?" 같은 관제 질문(관리자 로그인 필요, LangManus 구조 분석 에이전트)
 *   data-idle-reset="90"  아무 조작이 없으면 N초 뒤 대화를 지우고 창을 닫음(다음 사람에게 앞사람 대화가 보이지 않게). kiosk 기본 90, 웹은 0(끔)
 * 코드에서: window.LostFoundChat.open() / close() / toggle()
 * 대화 내용은 이 화면에만 있고 저장하지 않는다(새로 고침하면 사라짐). 스타일은 Shadow DOM 안에 가둬 화면 디자인을 건드리지 않는다.
 * 11/8 디자인 개편: 색·글꼴은 공통 토큰(/ui/theme.css 의 --ui-*)을 따른다(없는 화면은 대체값). 화면이 라이트/다크를 바꾸면(html data-theme) 위젯도 같이 바뀐다.
 * 11/9 창 밝기 단추(머리줄 ☀/🌙 그림): 이 창만 라이트·다크를 바꾼다. 고른 값은 창 자리와 같은 localStorage 칸(winKey)의 theme 에 기억하고,
 *   직접 고른 값이 있으면 화면 테마보다 우선한다. 화면과 같은 밝기로 다시 누르면 기억을 지우고 다시 화면을 따른다.
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
  // 11/8 작은 떠 있는 창: 크기 두 단계(작게·크게). 휴대폰 폭(600px 이하)은 폭 92vw, 높이 60vh·85vh
  var PHONE_MAX = 600;
  var SIZES = KIOSK ? { small: [460, 640], large: [620, 860] } : { small: [360, 520], large: [480, 720] };
  var MIN_W = KIOSK ? 380 : 300, MIN_H = KIOSK ? 420 : 340;
  var WIN_KEY = "lf-chat-win:" + location.pathname;
  // 11/9 창 투명도(사용자 요청): 머리말 조절바로 35~100%. 화면마다 기억(localStorage, 이 브라우저에서만)
  var OPACITY_KEY = "lf-chat-opacity:" + location.pathname, OPACITY_MIN = 35;
  // 11/8 진행률: 서버 단계(agents/chat_progress.py STAGES 와 같은 값)와 화면 글
  var STAGE_PCT = { received: 5, route: 12, retrieve: 22, intake: 25, search: 28, analyze: 30, write: 35, check: 80, rewrite: 84, recheck: 92 };
  var STAGE_NEXT = { write: "check", rewrite: "recheck" };   // 반드시 뒤따르는 단계 — 그 전까지는 시간으로 채워도 다음 단계 값을 넘지 않음
  var STAGE_TEXT = { received: "질문 받음", route: "질문 이해", retrieve: "안내 자료 찾기", intake: "접수 내용 확인", search: "물건 찾기", analyze: "관제 기록 분석", write: "답 쓰기", check: "근거 확인", rewrite: "다시 쓰기", recheck: "다시 확인" };
  var SHOW_AFTER_MS = 300, DEFAULT_EST_MS = 3000;
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

  // 11/9 창에서 직접 고른 밝기: 화면의 공통 토큰(--ui-*)은 화면 테마 값이라, 창만 반대 밝기를 고르면 .wrap 안에서 공통 토큰을
  // /ui/theme.css 와 같은 값으로 다시 정한다(아래 .wrap[data-own=…]). 값을 바꾸면 theme.css 와 함께 바꾼다
  var OWN_TOKENS = {
    light: "--ui-surface:#ffffff;--ui-text:#191f28;--ui-text-2:#4e5968;--ui-text-3:#8b95a1;--ui-line:#e5e8eb;--ui-fill:#f2f4f6;--ui-fill-hover:#e8ebed;--ui-primary:#3182f6;--ui-primary-hover:#1b64da;--ui-primary-soft:#e8f3ff;--ui-on-primary:#ffffff;--ui-ok:#03b26c;--ui-warn:#e58a00;--ui-warn-soft:#fff4e0;--ui-err:#f04452",
    dark: "--ui-surface:#1c1c21;--ui-text:#f2f3f5;--ui-text-2:#b0b4bc;--ui-text-3:#7e838c;--ui-line:#2e2e36;--ui-fill:#2a2a32;--ui-fill-hover:#33333c;--ui-primary:#4593fc;--ui-primary-hover:#6aa8fd;--ui-primary-soft:#1b2a40;--ui-on-primary:#ffffff;--ui-ok:#20c47f;--ui-warn:#f0a33a;--ui-warn-soft:#362a14;--ui-err:#ff5f6d"
  };
  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:var(--ui-font,'Pretendard Variable','Pretendard','Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',system-ui,sans-serif);letter-spacing:-.01em}",
    "/* 11/8 디자인 개편: 위젯 토큰은 공통 토큰(--ui-*)을 따른다. 공통 파일이 없는 화면은 괄호 안 대체값을 쓴다 */",
    ".wrap{color-scheme:light;--bg:var(--ui-surface,#ffffff);--fg:var(--ui-text,#191f28);--muted:var(--ui-text-2,#4e5968);--faint:var(--ui-text-3,#8b95a1);--line:var(--ui-line,#e5e8eb);--soft:var(--ui-fill,#f2f4f6);--soft-hover:var(--ui-fill-hover,#e8ebed);--accent:var(--ui-primary,#3182f6);--accent-hover:var(--ui-primary-hover,#1b64da);--accent-soft:var(--ui-primary-soft,#e8f3ff);--accent-fg:var(--ui-on-primary,#ffffff);--user:var(--ui-primary,#3182f6);--user-fg:var(--ui-on-primary,#ffffff);--bot:var(--ui-fill,#f2f4f6);--ok:var(--ui-ok,#03b26c);--warn:var(--ui-warn,#e58a00);--warn-bg:var(--ui-warn-soft,#fff4e0);--err:var(--ui-err,#f04452);--ring:0 0 0 0 transparent;--shadow:0 16px 48px rgba(0,0,0,.12),0 2px 8px rgba(0,0,0,.06)}",
    "/* 다크: 화면이 data-theme=dark 를 고른 경우 + data-theme 없이 OS 가 다크인 경우(.wrap[data-theme] 는 화면의 html 값을 그대로 옮긴 것) */",
    "@media (prefers-color-scheme:dark){.wrap:not([data-theme=light]){color-scheme:dark;--bg:var(--ui-surface,#1c1c21);--fg:var(--ui-text,#f2f3f5);--muted:var(--ui-text-2,#b0b4bc);--faint:var(--ui-text-3,#7e838c);--line:var(--ui-line,#2e2e36);--soft:var(--ui-fill,#2a2a32);--soft-hover:var(--ui-fill-hover,#33333c);--accent:var(--ui-primary,#4593fc);--accent-hover:var(--ui-primary-hover,#6aa8fd);--accent-soft:var(--ui-primary-soft,#1b2a40);--accent-fg:var(--ui-on-primary,#ffffff);--user:var(--ui-primary,#4593fc);--user-fg:var(--ui-on-primary,#ffffff);--bot:var(--ui-fill,#2a2a32);--ok:var(--ui-ok,#20c47f);--warn:var(--ui-warn,#f0a33a);--warn-bg:var(--ui-warn-soft,#362a14);--err:var(--ui-err,#ff5f6d);--ring:0 0 0 1px rgba(255,255,255,.07);--shadow:0 16px 48px rgba(0,0,0,.55)}}",
    ".wrap[data-theme=dark]{color-scheme:dark;--bg:var(--ui-surface,#1c1c21);--fg:var(--ui-text,#f2f3f5);--muted:var(--ui-text-2,#b0b4bc);--faint:var(--ui-text-3,#7e838c);--line:var(--ui-line,#2e2e36);--soft:var(--ui-fill,#2a2a32);--soft-hover:var(--ui-fill-hover,#33333c);--accent:var(--ui-primary,#4593fc);--accent-hover:var(--ui-primary-hover,#6aa8fd);--accent-soft:var(--ui-primary-soft,#1b2a40);--accent-fg:var(--ui-on-primary,#ffffff);--user:var(--ui-primary,#4593fc);--user-fg:var(--ui-on-primary,#ffffff);--bot:var(--ui-fill,#2a2a32);--ok:var(--ui-ok,#20c47f);--warn:var(--ui-warn,#f0a33a);--warn-bg:var(--ui-warn-soft,#362a14);--err:var(--ui-err,#ff5f6d);--ring:0 0 0 1px rgba(255,255,255,.07);--shadow:0 16px 48px rgba(0,0,0,.55)}",
    ".wrap[data-own=light]{" + OWN_TOKENS.light + "}",
    ".wrap[data-own=dark]{" + OWN_TOKENS.dark + "}",
    "/* 11/8 가림 줄이기: 닫힌 단추는 내릴 때 잠깐 숨고(.tuck) 페이지 끝에 단추만큼 빈 칸(host 높이)을 둔다.",
    "   연 창은 작은 떠 있는 창(left/top/width/height 는 스크립트가 정함). 어두운 막이 없어 창 밖 화면은 그대로 누를 수 있다 */",
    ".launcher{position:fixed;right:max(20px,env(safe-area-inset-right,0px));bottom:max(20px,env(safe-area-inset-bottom,0px));z-index:2147483000;width:60px;height:60px;border-radius:50%;border:0;background:var(--accent);color:var(--accent-fg);box-shadow:var(--ring),var(--shadow);cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:0;font-size:11.5px;font-weight:700;line-height:1.1;transition:background-color .15s,transform .2s,opacity .2s}",
    ".launcher svg{width:22px;height:22px;flex:none}",
    ".launcher:hover{background:var(--accent-hover)}",
    ".launcher:active{transform:scale(.96)}",
    ".launcher.tuck{transform:translateY(calc(100% + 32px));opacity:0;pointer-events:none}",
    ".wrap.open .launcher{display:none}",
    ".launcher:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}",
    ".panel{position:fixed;left:0;top:0;z-index:2147483001;width:360px;height:520px;display:flex;flex-direction:column;background:var(--bg);color:var(--fg);border:0;border-radius:20px;box-shadow:var(--ring),var(--shadow);overflow:hidden;font-size:15px;line-height:1.55;transition:opacity .15s;opacity:var(--lf-op,1)}",
    "/* 11/9 투명도 조절바(머리말) */",
    ".opac{width:44px;accent-color:var(--accent);cursor:pointer;margin:0 2px;flex:none}",
    ".wrap.kiosk .opac{width:72px}",
    "@media (max-width:360px){.opac{width:44px}}",
    "/* 11/9 대화 접수: 본인 확인 입력칸(가린 값만 보냄) */",
    ".idform{display:flex;flex-direction:column;gap:8px;margin-top:4px;padding:12px;border-radius:14px;background:var(--accent-soft)}",
    ".idform label{display:flex;flex-direction:column;gap:4px;font-size:.88em;font-weight:600}",
    ".idform input,.idform select{font:inherit;padding:8px 10px;border-radius:10px;border:1px solid var(--line,#ccd);background:var(--bg);color:var(--fg);min-width:0}",
    ".idform .note{font-size:.8em;opacity:.8}",
    ".idform button{font:inherit;font-weight:700;padding:9px 14px;border-radius:12px;border:0;background:var(--accent);color:var(--accent-fg);cursor:pointer}",
    ".idform button:disabled{opacity:.4;cursor:default}",
    ".panel[hidden],.launcher[hidden]{display:none}",
    "/* 끄는 동안 반투명: 창 아래 화면을 보면서 놓을 자리를 고른다 */",
    ".wrap.dragging .panel,.wrap.resizing .panel{opacity:.55;transition:none;user-select:none;-webkit-user-select:none}",
    ".wrap.min .panel{display:none}",
    ".grip{position:absolute;width:20px;height:20px;z-index:2;touch-action:none;opacity:.55;background:linear-gradient(135deg,transparent 0 46%,var(--faint) 46% 54%,transparent 54% 66%,var(--faint) 66% 74%,transparent 74%)}",
    ".grip:hover{opacity:1}",
    ".grip.tl{left:2px;top:2px;cursor:nwse-resize;transform:rotate(180deg)}",
    ".grip.tr{right:2px;top:2px;cursor:nesw-resize;transform:rotate(-90deg)}",
    ".grip.bl{left:2px;bottom:2px;cursor:nesw-resize;transform:rotate(90deg)}",
    ".grip.br{right:2px;bottom:2px;cursor:nwse-resize}",
    "/* 접은 창: 작은 알약. 새 답이 오면 점 */",
    ".pill{position:fixed;z-index:2147483001;display:none;align-items:center;gap:8px;height:48px;max-width:min(320px,calc(100vw - 24px));padding:0 16px 0 10px;border-radius:999px;border:0;background:var(--bg);color:var(--fg);box-shadow:var(--ring),var(--shadow);font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap}",
    ".pill .ic{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--accent);color:var(--accent-fg);flex:none}",
    ".pill .ic svg{width:17px;height:17px}",
    ".pill .pt{overflow:hidden;text-overflow:ellipsis}",
    ".pill .nd{display:none;width:9px;height:9px;border-radius:50%;background:var(--err);flex:none}",
    ".pill.unread .nd{display:block}",
    ".pill:hover{background:var(--soft)}",
    ".wrap.min .pill{display:flex}",
    ".wrap.kiosk .panel{font-size:19px}",
    ".wrap.kiosk .pill{height:64px;font-size:17px;padding:0 22px 0 12px}",
    ".wrap.kiosk .pill .ic{width:40px;height:40px}",
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
    ".wrap.kiosk .icon{width:56px;height:56px;font-size:22px}",
    ".wrap.kiosk .icon svg{width:24px;height:24px}",
    ".wrap.kiosk .prog .ptxt{font-size:15px}",
    "@media (max-width:480px){.launcher{width:52px;height:52px;right:max(16px,env(safe-area-inset-right,0px));bottom:max(16px,env(safe-area-inset-bottom,0px))}.launcher .txt{display:none}.launcher svg{width:24px;height:24px}.wrap.kiosk .launcher{width:72px;height:72px}}",
    "/* 휴대폰 폭: 손잡이는 숨기고(손가락으로 잡기 어려움) 작게·크게 단추로 높이를 바꾼다 */",
    "@media (max-width:600px){.grip{display:none}.panel{border-radius:18px}.wrap.kiosk .icon{width:40px;height:40px;font-size:18px}.wrap.kiosk .panel{font-size:16.5px}.wrap.kiosk header h2{font-size:18px}.wrap.kiosk .opac{display:none}.wrap.kiosk .welcome,.wrap.kiosk .card{font-size:16px}.wrap.kiosk .chip{font-size:16px;padding:12px 14px}.wrap.kiosk textarea{font-size:17px}.wrap.kiosk .send{font-size:16px;height:50px;padding:0 18px}}",
    "header{display:flex;align-items:center;gap:6px;padding:10px 8px 8px 20px;cursor:grab;touch-action:none;user-select:none;-webkit-user-select:none;flex:none}",
    ".wrap.dragging header{cursor:grabbing}",
    "header .tools{display:flex;gap:2px;flex:none}",
    "header .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px color-mix(in srgb,var(--ok) 18%,transparent);flex:none}",
    "header .dot.off{background:var(--faint);box-shadow:none}",
    "header .dot{margin-right:6px}",
    "header h2{margin:0;font-size:17px;font-weight:700;letter-spacing:-.02em;flex:1;min-width:0;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    "header .mode{display:block;font-size:12.5px;font-weight:500;color:var(--faint);letter-spacing:0;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    "/* 11/9 머리줄 단추는 손가락으로 누르기 쉽게 44px(키오스크 56px) */",
    ".icon{border:0;background:transparent;color:var(--muted);width:44px;height:44px;border-radius:50%;cursor:pointer;font-size:15px;flex:none;display:grid;place-items:center;padding:0;transition:background-color .15s}",
    ".icon svg{width:18px;height:18px}",
    ".icon.close{background:var(--soft)}",
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
    "/* 11/8 진행률: 답 말풍선 자리의 얇은 막대 + 글. 퍼센트는 예상치라 '예상'을 작게 붙인다 */",
    ".prog{display:flex;flex-direction:column;gap:7px;min-width:min(220px,60vw)}",
    ".prog .track{height:4px;border-radius:999px;background:var(--line);overflow:hidden}",
    ".prog .fill{height:100%;width:0;background:var(--accent);border-radius:inherit;transition:width .06s linear}",
    ".prog .ptxt{display:flex;align-items:baseline;justify-content:space-between;gap:10px;font-size:12.5px;color:var(--muted);white-space:nowrap}",
    ".prog .ptxt b{font-weight:600;font-variant-numeric:tabular-nums}",
    ".prog .est{font-size:11px;color:var(--faint);font-weight:500}",
    ".prog.done{transition:opacity .4s;opacity:0}",
    ".msg>.prog{width:100%;max-width:240px}",
    ".sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}",
    "@media (prefers-reduced-motion:reduce){*{transition:none!important}}"
  ].join("\n");

  var host, root, wrap, panel, launcher, log, form, input, sendBtn, countEl, modeEl, dotEl, statusEl;
  var header, grip, pill, pillText, minBtn, sizeBtn, themeBtn;
  var userTheme = null;   // 11/9 이 창에서 직접 고른 밝기("light"|"dark"), 없으면 null = 화면 테마를 따름
  var lastY = 0, tuckTimer = null;
  var win = null, cur = null, minimized = false, winPhone = null;   // 창 자리: win = 기억하는 값(붙은 구석 + 거리 + 크기), cur = 지금 그린 사각형
  var durations = [], metricsP50 = null, metricsP95 = null;          // 진행률 예상 시간(최근 응답 시간)
  var SVG_MIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 17h12"/></svg>';
  var SVG_BIG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/></svg>';
  var SVG_SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/></svg>';
  var SVG_MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>';
  var SVG_SMALL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10h-6V4M4 14h6v6M14 10l7-7M10 14l-7 7"/></svg>';
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

    panel = el("section", "panel");
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "false");
    panel.setAttribute("aria-label", TITLE);

    // 머리줄 = 끌어 옮기는 손잡이(단추를 누른 경우는 제외)
    header = el("header");
    header.title = "끌어서 옮길 수 있어요";
    dotEl = el("span", "dot off");
    var h2 = el("h2", null, TITLE);
    modeEl = el("span", "mode", "연결 확인 중…");
    h2.appendChild(modeEl);
    var tools = el("div", "tools");
    themeBtn = el("button", "icon theme");
    themeBtn.type = "button";
    themeBtn.addEventListener("click", function () { toggleTheme(); });
    minBtn = el("button", "icon min");
    minBtn.type = "button";
    minBtn.innerHTML = SVG_MIN;
    minBtn.setAttribute("aria-label", "챗봇 접기");
    minBtn.title = "접기";
    minBtn.addEventListener("click", function () { minimize(); });
    sizeBtn = el("button", "icon size");
    sizeBtn.type = "button";
    sizeBtn.innerHTML = SVG_BIG;
    sizeBtn.setAttribute("aria-label", "창 크게");
    sizeBtn.title = "크게";
    sizeBtn.addEventListener("click", function () { toggleSize(); });
    var close = el("button", "icon close", "✕");
    close.type = "button";
    close.setAttribute("aria-label", "챗봇 닫기");
    close.title = "닫기";
    close.addEventListener("click", function () { closePanel(); });
    var opac = el("input", "opac");
    opac.type = "range"; opac.min = String(OPACITY_MIN); opac.max = "100"; opac.step = "5";
    opac.setAttribute("aria-label", "창 투명도");
    opac.title = "창 투명도(왼쪽으로 갈수록 투명)";
    var startOp = 100;
    try { startOp = Math.max(OPACITY_MIN, Math.min(100, parseInt(localStorage.getItem(OPACITY_KEY) || "100", 10) || 100)); } catch (e) { startOp = 100; }
    opac.value = String(startOp);
    function applyOpacity(v) { try { wrap.style.setProperty("--lf-op", String(v / 100)); } catch (e) { /* 오래된 브라우저: 투명도만 못 바꿈 */ } }
    applyOpacity(startOp);
    opac.addEventListener("input", function () {
      var v = Math.max(OPACITY_MIN, Math.min(100, parseInt(opac.value, 10) || 100));
      applyOpacity(v);
      try { localStorage.setItem(OPACITY_KEY, String(v)); } catch (e) { /* 기억 못 해도 지금 화면엔 적용 */ }
    });
    opac.addEventListener("pointerdown", function (e) { e.stopPropagation(); });   // 조절바를 끌 때 창이 같이 움직이지 않게
    tools.append(opac, themeBtn, minBtn, sizeBtn, close);
    header.append(dotEl, h2, tools);
    header.addEventListener("pointerdown", function (e) {
      if (e.button > 0 || (e.target && e.target.closest && e.target.closest("button"))) return;
      if (e.target && e.target.closest && e.target.closest("input")) return;
      startDrag(e, "move");
    });
    // 구석 손잡이: 화면 가운데 쪽 구석에 붙는다(창이 오른쪽 아래면 왼쪽 위)
    grip = el("div", "grip tl");
    grip.setAttribute("aria-hidden", "true");
    grip.title = "끌어서 크기 바꾸기";
    grip.addEventListener("pointerdown", function (e) { if (e.button > 0) return; e.stopPropagation(); startDrag(e, "resize"); });

    // 접은 창: 작은 알약(누르면 다시 펼침)
    pill = el("button", "pill");
    pill.type = "button";
    var pillIcon = el("span", "ic");
    pillIcon.innerHTML = ICON;
    pillText = el("span", "pt", TITLE);
    pill.append(pillIcon, pillText, el("span", "nd"));
    pill.setAttribute("aria-label", TITLE + " 펼치기");
    pill.addEventListener("click", function () { restore(); });

    log = el("div", "log");
    log.setAttribute("role", "log");
    log.setAttribute("aria-live", "polite");

    form = el("form");
    var row = el("div", "row");
    input = el("textarea");
    input.rows = 1;
    input.maxLength = MAX_LEN;
    input.placeholder = "궁금한 점을 적어 주세요 (예: 검정 카드지갑 찾아줘)";
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

    panel.append(header, log, form, grip);
    wrap.append(launcher, panel, pill);
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
    // Esc = 닫기: 창 안에 초점이 없어도(창 밖을 본 뒤) 닫히도록 문서 전체에서 받는다
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel && !panel.hidden) closePanel(); });
    // 공용 기기: 창 안에서 무엇이든 조작하면 무입력 시계를 다시 잰다
    ["pointerdown", "keydown", "input", "wheel"].forEach(function (t) { panel.addEventListener(t, touchIdle, { passive: true }); });
    pill.addEventListener("pointerdown", touchIdle, { passive: true });
    showWelcome();
    restoreChat();
  }

  // 11/8 디자인 개편: 화면 <html data-theme="light|dark">(/ui/theme.js 전환 버튼)를 위젯 안쪽(.wrap)에도 옮겨 적는다.
  // Shadow DOM 안 CSS 는 바깥 html 속성을 직접 볼 수 없어서다. 값이 없으면 "auto" → OS 밝기 설정을 따른다
  // 11/9 창 밝기 단추: 이 창에서 고른 값(userTheme)이 있으면 그 값, 없으면 화면 값. 우선순위 = 창에서 고른 값 > 화면 data-theme > OS 설정
  function pageThemeAttr() {
    var de = document.documentElement;
    var t = de && de.getAttribute ? de.getAttribute("data-theme") : null;
    return t === "light" || t === "dark" ? t : null;
  }
  function osDark() {
    try { return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches); } catch (e) { return false; }
  }
  function pageTheme() { return pageThemeAttr() || (osDark() ? "dark" : "light"); }
  function effectiveTheme() { return userTheme || pageTheme(); }
  function paintThemeBtn() {
    if (!themeBtn) return;
    var dark = effectiveTheme() === "dark";
    themeBtn.innerHTML = dark ? SVG_SUN : SVG_MOON;      // 누르면 바뀔 모습: 다크일 때 해(밝게), 라이트일 때 달(어둡게)
    themeBtn.setAttribute("aria-label", dark ? "챗봇 창 밝게" : "챗봇 창 어둡게");
    themeBtn.title = dark ? "창 밝게" : "창 어둡게";
  }
  function syncTheme() {
    wrap.setAttribute("data-theme", userTheme || pageThemeAttr() || "auto");
    if (userTheme) wrap.setAttribute("data-own", userTheme); else if (wrap.removeAttribute) wrap.removeAttribute("data-own"); else wrap.setAttribute("data-own", "");
    paintThemeBtn();
  }
  function toggleTheme() {
    var next = effectiveTheme() === "dark" ? "light" : "dark";
    userTheme = next === pageTheme() ? null : next;     // 화면과 같은 값으로 돌아오면 기억을 지우고 다시 화면을 따른다
    writeStore();
    syncTheme();
  }
  function watchTheme() {
    userTheme = loadTheme();
    syncTheme();
    if (typeof MutationObserver === "function" && document.documentElement) {
      new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
    try {
      var mq = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
      if (mq && mq.addEventListener) mq.addEventListener("change", paintThemeBtn); else if (mq && mq.addListener) mq.addListener(paintThemeBtn);
    } catch (e) { /* 오래된 브라우저: 단추 그림만 늦게 바뀜 */ }
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

  function failMessage(status, d) {
    return typeof d === "string" && d ? d : status === 503 ? "챗봇이 아직 준비되지 않았어요. 잠시 뒤 다시 시도해 주세요." : "요청을 처리하지 못했어요.";
  }
  function checked(path, data) {
    if (!data || typeof data !== "object" || Array.isArray(data) ||
        (path === "/chat/questions" && (typeof data.answer !== "string" || !data.answer.trim() ||
          !Array.isArray(data.sources || []) || !Array.isArray(data.candidates || []) ||
          !(data.sources || []).every(function (s) { return s && typeof s === "object" && !Array.isArray(s); }) ||
          !(data.candidates || []).every(function (c) { return c && typeof c === "object" && !Array.isArray(c); })))) {
      throw new Error("서버 응답 형식을 확인하지 못했어요. 다시 시도해 주세요.");
    }
    return data;
  }
  // 11/8 진행률: 서버가 NDJSON(한 줄짜리 JSON 여러 개)으로 단계를 흘려보내면 줄마다 onStage, 마지막 {"done":true,...} 이 답
  function readStream(r, onStage) {
    var reader = r.body.getReader(), dec = new TextDecoder(), buf = "", final = null;
    function handle(text) {
      if (!text || !text.trim()) return;
      var obj;
      try { obj = JSON.parse(text); } catch (e) { return; }
      if (obj && obj.done === true) final = obj;
      else if (obj && typeof obj.stage === "string") { try { onStage(obj); } catch (e) { /* 진행 표시 실패는 답에 영향 없음 */ } }
    }
    function pump() {
      return reader.read().then(function (x) {
        if (x.done) { buf += dec.decode(); handle(buf); buf = ""; return final; }
        buf += dec.decode(x.value, { stream: true });
        var parts = buf.split("\n");
        buf = parts.pop();
        parts.forEach(handle);
        if (final) { try { reader.cancel(); } catch (e) { /* 이미 끝남 */ } return final; }
        return pump();
      });
    }
    return pump().then(function (data) {
      if (!data) throw new Error("서버 응답을 읽지 못했어요. 다시 시도해 주세요.");
      if (data.error) throw new Error(failMessage(data.status_code, data.detail));
      var out = {};
      Object.keys(data).forEach(function (k) { if (k !== "done") out[k] = data[k]; });
      return out;
    });
  }

  function api(path, body, controller, onStage) {
    var init = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
    // 단계 알림을 받을 수 있으면 스트림을 요청한다(서버가 모르면 그냥 한 번에 JSON 으로 옴)
    var canStream = !!onStage && typeof TextDecoder === "function";
    if (body && canStream) init.headers.Accept = "application/x-ndjson, application/json";
    controller = controller || new AbortController();
    init.signal = controller.signal;
    var timer = setTimeout(function () { controller.abort(); }, STAFF ? 60000 : 30000);   // 관제 분석은 모델을 두 번 불러 더 걸림
    return fetch(API + path, init).then(function (r) {
      var type = r.headers && typeof r.headers.get === "function" ? r.headers.get("content-type") || "" : "";
      if (canStream && r.ok && type.indexOf("application/x-ndjson") >= 0 && r.body && typeof r.body.getReader === "function") {
        return readStream(r, onStage).then(function (data) { return checked(path, data); });
      }
      return r.json().catch(function () { throw new Error("서버 응답을 읽지 못했어요. 다시 시도해 주세요."); }).then(function (data) {
        if (!r.ok) throw new Error(failMessage(r.status, data && data.detail));
        return checked(path, data);
      });
    }).catch(function (err) {
      if (controller.signal.aborted) throw new Error("응답 시간이 길어 요청을 멈췄어요. 잠시 후 다시 시도해 주세요.");
      if (err instanceof TypeError) throw new Error("서버에 연결하지 못했어요. 인터넷 연결이나 관제탑 상태를 확인해 주세요.");
      throw err;
    }).finally(function () { clearTimeout(timer); });
  }

  function badgeText(res) {
    if (res.agent === "intake" && res.intake && res.intake.kind === "cancel") {   // 11/10 대화로 찾기 요청 취소(접수 문구가 그대로 떠서 헷갈렸다)
      var cs = { intake_question: "찾기 요청 취소 · 본인 확인", intake_confirm: "취소 전 확인", intake_done: "찾기 요청 취소됨",
                 intake_cancelled: "취소 안 함", intake_failed: "취소 못 함", intake_uncertain: "취소 결과 확인 필요", intake_unavailable: "취소 창구 없음" };
      return cs[res.status] || "찾기 요청 취소";
    }
    if (res.agent === "intake") {      // 11/9 대화 접수
      var st = { intake_question: "접수 중 · 하나씩 여쭤봐요", intake_confirm: "접수 전 확인", intake_done: "접수 완료",
                 intake_cancelled: "접수 취소", intake_failed: "접수 못 함", intake_uncertain: "접수 결과 확인 필요", intake_unavailable: "접수 창구 없음" };
      return st[res.status] || "대화 접수";
    }
    if (res.agent === "ops") return res.ops_used_llm && res.ops_used_llm.length ? "관제 분석 · AI 보고" : "관제 분석 · 계산 보고";
    if (res.agent === "search" || res.agent === "both") return res.database_mode === "demo_sqlite" ? "가상 DB 시연" : "물건 검색 안내";
    if (res.generation_status === "off_topic") return "분실물 서비스 안내만 해요";   // 11/9 날씨·맛집 같은 서비스 밖 질문
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
        var confirming = res.status === "intake_confirm" && /^(접수할게요|네)$/.test(c);
        var proof = confirming && res.confirmation ? Object.assign({}, res.confirmation) : null;
        if (confirming && !proof) btn.disabled = true;
        btn.addEventListener("click", function () { if (!busy) send(c, null, null, proof); });
        row.append(btn);
      });
      m.append(row);
    }

    // 11/9 접수 번호 복사(정연우 검토): 접수 완료 답의 찾기·접수·대기 번호
    var ik = res.intake || {};
    var no = res.status === "intake_done" || res.status === "intake_status" ? (ik.claim_id || ik.wait_id || ik.item_id || "") : "";
    if (no && /^[A-Z]-\d{8}-\d{4}$/.test(no)) {
      var cp = el("button", "choice", no + " 복사");
      cp.type = "button";
      cp.addEventListener("click", function () {
        var ok = function () { cp.textContent = "복사했어요"; setTimeout(function () { cp.textContent = no + " 복사"; }, 2000); };
        try { navigator.clipboard.writeText(no).then(ok, function () { cp.textContent = no; }); } catch (e) { cp.textContent = no; }
      });
      var crow = el("div", "choices"); crow.append(cp); m.append(crow);
    }

    // 11/9 대화 접수: 본인 확인 — 이름·성별 숫자는 이 화면에서 가려서(홍*동 · ******-1******) 보내고 원래 값은 보내지 않는다
    if (res.form && res.form.kind === "identity") m.append(identityForm());

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

  // ── 11/8 진행률 ─────────────────────────────────────────────
  // 한줄 설명: "지금 몇 % 왔나"를 서버 단계(실제) + 최근 응답 시간(예상)으로 계산한다. 퍼센트는 절대 줄지 않고, 답이 오기 전에는 95%에서 멈춘다.
  // 시간 채우기: pct(t) = 95 × (1 − e^(−t/τ)). τ 는 p95 가 있으면 "p95 에 90%", 없으면 "p50(기본 3초)에 60%"가 되게 고른다.
  function progressModel(p50, p95) {
    var tau = p95 > 0 ? p95 / Math.log(19) : (p50 > 0 ? p50 : DEFAULT_EST_MS) / Math.log(95 / 35);
    var shown = 0, stagePct = 0, stageName = null, cap = 95, finished = false;
    return {
      stage: function (name, pct) {
        if (finished || typeof pct !== "number" || !(pct > stagePct)) return;
        stagePct = Math.min(95, pct);
        stageName = STAGE_TEXT[name] ? name : stageName;
        // 반드시 뒤따르는 단계가 있으면(답 쓰기 → 근거 확인) 그 값 바로 아래까지만 시간으로 채운다
        cap = STAGE_NEXT[name] ? Math.min(95, STAGE_PCT[STAGE_NEXT[name]] - 1) : 95;
      },
      at: function (ms) {
        if (finished) return 100;
        var t = 95 * (1 - Math.exp(-Math.max(0, ms || 0) / tau));
        var v = Math.max(stagePct, Math.min(cap, t));
        shown = Math.max(shown, Math.min(95, Math.floor(v)));
        return shown;
      },
      done: function () { finished = true; shown = 100; return 100; },
      stageText: function () { return stageName ? STAGE_TEXT[stageName] : ""; },
      value: function () { return shown; }
    };
  }
  function now() { return (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now(); }
  function median(a) { var b = a.slice().sort(function (x, y) { return x - y; }); return b.length ? b[Math.floor(b.length / 2)] : null; }
  function estimate() {
    // 이 화면에서 직접 잰 최근 응답 시간이 있으면 그것, 없으면 /chat/metrics 의 p50·p95, 그것도 없으면 3초
    if (durations.length) return { p50: median(durations), p95: Math.max(Math.max.apply(null, durations), metricsP95 || 0) || null };
    return { p50: metricsP50 || DEFAULT_EST_MS, p95: metricsP95 || null };
  }
  // 답 말풍선 자리(pending)에 막대를 붙인다. 0.3초 안에 끝나면 아예 그리지 않는다(규칙 답은 깜박임 없이)
  function progressFor(pending) {
    var est = estimate(), model = progressModel(est.p50, est.p95), t0 = now();
    var box = null, fill = null, txt = null, showTimer = null, tickTimer = null, stopped = false;
    var verb = STAFF ? "분석 중" : "답 준비 중";
    // 11/9 사용자 요청: 0~100% 의 모든 자연수가 눈에 보이게 — 화면 숫자(disp)는 계산값(target)을 1%씩 따라간다.
    // 차이가 크면 빠르게(최소 16ms 에 1), 작으면 천천히(최대 60ms 에 1). 예) 이미 20% 단계면 0→20 을 빠르게 센다
    var disp = 0, stepTimer = null, onFull = null, finishing = false;
    function stepDelay(gap) { return Math.max(16, Math.min(60, Math.round(700 / Math.max(1, gap)))); }
    function show(v) {
      var stage = model.stageText();
      var head = v >= 100 ? (STAFF ? "분석 완료" : "답 완료") : finishing ? "마무리 중" : verb;   // 답이 온 뒤 100 까지 세는 동안은 '마무리 중'
      var label = head + " " + v + "%" + (v < 100 && stage && !finishing ? " · " + stage : "");
      if (box) {
        fill.style.width = v + "%";
        txt.textContent = label;
        box.setAttribute("aria-valuenow", String(v));
        box.setAttribute("aria-valuetext", label + (v < 100 ? " (예상)" : ""));
      }
      if (minimized && pillText) pillText.textContent = verb + " " + v + "%";
    }
    function chase(target) {                    // disp 를 target 까지 1씩 올린다(내려가지 않음)
      clearTimeout(stepTimer);
      if (disp >= target) { if (disp >= 100 && onFull) { var f = onFull; onFull = null; f(); } return; }
      disp += 1; show(disp);
      stepTimer = setTimeout(function () { chase(Math.max(target, model.value())); }, stepDelay(target - disp));
    }
    function render() {
      var v = model.at(now() - t0);
      if (v > disp && !stepTimer) chase(v);
      else if (v > disp) { clearTimeout(stepTimer); chase(v); }
    }
    function tick() { if (stopped) return; render(); tickTimer = setTimeout(tick, 150); }
    showTimer = setTimeout(function () {
      if (stopped) return;
      box = el("div", "prog");
      box.setAttribute("role", "progressbar");
      box.setAttribute("aria-label", "답변 준비 진행률(예상)");
      box.setAttribute("aria-valuemin", "0");
      box.setAttribute("aria-valuemax", "100");
      var track = el("div", "track");
      fill = el("div", "fill");
      track.append(fill);
      var row = el("div", "ptxt");
      txt = el("b");
      row.append(txt, el("span", "est", "예상"));
      box.append(track, row);
      var bubble = pending.querySelector(".bubble");
      if (bubble) { bubble.textContent = ""; bubble.append(box); } else pending.append(box);
      tick();
    }, SHOW_AFTER_MS);
    return {
      stage: function (name, pct) { model.stage(name, pct); if (box) render(); },
      stop: function () { stopped = true; clearTimeout(showTimer); clearTimeout(tickTimer); if (!finishing) clearTimeout(stepTimer); },   // 답 뒤 100 까지 세는 중이면 그대로
      // 11/10 답이 오면: 지금 숫자에서 100 까지 빠르게(최대 0.45초) 채운 **뒤에** 답을 보여 준다(cb).
      // 전에는 답을 먼저 보이고 막대가 답 아래에서 100 까지 따라가, "100% 가 되기 전에 답이 나온다"로 보였다.
      // 막대를 아직 그리지 않았으면(0.3초 안에 온 답) 기다리지 않고 바로 cb
      complete: function (cb) {
        stopped = true; finishing = true; clearTimeout(showTimer); clearTimeout(tickTimer); clearTimeout(stepTimer);
        model.done();
        if (!box) { cb(); return; }
        var from = disp, began = now(), dur = Math.min(450, Math.max(120, (100 - from) * 6));
        (function run() {
          var k = Math.min(1, (now() - began) / dur), v = Math.max(disp, Math.round(from + (100 - from) * k));
          if (v !== disp) { disp = v; show(v); }
          if (k < 1) stepTimer = setTimeout(run, 16);
          else { disp = 100; show(100); stepTimer = setTimeout(cb, 180); }      // '답 완료 100%' 를 잠깐 보인 뒤 답
        })();
      },
      shown: function () { return disp; },
      model: model
    };
  }

  function setBusy(v) {
    busy = v;
    sendBtn.disabled = v;
    input.setAttribute("aria-busy", String(v));
  }

  function maskName(n) {
    n = String(n || "").trim();
    if (!n) return "";
    if (n.length === 1) return n + "*";
    if (n.length === 2) return n[0] + "*";
    return n[0] + new Array(n.length - 1).join("*") + n[n.length - 1];
  }

  function identityForm() {
    var f = el("form", "idform");
    var l1 = el("label", null, "이름");
    var nm = el("input"); nm.type = "text"; nm.maxLength = 10; nm.autocomplete = "off"; nm.placeholder = "예: 홍길동";
    l1.append(nm);
    var l2 = el("label", null, "주민등록번호 뒷자리 첫 숫자");
    var g = el("select");
    ["", "1", "2", "3", "4"].forEach(function (v) { var o = el("option", null, v ? v : "고르세요"); o.value = v; g.append(o); });
    l2.append(g);
    var note = el("div", "note", "보내기 전에 이 화면에서 가려요: 홍*동 · ******-1******");
    var go = el("button", null, "가려서 보내기");
    go.type = "submit"; go.disabled = true;
    function ok() { return nm.value.trim().length >= 1 && !/[0-9*\s]/.test(nm.value.trim()) && /^[1-4]$/.test(g.value); }
    function upd() {
      go.disabled = !ok();
      note.textContent = ok() ? "보낼 값: " + maskName(nm.value) + " · ******-" + g.value + "******" : "보내기 전에 이 화면에서 가려요: 홍*동 · ******-1******";
    }
    nm.addEventListener("input", upd); g.addEventListener("change", upd);
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!ok() || busy) return;
      var action = { type: "identity", name_masked: maskName(nm.value), id_no_masked: "******-" + g.value + "******" };
      nm.value = ""; nm.disabled = true; g.disabled = true; go.disabled = true;     // 원래 이름은 화면에도 남기지 않음
      send("본인 확인 정보를 입력했어요", null, null, action);
    });
    f.append(l1, l2, note, go);
    return f;
  }

  function send(text, suggestionId, retryHistory, intakeAction) {
    var q = (text || "").trim();
    if (busy || !q) return;
    if (q.length > MAX_LEN) { statusEl.textContent = "질문을 500자 이하로 줄여 주세요. 입력한 내용은 그대로 남겨 뒀어요."; return; }
    var welcome = root.querySelector(".welcome");
    if (welcome) welcome.remove();
    var userLine = line("user", q);
    if (input.value.trim() === q) input.value = "";
    input.dispatchEvent(new Event("input"));
    // 11/10 이 화면이 다른 화면 안(통합 시연 화면의 키오스크·휴대폰 틀)에 들어 있으면 "질문을 보냈다"고 알린다 →
    // 바깥 화면이 챗봇 에이전트 그림으로 곧바로 바꾸고 단계를 더 자주 읽는다. 질문 내용은 보내지 않는다
    try { if (window.top !== window) window.top.postMessage({ source: "lostfound-chat", phase: "ask" }, location.origin); } catch (e) {}
    var pending = line("bot pending", "질문을 확인하고 있어요…");
    var progress = progressFor(pending), started = now();
    setBusy(true);
    statusEl.textContent = "답변 준비 중";
    var body = { question: q, history: (retryHistory || history).slice(-MAX_HISTORY) };
    if (suggestionId) body.suggestion_id = suggestionId;
    if (intakeAction) body.intake_action = intakeAction;
    body.session_id = getSessionId();
    if (STAFF) body.mode = "staff";
    var request = { controller: new AbortController(), version: conversationVersion, progress: progress };
    activeRequest = request;
    api("/chat/questions", body, request.controller, function (ev) {
      if (activeRequest === request) progress.stage(ev.stage, ev.pct);
    }).then(function (res) {
      if (activeRequest !== request) return;
      durations = durations.concat([Math.max(1, now() - started)]).slice(-5);
      return new Promise(function (resolve) { progress.complete(resolve); }).then(function () { return res; });
    }).then(function (res) {
      if (!res || activeRequest !== request) return;       // 막대를 채우는 사이 대화를 지웠으면 답을 붙이지 않는다
      var answerText = res.answer || "답변을 만들지 못했어요. 질문을 조금 바꿔 다시 물어봐 주세요.";
      history = body.history.concat([{ q: q, a: String(res.answer || "").slice(0, MAX_ANSWER) }]).slice(-MAX_HISTORY);
      pending.remove();
      var m = line("bot", answerText);
      if (minimized) { pill.className = "pill unread"; pillText.textContent = "새 답변이 왔어요"; pill.setAttribute("aria-label", "새 답변이 왔어요 — " + TITLE + " 펼치기"); }
      var saved = storeGet() || { history: [], msgs: [] };
      saved.history = history;
      saved.sid = getSessionId();
      saved.msgs = saved.msgs.concat([{ r: "user", t: q }, { r: "bot", t: answerText }]).slice(-MAX_MESSAGES);
      storeSet(saved);
      addExtras(m, res);
      statusEl.textContent = res.status === "intake_uncertain" ? "처리 결과 확인 필요 · 같은 요청을 다시 보내지 마세요" : res.agent === "intake" && res.intake && res.intake.kind === "cancel"
        ? (res.status === "intake_done" ? "찾기 요청 취소됨 · 물건은 계속 보관돼요" : "찾기 요청 취소 중 · '아니요'로 그만둘 수 있어요") :
        res.agent === "intake" ? (res.status === "intake_done" ? "접수 완료 · 번호를 꼭 적어 두세요" : "접수 중 · '취소'로 언제든 멈출 수 있어요") :
        res.agent === "ops" ? "관제 기록 기준 · 직원 전용" :
        res.agent === "search" || res.agent === "both" ? "후보는 본인 물건 확정이 아니에요" : "안내 완료 · 근거를 펼쳐 볼 수 있어요";
      scroll();
    }).catch(function (err) {
      if (activeRequest !== request) return;
      progress.stop();
      pending.remove();
      var m = line("bot error", err.message);
      if (minimized) { pill.className = "pill unread"; pillText.textContent = "답을 받지 못했어요"; }
      var retry = el("button", "retry", "다시 보내기");
      retry.type = "button";
      retry.addEventListener("click", function () { if (busy || request.version !== conversationVersion) return; m.remove(); userLine.remove(); send(q, suggestionId, body.history, intakeAction); });
      m.append(retry);
      statusEl.textContent = "전송하지 못했어요";
    }).finally(function () {
      progress.stop();
      if (activeRequest !== request) return;
      activeRequest = null;
      setBusy(false);
      touchIdle();   // 답을 읽는 시간부터 다시 잰다
      if (!panel.hidden && !minimized && (document.activeElement === host || document.activeElement === input)) input.focus();
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
    if (previous) { previous.controller.abort(); if (previous.progress) previous.progress.stop(); }
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

  // 진행률 예상 시간: 관제탑이 잰 최근 응답 시간(p50·p95). 못 읽으면 기본 3초
  function loadMetrics() {
    api("/chat/metrics").then(function (m) {
      var q = m && m.requests && m.requests.question;
      if (q && typeof q.p50_ms === "number" && q.p50_ms > 0) metricsP50 = q.p50_ms;
      if (q && typeof q.p95_ms === "number" && q.p95_ms > 0) metricsP95 = q.p95_ms;
    }).catch(function () { /* 예상 시간만 기본값 */ });
  }

  function loadStatus() {
    if (statusLoading) return;
    statusLoading = true;
    api("/chat/health").then(function (h) {
      if (!h.ready) { loadedOnce = false; modeEl.textContent = "준비 중 — 관제탑 확인 필요"; dotEl.className = "dot off"; return; }
      dotEl.className = "dot";
      modeEl.textContent = STAFF ? (h.staff_ops ? "이용 안내 + 관제 분석(직원)" : "이용 안내 — 관제 분석은 관제탑에서만") : h.search_mode === "demo_sqlite" ? "이용 안내 + 가상 물건 검색" : h.search_mode === "postgres" ? "이용 안내 + 본인인증 후 물건 검색" : "이용 안내";
      loadMetrics();
      return api("/chat/suggestions").then(function (s) { suggestions = (s && s.items) || []; renderChips(); });
    }).catch(function () { loadedOnce = false; modeEl.textContent = "연결 확인 필요"; dotEl.className = "dot off"; })
      .finally(function () { statusLoading = false; });
  }

  // ── 11/8 작은 떠 있는 창 ─────────────────────────────────────
  // 한줄 설명: 창 자리를 "어느 구석에 붙어 있고(ax·ay), 그 구석에서 얼마나 떨어졌는지(dx·dy), 크기(w·h)"로 기억한다.
  // 화면 크기가 바뀌어도 같은 구석 기준으로 다시 놓고, 언제나 화면 안쪽으로 끌어 넣는다.
  function vp() { return { w: window.innerWidth || 1024, h: window.innerHeight || 768 }; }
  function isPhone() { return vp().w <= PHONE_MAX; }
  function gap() { return isPhone() ? Math.max(6, Math.floor(vp().w * 0.04)) : 16; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function sizeFor(name) {
    var v = vp();
    // 11/10: 좁은 키오스크 화면(통합 시연 화면의 키오스크 틀 460px)은 창이 촬영 영상·단추를 다 가리지 않게 절반까지만
    if (isPhone()) return [Math.round(v.w * 0.92), Math.round(v.h * (KIOSK ? (name === "large" ? 0.78 : 0.5) : (name === "large" ? 0.85 : 0.6)))];
    return SIZES[name] || SIZES.small;
  }
  function winKey() { return WIN_KEY + (isPhone() ? ":phone" : ""); }
  // 창 설정 한 칸(winKey): 창 자리·크기 + 11/9 창 밝기(theme). 대화·질문은 넣지 않는다
  function readStore() {
    try {
      if (typeof localStorage === "undefined") return null;
      var v = JSON.parse(localStorage.getItem(winKey()) || "null");
      return v && typeof v === "object" && !Array.isArray(v) ? v : null;
    } catch (e) { return null; }
  }
  function loadTheme() {
    var v = readStore();
    return v && (v.theme === "light" || v.theme === "dark") ? v.theme : null;
  }
  function writeStore() {
    var o = {};
    if (!KIOSK && win && win.saved) { o.ax = win.ax; o.ay = win.ay; o.dx = Math.round(win.dx); o.dy = Math.round(win.dy); o.w = Math.round(win.w); o.h = Math.round(win.h); o.size = win.size; }
    if (userTheme) o.theme = userTheme;
    try {
      if (typeof localStorage === "undefined") return;
      if (Object.keys(o).length) localStorage.setItem(winKey(), JSON.stringify(o));
      else localStorage.removeItem(winKey());
    } catch (e) { /* 저장 못 해도 창은 그대로 동작 */ }
  }
  function loadWin() {
    if (KIOSK) return null;      // 11/10 공용 기기: 앞사람이 키우거나 옮긴 창을 다음 사람에게 남기지 않음(열 때마다 기본 자리·작게)
    try {
      var v = readStore();
      if (v && (v.ax === "l" || v.ax === "r") && (v.ay === "t" || v.ay === "b") &&
          [v.dx, v.dy, v.w, v.h].every(function (n) { return typeof n === "number" && isFinite(n) && n >= 0 && n < 10000; })) {
        return { ax: v.ax, ay: v.ay, dx: v.dx, dy: v.dy, w: v.w, h: v.h, size: v.size === "large" ? "large" : v.size === "custom" ? "custom" : "small", saved: true };
      }
    } catch (e) { /* 읽지 못하면 기본 자리 */ }
    return null;
  }
  function saveWin() {
    if (!win) return;
    win.saved = true;
    writeStore();
  }
  // 창 크기·자리를 화면 안으로(가장자리 여백 gap)
  function clampRect(r) {
    var v = vp(), m = gap();
    var w = clamp(r.w, Math.min(MIN_W, v.w - 2 * m), v.w - 2 * m);
    var h = clamp(r.h, Math.min(isPhone() ? 300 : MIN_H, v.h - 2 * m), v.h - 2 * m);
    return { x: clamp(r.x, m, v.w - w - m), y: clamp(r.y, m, v.h - h - m), w: w, h: h };
  }
  function rectFromWin(w0) {
    var v = vp();
    var w = Math.min(w0.w, v.w), h = Math.min(w0.h, v.h);
    return clampRect({ x: w0.ax === "r" ? v.w - w0.dx - w : w0.dx, y: w0.ay === "b" ? v.h - w0.dy - h : w0.dy, w: w, h: h });
  }
  function winFromRect(r, size) {
    var v = vp();
    var ax = r.x + r.w / 2 > v.w / 2 + 1 ? "r" : "l", ay = r.y + r.h / 2 > v.h / 2 ? "b" : "t";
    return { ax: ax, ay: ay, dx: ax === "r" ? v.w - r.x - r.w : r.x, dy: ay === "b" ? v.h - r.y - r.h : r.y, w: r.w, h: r.h, size: size };
  }
  // 처음 열 때(기억한 자리가 없을 때): 창 아래에 놓일 버튼·입력칸이 가장 적은 구석을 고른다
  var BUSY_SEL = "button,a[href],input:not([type=hidden]),select,textarea,[role=button],[contenteditable=true]";
  function busyScore(r) {
    if (typeof document.querySelectorAll !== "function") return 0;
    var list, n = 0;
    try { list = document.querySelectorAll(BUSY_SEL); } catch (e) { return 0; }
    for (var i = 0; i < list.length && i < 600; i++) {
      var e = list[i];
      if (e === host || !e.getBoundingClientRect) continue;
      var b = e.getBoundingClientRect();
      if (!b.width || !b.height) continue;
      var ox = Math.min(b.right, r.x + r.w) - Math.max(b.left, r.x), oy = Math.min(b.bottom, r.y + r.h) - Math.max(b.top, r.y);
      if (ox > 0 && oy > 0) n += 1 + (ox * oy) / (b.width * b.height);   // 가려지는 요소 수 + 가려지는 비율
    }
    // 11/8: 제목·글도 약하게 센다(버튼이 적은 구석이 페이지 제목 위로 골라지던 것)
    var texts;
    try { texts = document.querySelectorAll("h1,h2,h3,p,label,li,td"); } catch (e2) { texts = []; }
    for (var k = 0; k < texts.length && k < 600; k++) {
      var t = texts[k];
      if (!t.getBoundingClientRect || (host && host.contains && host.contains(t))) continue;
      var tb = t.getBoundingClientRect();
      if (!tb.width || !tb.height) continue;
      var tx = Math.min(tb.right, r.x + r.w) - Math.max(tb.left, r.x), ty = Math.min(tb.bottom, r.y + r.h) - Math.max(tb.top, r.y);
      if (tx > 0 && ty > 0) n += (/^H\d$/.test(t.tagName) ? 1.2 : 0.3) * (tx * ty) / (tb.width * tb.height);
    }
    return n;
  }
  function pickWin() {
    var sz = sizeFor("small"), m = gap(), best = null;
    var corners = isPhone() ? [["l", "b"], ["l", "t"]] : [["r", "b"], ["l", "b"], ["r", "t"], ["l", "t"]];   // 같으면 앞쪽(오른쪽 아래) 우선
    corners.forEach(function (c) {
      var w0 = { ax: c[0], ay: c[1], dx: m, dy: m, w: sz[0], h: sz[1], size: "small", saved: false };
      var score = busyScore(rectFromWin(w0));
      if (!best || score < best.score - 0.01) best = { score: score, win: w0 };
    });
    return best.win;
  }
  function placeGrip() {
    if (!grip || !win) return;
    // 손잡이는 붙은 구석의 반대쪽(화면 가운데 쪽) 구석: 오른쪽 아래 창이면 왼쪽 위를 끌어 키운다
    grip.className = "grip " + (win.ay === "b" ? "t" : "b") + (win.ax === "r" ? "l" : "r");
  }
  function placePill() {
    if (!pill || !cur || !win) return;
    var v = vp(), s = pill.style;
    if (win.ax === "r") { s.right = Math.max(8, v.w - cur.x - cur.w) + "px"; s.left = "auto"; } else { s.left = Math.max(8, cur.x) + "px"; s.right = "auto"; }
    if (win.ay === "b") { s.bottom = Math.max(8, v.h - cur.y - cur.h) + "px"; s.top = "auto"; } else { s.top = Math.max(8, cur.y) + "px"; s.bottom = "auto"; }
  }
  function applyRect(r) {
    cur = r;
    var s = panel.style;
    s.left = r.x + "px"; s.top = r.y + "px"; s.width = r.w + "px"; s.height = r.h + "px";
    placeGrip();
    placePill();
  }
  function updateSizeBtn() {
    if (!sizeBtn || !win) return;
    var big = win.size === "large";
    sizeBtn.innerHTML = big ? SVG_SMALL : SVG_BIG;
    sizeBtn.setAttribute("aria-label", big ? "창 작게" : "창 크게");
    sizeBtn.title = big ? "작게" : "크게";
  }
  function placeWindow() {
    winPhone = isPhone();
    win = loadWin() || pickWin();
    userTheme = loadTheme();      // 휴대폰 폭 ↔ 넓은 화면은 칸이 따로라 그 칸의 밝기로
    syncTheme();
    applyRect(rectFromWin(win));
    updateSizeBtn();
  }
  function toggleSize() {
    if (!win) return;
    var name = win.size === "large" ? "small" : "large", sz = sizeFor(name);
    // 붙은 구석은 그대로 두고 크기만 바꾼다(오른쪽 아래 창은 왼쪽 위로 커짐)
    var next = { ax: win.ax, ay: win.ay, dx: win.dx, dy: win.dy, w: sz[0], h: sz[1], size: name };
    applyRect(rectFromWin(next));
    win = winFromRect(cur, name);
    saveWin();
    updateSizeBtn();
  }
  // 끌기(옮기기·크기 바꾸기): 마우스·터치·펜 모두 pointer 이벤트 하나로
  function startDrag(e, kind) {
    if (!cur) return;
    var target = e.currentTarget || (kind === "move" ? header : grip);
    var sx = e.clientX, sy = e.clientY, r0 = { x: cur.x, y: cur.y, w: cur.w, h: cur.h }, corner = grip.className.replace("grip ", "");
    if (e.cancelable) e.preventDefault();
    try { target.setPointerCapture(e.pointerId); } catch (err) { /* 오래된 브라우저 */ }
    wrap.classList.add(kind === "move" ? "dragging" : "resizing");
    function move(ev) {
      var dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (kind === "move") { applyRect(clampRect({ x: r0.x + dx, y: r0.y + dy, w: r0.w, h: r0.h })); return; }
      var v = vp(), m = gap(), left = corner.charAt(1) === "l", top = corner.charAt(0) === "t";
      var maxW = left ? r0.x + r0.w - m : v.w - m - r0.x, maxH = top ? r0.y + r0.h - m : v.h - m - r0.y;
      var w = clamp(r0.w + (left ? -dx : dx), Math.min(MIN_W, maxW), maxW);
      var h = clamp(r0.h + (top ? -dy : dy), Math.min(MIN_H, maxH), maxH);
      applyRect({ x: left ? r0.x + r0.w - w : r0.x, y: top ? r0.y + r0.h - h : r0.y, w: w, h: h });
    }
    function end() {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", end);
      target.removeEventListener("pointercancel", end);
      wrap.classList.remove("dragging");
      wrap.classList.remove("resizing");
      var moved = cur.x !== r0.x || cur.y !== r0.y || cur.w !== r0.w || cur.h !== r0.h;
      if (!moved) return;
      win = winFromRect(cur, kind === "resize" ? "custom" : win.size);
      saveWin();
      placeGrip();
      placePill();
      updateSizeBtn();
    }
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", end);
    target.addEventListener("pointercancel", end);
  }
  function onResize() {
    updateSpacer();
    if (!panel || panel.hidden || !win) return;
    if (winPhone !== isPhone()) { placeWindow(); return; }   // 휴대폰 폭 ↔ 넓은 화면을 넘나들면 그 폭의 기억 자리로
    if (!win.saved && win.size === "small") { var sz = sizeFor("small"); win.w = sz[0]; win.h = sz[1]; }
    applyRect(rectFromWin(win));
  }
  function minimize() {
    if (!panel || panel.hidden || minimized) return;
    minimized = true;
    wrap.classList.add("min");
    pill.className = "pill";
    pillText.textContent = busy ? (STAFF ? "분석 중" : "답 준비 중") : TITLE;
    pill.setAttribute("aria-label", TITLE + " 펼치기");
    placePill();
    pill.focus();
  }
  function restore() {
    if (!minimized) return;
    minimized = false;
    wrap.classList.remove("min");
    pill.className = "pill";
    pillText.textContent = TITLE;
    if (win) applyRect(rectFromWin(win));
    scroll();
    setTimeout(function () { if (!panel.hidden && !minimized) input.focus(); }, 0);
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
    if (typeof window.addEventListener === "function") {
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", onResize);
    }
  }

  function openPanel() {
    if (!panel) build();
    if (!panel.hidden) return;
    lastFocus = document.activeElement;
    panel.hidden = false;
    wrap.classList.add("open"); // 창이 열리면 동그란 버튼은 숨긴다(창의 ✕·Esc 로 닫음)
    placeWindow();
    launcher.setAttribute("aria-expanded", "true");
    if (!loadedOnce) { loadedOnce = true; loadStatus(); }
    touchIdle();
    setTimeout(function () { if (!panel.hidden) input.focus(); }, 0);
  }

  function closePanel() {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    wrap.classList.remove("open");
    if (minimized) { minimized = false; wrap.classList.remove("min"); pill.className = "pill"; pillText.textContent = TITLE; }
    launcher.setAttribute("aria-expanded", "false");
    if (KIOSK) { clearTimeout(idleTimer); if (log && log.querySelector(".msg")) resetChat(true); }  // 공용 기기는 닫으면 바로 지움
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
  }

  // 여는 버튼(data-chatbot-open)·동그란 단추: 닫혀 있으면 열고, 접혀 있으면 펼치고, 펼쳐져 있으면 닫는다
  function toggle() { if (!panel || panel.hidden) openPanel(); else if (minimized) restore(); else closePanel(); }

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

  function openOrRestore() { if (panel && !panel.hidden && minimized) restore(); else openPanel(); }
  // progressModel 은 시험(tests/test_chat_widget_window.cjs)이 진행률 계산만 따로 확인하려고 내보낸다
  window.LostFoundChat = { open: openOrRestore, close: closePanel, toggle: toggle, minimize: function () { minimize(); }, progressModel: progressModel };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
