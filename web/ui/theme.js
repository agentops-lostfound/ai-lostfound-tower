/* 라이트·다크 전환(11/8 변재원). 화면 <head> 에 <script src="/ui/theme.js"></script> 한 줄(깜박임 없게 head 에서 바로 실행)
   한줄 설명: 처음엔 휴대폰·PC 의 밝기 설정(OS)을 따르고, 버튼을 누르면 그 선택을 이 브라우저에 기억한다.
   - 선택은 <html data-theme="light|dark"> 로 표시 → theme.css 토큰이 바뀜
   - 같은 주소의 다른 창·관리자 화면 안쪽 화면(iframe)도 storage 이벤트로 함께 바뀜
   - 버튼 자리: 화면에 [data-theme-slot] 요소가 있으면 그 안, 없으면 왼쪽 아래 둥근 버튼
   - 버튼을 숨기려면 <html data-theme-toggle="off"> (예: 관리자 화면 안쪽 iframe — 바깥 버튼 하나로 바꿈) */
(function () {
  var KEY = 'lf-theme';
  var root = document.documentElement;
  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function apply(v) { if (v === 'light' || v === 'dark') root.setAttribute('data-theme', v); else root.removeAttribute('data-theme'); }
  function current() {
    var v = root.getAttribute('data-theme');
    if (v) return v;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  apply(saved());
  if (window.self !== window.top) root.setAttribute('data-theme-toggle', root.getAttribute('data-theme-toggle') || 'off');

  var SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>';
  var btn = null;
  function paint() {
    if (!btn) return;
    var dark = current() === 'dark';
    btn.innerHTML = dark ? SUN : MOON;
    btn.setAttribute('aria-label', dark ? '밝은 화면으로 바꾸기' : '어두운 화면으로 바꾸기');
    btn.title = btn.getAttribute('aria-label');
  }
  function toggle() {
    var next = current() === 'dark' ? 'light' : 'dark';
    apply(next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
    paint();
  }
  window.lfTheme = { toggle: toggle, current: current };
  window.addEventListener('storage', function (e) { if (e.key === KEY) { apply(e.newValue); paint(); } });
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    var onChange = function () { paint(); };
    if (mq.addEventListener) mq.addEventListener('change', onChange); else if (mq.addListener) mq.addListener(onChange);
  }
  function mount() {
    if (root.getAttribute('data-theme-toggle') === 'off' || btn) return;
    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ui-theme-toggle';
    btn.addEventListener('click', toggle);
    var slot = document.querySelector('[data-theme-slot]');
    if (slot) slot.appendChild(btn); else { btn.classList.add('floating'); document.body.appendChild(btn); }
    paint();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();

/* "아래에 더 있음" 표시(11/8). 안쪽에서 스크롤되는 상자에 data-scroll-hint 를 붙이면,
   내용이 넘칠 때만 아래쪽이 흐려지고 "아래에 더 있음 ↓" 단추가 뜬다(누르면 한 화면 내려감). 끝까지 내리면 사라진다.
   상자 크기·내용이 바뀌어도 다시 계산한다(ResizeObserver·MutationObserver). 페이지 전체 스크롤에는 쓰지 않는다 */
(function () {
  var seen = typeof WeakSet === 'function' ? new WeakSet() : null;
  function attach(box) {
    if (!seen || seen.has(box)) return;
    seen.add(box);
    var label = box.getAttribute('data-scroll-hint') || '아래에 더 있음';
    var hint = document.createElement('button');
    hint.type = 'button';
    hint.className = 'ui-scroll-hint';
    hint.setAttribute('aria-label', label + ' — 아래로 내리기');
    hint.innerHTML = '<span>' + label + '</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
    hint.hidden = true;
    hint.addEventListener('click', function () { box.scrollBy({ top: Math.max(120, box.clientHeight * 0.8), behavior: 'smooth' }); });
    var host = box.parentElement;
    if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
    host.appendChild(hint);
    // 11/8 무작위 시험: 단추가 상자 안 마지막 입력칸·단추를 덮어 바로 누를 수 없었다 →
    // ① 상자 아래 테두리에 반쯤 걸치게 두고 ② 사용자가 한 번 내려 보면 숨긴다(내용이 새로 바뀌면 다시)
    var seenScroll = false;
    function update() {
      var visible = box.offsetParent !== null;
      var more = visible && box.scrollHeight - box.clientHeight - box.scrollTop > 16;
      box.classList.toggle('ui-has-more', more);
      hint.hidden = !more || seenScroll;
      if (!hint.hidden) {
        hint.style.top = (box.offsetTop + box.clientHeight - (hint.offsetHeight || 40) / 2) + 'px';
        hint.style.left = (box.offsetLeft + box.clientWidth / 2) + 'px';
      }
    }
    box.addEventListener('scroll', function () { if (box.scrollTop > 24) seenScroll = true; update(); }, { passive: true });
    box.addEventListener('focusin', function (e) { if (e.target !== box) { seenScroll = true; update(); } });
    window.addEventListener('resize', update);
    if (window.ResizeObserver) new ResizeObserver(update).observe(box);
    if (window.MutationObserver) new MutationObserver(function (list) {
      if (list.some(function (m) { return m.type === 'childList' && m.target === box; })) seenScroll = false;   // 내용이 새로 바뀜
      setTimeout(update, 0);
    }).observe(box, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'style'] });
    var section = box.closest('section') || box;      // 키오스크처럼 같은 상자를 다른 단계로 다시 보여 줄 때 다시 띄움
    if (window.MutationObserver) new MutationObserver(function () { if (!section.classList.contains('on')) seenScroll = false; setTimeout(update, 0); })
      .observe(section, { attributes: true, attributeFilter: ['class'] });
    setTimeout(update, 50);
  }
  function scan() { document.querySelectorAll('[data-scroll-hint]').forEach(attach); }
  window.lfScrollHint = { scan: scan };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan); else scan();
  if (window.MutationObserver) {
    var start = function () { new MutationObserver(scan).observe(document.body, { childList: true, subtree: true }); };
    if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
  }
})();
