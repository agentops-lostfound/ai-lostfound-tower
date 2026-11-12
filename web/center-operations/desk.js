(() => {
  'use strict';
  const root = '/api/admin/center', $ = id => document.getElementById(id);
  let board = null, busy = false, pending = null;
  // An uncertain pickup keeps its exact retry key across reloads. No personal data.
  const storageKey = 'lf-center-pending-v1';
  try { pending = JSON.parse(sessionStorage.getItem(storageKey) || 'null'); } catch (_) {}
  function text(tag, value) { const e = document.createElement(tag); e.textContent = String(value); return e; }
  function message(value) { $('message').textContent = value; }
  function remember(value) {
    pending = value;
    try { if (value) sessionStorage.setItem(storageKey, JSON.stringify(value)); else sessionStorage.removeItem(storageKey); } catch (_) {}
    $('retry').hidden = !value;
    $('pending').textContent = value ? '회수 결과 확인 중입니다. 새 요청을 만들지 말고 같은 요청으로 확인하세요.' : '';
  }
  async function api(path, body) {
    const options = {cache: 'no-store', credentials: 'same-origin'};
    if (body !== undefined) Object.assign(options, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const r = await fetch(root + path, options);
    let d; try { d = await r.json(); } catch (_) { throw Error('서버 응답을 확인하지 못했습니다.'); }
    if (!r.ok) { const error = Error(typeof d.detail === 'string' ? d.detail : '요청을 처리하지 못했습니다. 기록을 새로 확인하세요.'); error.status = r.status; throw error; }
    return d;
  }
  function controls() {
    document.querySelectorAll('button,input,select').forEach(e => { e.disabled = busy || !board; });
    $('refresh').disabled = busy; $('readiness').disabled = busy;
    $('pickup').disabled = busy || !!pending || !$('items').querySelector('input:checked');
    $('machine').disabled = busy || !!pending || !board;
    $('retry').disabled = busy || !pending;
  }
  function renderItems() {
    $('items').replaceChildren();
    for (const item of board.items.filter(i => i.machine_id === $('machine').value && i.status === '등록기계 보관')) {
      const label = text('label', ''); const box = document.createElement('input'); box.type = 'checkbox'; box.value = item.item_id;
      box.onchange = controls; label.append(box, document.createTextNode(` ${item.item_id} · ${item.category}`)); $('items').append(label);
    }
    if (!$('items').children.length) $('items').append(text('p', '표시 범위 안에 회수 대기 물건이 없습니다.'));
    controls();
  }
  function renderBatch(batch, target) {
    const section = document.createElement('section'); section.append(text('h3', `회수 ${batch.collection_id} · ${batch.machine_id}`));
    const boxes = [];
    for (const item of batch.items) {
      const label = text('label', '');
      if (!item.arrived) { const box = document.createElement('input'); box.type = 'checkbox'; box.value = item.item_id; boxes.push(box); label.append(box); }
      label.append(document.createTextNode(` ${item.item_id} · ${item.arrived ? '도착 확인됨' : '도착 전'}`)); section.append(label);
    }
    if (!batch.arrived_at) {
      const save = text('button', '체크한 물건 도착 기록'); save.type = 'button';
      save.onclick = () => action(async () => {
        await api(`/collections/${batch.collection_id}/arrivals`, {item_ids: boxes.filter(b => b.checked).map(b => b.value)});
        message('도착 기록을 저장했습니다.'); await load();
        if (target === $('lookupResult')) { target.replaceChildren(); renderBatch(await api(`/collections/${batch.collection_id}`), target); }
      }); section.append(save);
    } else section.append(text('p', '전체 도착 완료'));
    target.append(section);
  }
  async function load() {
    // Hide stale state before requesting a fresh snapshot.
    board = null; $('items').replaceChildren(); $('batches').replaceChildren(); $('alerts').replaceChildren(); $('answer').textContent = ''; $('lookupResult').replaceChildren(); controls();
    board = await api('/dashboard');
    const selected = $('machine').value; $('machine').replaceChildren();
    for (const m of board.machines) { const option = text('option', `${m.machine_id} · ${m.station || ''}`); option.value = m.machine_id; $('machine').append(option); }
    if (board.machines.some(m => m.machine_id === selected)) $('machine').value = selected;
    renderItems(); for (const b of board.collections) renderBatch(b, $('batches'));
    for (const a of board.alerts) $('alerts').append(text('p', `회수 ${a.collection_id} · ${a.item_id} · ${a.sent_at ? '전송 기록 있음' : '미전송'}`));
    if (!board.alerts.length) $('alerts').append(text('p', '표시할 미도착 알림이 없습니다.'));
    $('updated').textContent = new Date().toLocaleString('ko-KR') + (Object.values(board.truncated).some(Boolean) ? ' · 표시 한도 초과, 번호로 조회하세요.' : '');
    if ($('message').textContent === '연결을 확인하고 있습니다.') message('회수 목록을 불러왔습니다.');
  }
  async function action(fn) {
    if (busy) return; busy = true; controls();
    try { await fn(); } catch (e) { message(e.message || '연결을 확인해주세요.'); }
    finally { busy = false; controls(); }
  }
  async function sendPickup() {
    let result;
    try { result = await api('/collections', pending); }
    catch (error) {
      // Store validation/conflict rolls back. Auth/transport/5xx remains uncertain.
      if (error.status === 409 || error.status === 422) remember(null);
      throw error;
    }
    remember(null); message(`회수 ${result.collection_id} 기록을 확인했습니다.`); await load();
  }
  $('machine').onchange = renderItems;
  $('refresh').onclick = () => action(load);
  $('pickup').onclick = () => action(async () => {
    const ids = Array.from($('items').querySelectorAll('input:checked'), b => b.value);
    if (!ids.length || pending) return;
    const key = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
    remember({machine_id: $('machine').value, item_ids: ids, request_id: key}); await sendPickup();
  });
  $('retry').onclick = () => action(sendPickup);
  $('readiness').onclick = () => action(async () => { const d = await api('/readiness'); message(`연결 점검: ${d.ready ? '준비됨' : '확인 필요'} · 회수 ${d.collection} · 통계 ${d.statistics} · 같은 DB ${d.same_database ? '확인' : '미확인'}`); });
  $('stats').onsubmit = e => { e.preventDefault(); action(async () => { $('answer').textContent = ''; const d = await api('/statistics/questions', {question: $('question').value}); $('answer').textContent = d.answer; }); };
  $('question').oninput = () => { $('answer').textContent = ''; };
  $('lookup').onsubmit = e => { e.preventDefault(); action(async () => { $('lookupResult').replaceChildren(); renderBatch(await api('/collections/' + Number($('collectionId').value)), $('lookupResult')); }); };
  remember(pending); action(load);
})();
