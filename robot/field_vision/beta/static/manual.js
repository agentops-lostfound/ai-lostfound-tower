(() => {
 'use strict';
 const $=id=>document.getElementById(id),names=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'],labels=['맨 아래 좌우 회전','어깨 · 앞뒤','팔꿈치','손목 굽힘','손목 회전','집게'];
 let state={},selected=0,held=null,baseline={},busy=false,lastError='',polling=false,jogSending=false,stopping=false;
 $('joints').innerHTML=names.map((n,i)=>`<tr id="row-${i}"><td><b>${i+1}. ${labels[i]}</b><small>${n}</small></td><td id="position-${i}">—</td><td id="delta-${i}">—</td><td><span id="torque-${i}">—</span><small id="range-${i}">—</small><div class="row-control"><button class="torque" data-enable="${n}">토크 켜기</button><button class="torque" data-disable="${n}">토크 끄기</button></div></td><td><div class="row-control"><button class="jog" data-joint="${n}" data-direction="-1">− 유지</button><button class="jog" data-joint="${n}" data-direction="1">＋ 유지</button></div></td></tr>`).join('');
 function log(message,error=false){const div=document.createElement('div');div.textContent=new Date().toLocaleTimeString('ko-KR')+' · '+message;if(error)div.className='error';$('messages').prepend(div);while($('messages').children.length>70)$('messages').lastChild.remove();}
 async function api(path,data){const r=await (window.visionFetch||fetch)('/api/manual/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.detail||'요청 실패');return v;}
 async function command(action,data={}){return api('command',{action,...data});}
 function select(i){selected=i;names.forEach((_,j)=>$('row-'+j).classList.toggle('selected',i===j));}
 let torqueBusy=false;
 function render(s){state=s;const fresh=s.connected&&s.age!=null&&s.age<1.2;let text=s.connected?(fresh?'연결됨':'피드백 지연'):'연결 안 됨';if(s.latched)text+=' · 정지 잠금: 상단의 ‘정지 해제’를 먼저 누르세요';if(s.active)text+=' · '+(s.active.kind==='move'?'다축 목표 이동 중':labels[names.indexOf(s.active.joint)]+' 조그 중');const joints=s.joints||[];
  $('enableAll').disabled=!fresh||torqueBusy||!!s.active||s.latched||joints.length!==6||joints.every(j=>j.torque_enabled);
  $('disableAll').disabled=!fresh||torqueBusy||!!s.active||!joints.some(j=>j.torque_enabled);
  $('status').textContent=text+' · '+(s.latched?'이전 정지·오류 잠금이 유지되고 있습니다. 범위 안으로 돌아와도 직접 정지 해제가 필요합니다.':s.message)+(s.session?' · 세션 '+s.session:'');$('connect').disabled=s.connected||busy;$('disconnect').disabled=!s.connected;$('resume').disabled=!s.connected;$('resume').classList.toggle('primary',!!s.latched);$('resume').textContent=s.latched?'▶ 정지 해제 · 토크 조작 잠금 풀기':'정지 해제';
  (s.joints||[]).forEach(j=>{const i=names.indexOf(j.name);if(i<0)return;if(baseline[j.name]===undefined)baseline[j.name]=j.raw_ticks;$('position-'+i).textContent=j.raw_ticks+' / '+j.normalized.toFixed(2);$('delta-'+i).textContent=((j.raw_ticks-baseline[j.name])*360/4096).toFixed(2)+'°';$('torque-'+i).textContent='토크 '+(j.torque_enabled?'ON':'OFF');$('range-'+i).textContent=(j.in_range?'범위 안':'범위 밖')+' · '+j.min_ticks+'~'+j.max_ticks;$('range-'+i).className=j.in_range?'good':'bad';document.querySelectorAll('[data-joint="'+j.name+'"]').forEach(b=>b.disabled=!fresh||!j.torque_enabled||s.latched);document.querySelector('[data-enable="'+j.name+'"]').disabled=!fresh||s.latched||j.torque_enabled;document.querySelector('[data-disable="'+j.name+'"]').disabled=!fresh||!j.torque_enabled;});
  if(s.last_error&&s.last_error!==lastError){lastError=s.last_error;log(s.last_error,true);}if(!fresh&&held)release(true);
 }
 async function poll(){if(polling||document.hidden)return;polling=true;try{render(await api('state'));}catch(e){$('status').textContent='서버 연결 끊김 · 조그 신호 만료 시 자동 정지';if(held)release(true);}finally{polling=false;}}
 async function release(latch=false){const previous=held;held=null;document.querySelectorAll('.jog').forEach(b=>b.classList.remove('pressed'));if(stopping)return;stopping=true;try{if(state.connected){await command(latch?'stop':'halt',{token:previous?.token});if(latch)log('정지 요청 · 토크 유지');}}catch(e){log(e.message,true);}finally{stopping=false;}}
 async function jog(){if(!held||jogSending)return;jogSending=true;const input={...held};try{await command('jog',input);}catch(e){log(e.message,true);release(true);}finally{jogSending=false;}}
 function begin(joint,direction,button){if(held||stopping||!state.connected||state.latched)return;const j=state.joints?.find(j=>j.name===joint);if(!j?.torque_enabled){log('해당 관절의 토크 켜기를 먼저 누르세요.',true);return;}select(names.indexOf(joint));held={joint,direction,speed:Number($('speed').value),token:crypto.randomUUID()};button?.classList.add('pressed');log(labels[selected]+' · '+(direction>0?'+':'−')+' 조그 시작 · '+held.speed+'도/초');jog();}
 document.querySelectorAll('.jog').forEach(b=>{b.onpointerdown=e=>{e.preventDefault();b.setPointerCapture(e.pointerId);begin(b.dataset.joint,Number(b.dataset.direction),b);};b.onpointerup=()=>release();b.onpointercancel=()=>release(true);b.onlostpointercapture=()=>{if(held)release();};});
 document.querySelectorAll('[data-enable],[data-disable]').forEach(b=>b.onclick=async()=>{const enabling=!!b.dataset.enable,name=b.dataset.enable||b.dataset.disable;b.disabled=true;try{if(held)await release();render(await command(enabling?'enable':'disable',{joint:name}));log(labels[names.indexOf(name)]+' 토크 '+(enabling?'켜기':'끄기'));}catch(e){log(e.message,true);}finally{poll();}});
 async function allTorque(action){
  if(torqueBusy)return;
  if(action==='disable'&&!confirm('팔과 집게가 힘을 잃습니다. 팔을 받친 상태에서 전체 토크를 해제할까요?'))return;
  torqueBusy=true;render(state);
  try{render(await command(action,{joint:'all'}));log(action==='enable'?'전체 토크 켜기 완료':'전체 토크 해제 완료');}
  catch(e){log(e.message,true);}
  finally{torqueBusy=false;poll();}
 }
 $('enableAll').onclick=()=>allTorque('enable');
 $('disableAll').onclick=()=>allTorque('disable');
 $('connect').onclick=async()=>{busy=true;$('connect').disabled=true;try{baseline={};lastError='';render(await api('connect',{}));log('수동 연결 완료 · 토크는 기존 상태 유지');}catch(e){log(e.message,true);}finally{busy=false;poll();}};
 $('disconnect').onclick=async()=>{try{await release(true);render(await api('disconnect',{}));log('연결 종료 · 켜진 토크는 위치 유지를 위해 유지');}catch(e){log(e.message,true);}};
 $('stop').onclick=()=>release(true);
 $('resume').onclick=async()=>{try{render(await command('resume'));log('정지 잠금 해제 · 이동 없음');}catch(e){log(e.message,true);}};
 $('snapshot').onclick=async()=>{try{await release();const r=await api('snapshot',{label:$('label').value});$('saved').textContent='저장 완료: '+r.saved;log('자세·카메라 저장: '+(r.label||'이름 없음'));}catch(e){log(e.message,true);}};
 document.addEventListener('keydown',e=>{const editing=['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName);if(e.key==='Escape'||(!editing&&e.code==='Space')){e.preventDefault();release(true);return;}if(editing)return;if(/^[1-6]$/.test(e.key)){select(Number(e.key)-1);return;}if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();if(!e.repeat)begin(names[selected],e.key==='ArrowRight'?1:-1);}});
 document.addEventListener('keyup',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key))release();});
 window.addEventListener('blur',()=>{if(held)release(true);});document.addEventListener('visibilitychange',()=>{if(document.hidden&&held)release(true);});
 window.addEventListener('pagehide',()=>{navigator.sendBeacon('/api/manual/command',new Blob([JSON.stringify({action:'stop'})],{type:'application/json'}));});
 select(0);setInterval(jog,120);setInterval(poll,200);poll();
})();
