'use strict';
const $=id=>document.getElementById(id);
let snapshot=null,busy=false,fresh=false,pickupSelection=new Set(),pendingPickup=null;
const arrivalDrafts=new Map(),zeroConfirm=new Set();
function el(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
function message(text,error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
async function api(path,body){
 const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','x-demo-revision':snapshot?.revision||''},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
 let data;try{data=await response.json();}catch{throw Error('서버 응답을 확인하지 못했습니다. 새로고침으로 기록을 확인해주세요.');}
 if(!response.ok){const error=Error(typeof data.detail==='string'?data.detail:data.detail?.message||'요청을 처리하지 못했습니다. 다시 확인해주세요.');error.code=data.detail?.code;throw error;}return data;
}
function clearDrafts(){pickupSelection.clear();pendingPickup=null;arrivalDrafts.clear();zeroConfirm.clear();$('resetConfirm').hidden=true;}
function failed(error,saved){fresh=false;if(error.code==='stale_demo')clearDrafts();message(saved?saved+' 저장은 완료됐지만 목록을 갱신하지 못했습니다. 새로고침 후 계속해주세요.':error.message+' 새로고침으로 최신 기록을 확인해주세요.',true);}
const timeLabel=value=>new Intl.DateTimeFormat('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'}).format(new Date(value));
function title(item){return [item.color,item.category==='모형폰'?'휴대폰(모형폰)':item.category].filter(Boolean).join(' ');}
function row(item,checked,disabled,onchange){
 const label=el('label',undefined,'item-row'),input=document.createElement('input');input.type='checkbox';input.checked=checked;input.disabled=disabled;input.setAttribute('aria-label',`${item.item_id} ${title(item)}${item.arrived?' · 도착 완료':''}`);input.onchange=()=>onchange(input.checked);
 const text=el('span');text.append(el('strong',title(item)),el('small',item.item_id+(item.arrived?' · 도착 완료':'')));label.append(input,text);return label;
}
function renderPickup(){
 const items=snapshot.items.filter(i=>i.machine_id===$('machine').value&&i.status==='등록기계 보관');
 const allowed=new Set(items.map(i=>i.item_id));pickupSelection=new Set([...pickupSelection].filter(id=>allowed.has(id)));
 const list=$('pickupList');list.replaceChildren();
 for(const item of items)list.append(row(item,pickupSelection.has(item.item_id),busy||!fresh||!!pendingPickup,checked=>{if(checked)pickupSelection.add(item.item_id);else pickupSelection.delete(item.item_id);renderPickup();}));
 if(!items.length)list.append(el('div','이 등록기계에 회수할 물건이 없습니다.','empty'));
 $('pickup').disabled=busy||!fresh||!!pendingPickup||!pickupSelection.size;$('selectAll').disabled=busy||!fresh||!!pendingPickup||!items.length;$('machine').disabled=busy||!fresh||!!pendingPickup;
 $('pickupHint').textContent=pendingPickup?'이전 요청의 결과를 확인 중입니다. 같은 요청으로 재시도하면 중복 기록을 방지합니다.':pickupSelection.size?`${pickupSelection.size}개 선택 · 등록기계에서 꺼냈다면 회수 기록을 남기세요.`:'물건을 선택해주세요.';
 $('retryPickup').hidden=!pendingPickup;$('discardPickup').hidden=!pendingPickup;$('retryPickup').disabled=busy||!fresh;$('discardPickup').disabled=busy||!fresh;
}
function renderBatches(){
 const list=$('batchList');list.replaceChildren();$('batchCount').textContent=snapshot.collections.length+'건';
 if(!snapshot.collections.length){list.append(el('div','아직 회수 기록이 없습니다. 왼쪽에서 물건을 선택해 회수를 기록하세요.','empty'));return;}
 for(const batch of snapshot.collections){
  const card=el('article',undefined,'batch'),head=el('div',undefined,'batch-head');head.append(el('strong',`회수 #${batch.collection_id} · 등록기계 ${batch.machine_id.replace('KIOSK-','')}`),el('span',batch.arrived_at?'전량 도착':'도착 확인 중','status'+(batch.arrived_at?' complete':'')));
  card.append(head,el('p',`회수 ${timeLabel(batch.picked_at)}`+(batch.arrived_at?` · 완료 ${timeLabel(batch.arrived_at)}`:''),'batch-meta'));
  const items=el('div',undefined,'batch-items'),draft=arrivalDrafts.get(batch.collection_id)||new Set();
  for(const item of batch.items){if(item.arrived)draft.delete(item.item_id);items.append(row(item,item.arrived||draft.has(item.item_id),busy||!fresh||item.arrived,checked=>{if(checked)draft.add(item.item_id);else draft.delete(item.item_id);arrivalDrafts.set(batch.collection_id,draft);zeroConfirm.delete(batch.collection_id);renderBatches();}));}
  arrivalDrafts.set(batch.collection_id,draft);card.append(items);
  const totalArrived=batch.items.filter(i=>i.arrived).length,actions=el('div',undefined,'batch-actions');actions.append(el('span',`${totalArrived}/${batch.items.length}개 도착 완료`));
  if(!batch.arrived_at){const button=el('button',zeroConfirm.has(batch.collection_id)?'0개 도착 · 미도착 기록 확인':draft.size?`도착 ${draft.size}개 추가 기록`:'도착 체크 결과 저장');button.type='button';button.disabled=busy||!fresh;button.onclick=()=>{if(busy||!fresh)return;if(!draft.size&&!zeroConfirm.has(batch.collection_id)){zeroConfirm.add(batch.collection_id);renderBatches();message('새로 도착한 물건이 0개입니다. 나머지를 미도착으로 기록하려면 같은 버튼을 한 번 더 눌러주세요.');return;}saveArrival(batch.collection_id,[...draft]);};actions.append(button);}
  card.append(actions);list.append(card);
 }
}
function render(){
 if(!snapshot){$('refresh').disabled=busy;$('reset').disabled=true;$('resetYes').disabled=true;return;}
 for(const [id,status] of [['waiting','등록기계 보관'],['moving','회수 중'],['arrived','본센터 보관']])$(id).textContent=snapshot.items.filter(i=>i.status===status).length;
 $('missing').textContent=snapshot.alerts.length;renderPickup();renderBatches();
 const list=$('alertList');list.replaceChildren();
 for(const alert of snapshot.alerts){const item=snapshot.items.find(i=>i.item_id===alert.item_id),line=el('div',undefined,'alert-row'),text=el('div');text.append(el('strong',`${alert.item_id} · ${item?title(item):'물건'}`),el('p',`회수 #${alert.collection_id} · 본센터 도착 체크에서 제외됨`));line.append(text,el('span','알림 미리보기 · 미전송','status'));list.append(line);}
 if(!snapshot.alerts.length)list.append(el('div','현재 도착 확인에서 빠진 물건이 없습니다.','empty'));
 $('refresh').disabled=busy;$('reset').disabled=busy||!fresh||!!pendingPickup;$('resetYes').disabled=busy||!fresh;$('resetNo').disabled=busy;
}
async function load(){fresh=false;const data=await api('/collection-dashboard');if(data.mode!=='demo_sqlite'||!(/^[0-9a-f]{32}$/.test(data.revision)))throw Error('가상 시연 데이터인지 확인할 수 없습니다.');const changed=!!snapshot&&snapshot.revision!==data.revision;if(changed){clearDrafts();message('다른 화면에서 시연을 초기화했습니다. 물건을 다시 선택해주세요.');}snapshot=data;fresh=true;$('updated').textContent='최근 확인 '+timeLabel(new Date());render();return changed;}
async function pickup(){
 if(busy||!fresh)return;if(!pendingPickup){if(!pickupSelection.size)return;pendingPickup={machine_id:$('machine').value,item_ids:[...pickupSelection].sort(),request_id:crypto.randomUUID()};}
 busy=true;render();message('회수 기록을 저장하고 있습니다…');
 let saved=null;
 try{const result=await api('/collections',pendingPickup);saved=`회수 #${result.collection_id}`;pendingPickup=null;pickupSelection.clear();if(!await load())message(`${saved}에 기록했습니다. 본센터에 도착하면 오른쪽에서 체크하세요.`);}
 catch(error){failed(error,saved);if(!saved){try{await load();}catch{/* Lock mutation controls until refresh succeeds; preserve the request key. */}}}
 finally{busy=false;render();}
}
async function saveArrival(cid,ids){
 if(busy||!fresh)return;busy=true;render();message('도착 체크 결과를 저장하고 있습니다…');let saved=null;
 try{const result=await api(`/collections/${cid}/arrivals`,{item_ids:ids});saved=`회수 #${cid} 도착 체크`;arrivalDrafts.delete(cid);zeroConfirm.delete(cid);if(!await load())message(result.missing_item_ids.length?`${ids.length}개 도착 체크를 반영했습니다. 미도착 ${result.missing_item_ids.length}개를 아래에서 확인하세요.`:`회수 #${cid}의 모든 물건이 도착했습니다.`);}
 catch(error){failed(error,saved);if(!saved){try{await load();}catch{/* Lock stale controls until a successful refresh. */}}}
 finally{busy=false;render();}
}
$('machine').onchange=()=>{pickupSelection.clear();renderPickup();};
$('selectAll').onclick=()=>{if(busy||!fresh)return;const ids=snapshot.items.filter(i=>i.machine_id===$('machine').value&&i.status==='등록기계 보관').map(i=>i.item_id);pickupSelection=new Set(pickupSelection.size===ids.length?[]:ids);renderPickup();};
$('pickup').onclick=pickup;$('retryPickup').onclick=pickup;
$('discardPickup').onclick=async()=>{if(busy)return;busy=true;render();try{await load();pendingPickup=null;pickupSelection.clear();message('현재 회수 기록을 확인했습니다. 다시 선택할 수 있습니다.');}catch(e){message(e.message,true);}finally{busy=false;render();}};
$('refresh').onclick=async()=>{if(busy)return;busy=true;render();try{if(!await load())message('최신 회수·도착 기록을 확인했습니다.');}catch(e){message(e.message,true);}finally{busy=false;render();}};
$('reset').onclick=()=>{if(!busy&&fresh)$('resetConfirm').hidden=false;};$('resetNo').onclick=()=>{$('resetConfirm').hidden=true;};
$('resetYes').onclick=async()=>{if(busy||!fresh)return;busy=true;render();let saved=null;try{await api('/demo/reset',{confirm:'RESET_DEMO'});saved='가상 데이터 초기화';clearDrafts();await load();message('가상 물건 6개를 처음 상태로 돌렸습니다.');}catch(e){failed(e,saved);}finally{busy=false;render();}};
load().catch(e=>{message('불러오기 실패: '+e.message,true);$('updated').textContent='연결을 확인해주세요';render();});
