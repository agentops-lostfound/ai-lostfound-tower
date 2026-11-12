(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const names={phone:'핸드폰',wallet:'지갑',hand_cream:'핸드크림',usb:'USB',lip_balm:'립밤'};
  let activeCategoryIds=new Set(Object.keys(names));
  const sources={top:'탑뷰',arm:'ARM',upload:'업로드',sample:'검증 사진',search:'검색'};
  const colorStatus={same:'바탕색 일치',conflict:'바탕색 불일치 −0.30',unknown:'바탕색 확인 불가',uncertain:'유사 색상 · 감점 보류'};
  const states={idle:'대기',loading:'로딩 중',running:'추론 중',unloading:'해제 중'};
  const kinds={detect:'박스 검출',analyze:'물체 분석',monitor:'자동 감시',search:'물품 검색'};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time=t=>new Date(t*1000).toLocaleTimeString('ko-KR',{hour12:false});
  let state=null,result=null,tab='live',settingsLoaded=false,observations=[],registered=[],logLevel='all',autoScroll=true,logSignature='',resultSignature='',followMonitor=true,lastSearchId='',lastSearchRendered='',registerIndex=-1,registerTarget=null;
  const completed=new Set();
  let confidencePaused=false,confidenceSignature='';
  $('confidencePause').onclick=()=>{confidencePaused=!confidencePaused;$('confidencePause').textContent=confidencePaused?'표 갱신 재개':'표 갱신 멈춤';if(!confidencePaused&&state)renderConfidences(state);};
  function renderConfidences(s){
    if(confidencePaused)return;
    const entries=Object.entries(s.confidences||{});
    const signature=JSON.stringify(entries);if(signature===confidenceSignature)return;confidenceSignature=signature;
    $('confidenceTable').innerHTML=entries.length?entries.map(([source,data])=>`<div class="confidence-group"><b>${esc(sources[source]||source)}</b><span class="muted">촬영 ${time(data.captured)} · 임계값 ${data.threshold.toFixed(3)}</span><table><thead><tr><th>품목</th><th>confidence</th><th>판정</th><th>검출 문구</th><th>박스</th></tr></thead><tbody>${data.rows.length?data.rows.map(row=>`<tr><td>${esc(names[row.category]||row.category)}</td><td><strong>${row.score.toFixed(4)}</strong></td><td class="${row.accepted?'score-pass':'score-review'}">${row.accepted?'임계값 통과':'미확정 후보'}</td><td>${esc(row.prompt||'—')}</td><td>${row.bbox.join(', ')}</td></tr>`).join(''):'<tr><td colspan="5">표시할 검출 후보 없음</td></tr>'}</tbody></table></div>`).join(''):'검출을 시작하면 물체별 점수가 표시됩니다.';
  }
  try{const preferred=localStorage.getItem('fieldVision.camera');if(['top','arm'].includes(preferred))$('cameraSelect').value=preferred;}catch{}
  $('cameraSelect').onchange=()=>{try{localStorage.setItem('fieldVision.camera',$('cameraSelect').value);}catch{}};
  let deviceList=[],bridgeSettings={},selectedPaths={};
  for(const key of ['top','arm']){
    const picker=$(key+'Device'),source=$(key+'Source');
    picker.onchange=()=>{selectedPaths[key]=deviceList.find(d=>'device:'+d.index===picker.value)?.path; if(picker.value==='custom'){source.focus();return;}if(picker.value==='bridge'&&bridgeSettings.width){setResolution(key,bridgeSettings.width,bridgeSettings.height);}source.value=picker.value==='bridge'?'http://127.0.0.1:8765/camera.mjpg':picker.value;$(key+'Enabled').checked=true;};
    source.oninput=()=>{selectedPaths[key]=undefined;syncDevicePicker(key);};

  }
  function setResolution(key,width,height){
    const picker=$(key+'Resolution'), value=width+'x'+height;
    picker.querySelector('option[data-saved]')?.remove();
    if(!Array.from(picker.options).some(option=>option.value===value)){
      const saved=new Option(width+'×'+height+' (기존 설정)',value);
      saved.dataset.saved='true';
      picker.add(saved);
    }
    picker.value=value;
  }
  function syncDevicePicker(key){
    const picker=$(key+'Device'),source=$(key+'Source').value;
    const device=selectedPaths[key]?deviceList.find(d=>d.path===selectedPaths[key]):deviceList.find(d=>'device:'+d.index===source);
    picker.value=device?'device:'+device.index:source==='http://127.0.0.1:8765/camera.mjpg'?'bridge':'custom';
  }
  async function scanVideoDevices(){
    const result=await api('video-devices');deviceList=result.devices;bridgeSettings=result.bridge;
    $('videoDevicesStatus').textContent=deviceList.length?deviceList.map(d=>`USB 장치 ${d.index} · ${d.name}${d.location?' · '+d.location:''}${d.index===bridgeSettings.index?' (브리지 설정 번호)':''}`).join(' / '):'연결된 웹캠이 없습니다.';
    for(const key of ['top','arm']){
      const picker=$(key+'Device');
      picker.querySelectorAll('option[value^="device:"]').forEach(option=>option.remove());
      for(const d of deviceList)picker.add(new Option(`USB 장치 ${d.index} · ${d.name}${d.index===bridgeSettings.index?' (브리지 점유 가능)':''}`,'device:'+d.index));
      syncDevicePicker(key);
    }
  }
  $('scanVideoDevices').onclick=()=>scanVideoDevices().catch(e=>{$('videoDevicesStatus').textContent=e.message;});
  $('scanVideoDevices').click();
  function cameraReadout(s){
    for(const key of ['top','arm']){
      const c=s.cameras[key];if(!c)continue;
      const size=c.connected?(c.input_size?.join('×')||'확인 중'):'영상 미연결';
      const device=deviceList.find(d=>d.index===c.device_index);
      $(key+'Actual').textContent=`${device?('USB 장치 '+device.index+' · '+device.name+' / '):''}수신 ${size}${c.connected&&c.frame_size&&c.frame_size.join('×')!==size?' / 처리 '+c.frame_size.join('×'):''}`;
    }
  }
  let toastTimer;
  function toast(message,error=false){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').className='toast visible'+(error?' error':'');toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),5000);}
  async function api(path,data){const response=await (window.visionFetch||fetch)('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let value;try{value=await response.json();}catch{throw new Error('서버 응답을 읽을 수 없습니다. 작업 로그를 확인하세요.');}if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail||value));return value;}
  function action(fn){return async e=>{e?.preventDefault();try{await fn(e);}catch(error){toast(error.message,true);}};}
  function showTab(next){tab=next;document.querySelectorAll('.view').forEach(el=>el.classList.toggle('active',el.id==='tab-'+next));document.querySelectorAll('.nav').forEach(el=>el.classList.toggle('active',el.dataset.tab===next));$('pageTitle').innerHTML=({live:'관측 콘솔',registry:'등록 물품',search:'물품 검색',settings:'시스템 설정'}[next])+' <span class="version">BETA</span>';if(next==='registry')refreshRegistry();}
  document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>showTab(button.dataset.tab));
  document.querySelectorAll('[data-camera]').forEach(button=>button.onclick=()=>{$('cameraSelect').value=button.dataset.camera;toast((sources[button.dataset.camera])+' 카메라를 분석 소스로 선택했습니다.');});
  function modelCards(s){for(const key of ['yolo','owl','sig','qwen']){const data=s.models[key],card=$('model-'+key);if(!data||!card)continue;card.className='model-card '+data.status;card.querySelector('.model-message').textContent=data.message;card.querySelector('.model-badge').textContent=states[data.status]||data.status;}}
  function cameras(s){
    $('showCandidates').checked=!!s.settings.show_candidates;
    for(const key of ['top','arm']){
      const data=s.cameras[key];if(!data)continue;
      const online=data.connected,img=$(key+'Stream'),warning=data.signal_warning,tracks=data.overlay||[];
      $(key+'Status').textContent=online?(warning?'SIGNAL CHECK':'CONNECTED'):data.enabled?'OFFLINE':'미사용';
      $(key+'Status').className='pill small'+(warning?' amber':online?' online':'');
      img.hidden=!online;$(key+'Empty').hidden=online;$(key+'Empty').classList.toggle('hidden',online);
      if(online&&!img.getAttribute('src'))img.src='/api/cameras/'+key+'/frame.jpg';
      const confirmed=tracks.filter(t=>!t.preview&&['accepted','detected'].includes(t.quality));
      const status=confirmed.length?confirmed.map(t=>names[t.category]||t.category).join(' · ')+' / 추적 중':tracks.length?'미확정 후보 / 검토 필요':s.active?.source===key?'검출·분석 중':s.monitor&&s.monitor_camera===key?'재검출 대기':'감시 대기';
      $(key+'OverlayStatus').textContent=status;
      $(key+'OverlayStatus').className='overlay-label'+(confirmed.length?' found':tracks.length?' uncertain':'');
      $(key+'Message').textContent=online?(warning||'초록 실선: 검출·추적 / 주황 점선: 미확정'):(data.error||'연결 대기');
      img.parentElement.querySelector('.live-stamp').firstChild.nodeValue=online?'● LIVE ':'○ OFFLINE ';
      if(warning)img.parentElement.dataset.signal=warning;else delete img.parentElement.dataset.signal;
      $(key+'LiveCrops').innerHTML=tracks.length?tracks.map(t=>`<div class="live-crop ${t.preview?'uncertain':''}"><img src="/api/cameras/${key}/crop/${esc(t.id)}.jpg?v=${Math.floor(s.time)}" alt="${esc(names[t.category]||t.category)} 실시간 crop"><span>${esc(t.category)}${t.preview?'?':''}<small>${t.preview?'미확정 후보':'추적 중'}</small></span></div>`).join(''):'<span class="muted">감시를 시작하면 라이브 박스·품목·crop이 표시됩니다.</span>';
    }
  }
  function hydrateSettings(s){if(settingsLoaded)return;settingsLoaded=true;for(const key of ['top','arm']){$(key+'Enabled').checked=s.settings.cameras[key].enabled;$(key+'Source').value=s.settings.cameras[key].source;selectedPaths[key]=s.settings.cameras[key].device_path;syncDevicePicker(key);const c=s.settings.cameras[key], bridge=c.source.includes(':8765/');setResolution(key,c.width??(bridge?bridgeSettings.width:1280)??1280,c.height??(bridge?bridgeSettings.height:720)??720);}$('interval').value=s.settings.interval;$('threshold').value=s.settings.threshold;$('roi').value=s.settings.roi?JSON.stringify(s.settings.roi):'';$('autoFeatures').checked=s.settings.auto_features;$('featureLimit').value=s.settings.feature_limit;$('analysisDelay').value=s.settings.analysis_delay??5;}
  function logs(s){let rows=s.logs;if(logLevel==='model')rows=rows.filter(r=>['owl','sig','qwen','detection','matching'].includes(r.stage));if(logLevel==='error')rows=rows.filter(r=>r.level==='error'||r.level==='warning');const sig=logLevel+':'+rows.map(r=>r.seq).join(',');if(sig===logSignature)return;logSignature=sig;$('logCount').textContent=(s.logs.at(-1)?.seq||0)+' events';const scroll=$('logs').scrollTop;$('logs').innerHTML=rows.length?rows.map(r=>`<article class="log-event ${esc(r.level)}"><div class="log-event-head"><span>${time(r.time)}</span><span class="log-stage">${esc(r.stage)}</span>${r.status?'<span>'+esc(states[r.status]||r.status)+'</span>':''}</div><p>${esc(r.message)}</p></article>`).join(''):'<div class="log-placeholder">표시할 이벤트가 없습니다.</div>';$('logs').scrollTop=autoScroll?$('logs').scrollHeight:scroll;}
  document.querySelectorAll('[data-level]').forEach(button=>button.onclick=()=>{logLevel=button.dataset.level;document.querySelectorAll('[data-level]').forEach(el=>el.classList.toggle('active',el===button));if(state)logs(state);});
  $('logPause').onclick=()=>{autoScroll=!autoScroll;$('logPause').textContent=autoScroll?'Ⅱ':'▷';$('logPause').title=autoScroll?'자동 스크롤 일시정지':'자동 스크롤 다시 시작';};
  function setResult(next){if(!next)return;const signature=JSON.stringify(next);if(signature===resultSignature)return;resultSignature=signature;result=next;renderResult();}
  function renderResult(){const r=result;if(!r)return;$('detectedCount').textContent=r.items.length;$('resultStatus').textContent=r.status==='complete'?`${(r.seconds||0).toFixed(1)}초 · 완료`:'검출 스냅샷';$('snapshotMeta').textContent=`${sources[r.source]||r.source} · #${r.frame_id??'사진'} · ${time(r.captured)}`;$('snapshot').innerHTML=`<img src="${esc(r.snapshot)}?v=${r.created}" alt="검출 당시 프레임과 바운딩박스">`;$('snapshotFoot').textContent=`${r.image_size.join(' × ')} px · 촬영 ${time(r.captured)} · 중심 좌표는 집기점·로봇 좌표가 아닙니다.`;$('objects').innerHTML=r.items.length?r.items.map(obj=>{
      const accepted=obj.quality==='accepted',tags=obj.features?Object.entries(obj.features).map(([key,v])=>`<span title="${esc(key)}">${esc(v)}</span>`).join(''):'';
      const candidates=obj.candidates?.length?`<div class="candidate-line">후보: ${obj.candidates.map(c=>`${esc(c.id)} 최종 ${(c.matching_score??c.similarity).toFixed(3)} / 사진 ${c.similarity.toFixed(3)} · ${colorStatus[c.color_comparison?.status]||'색상 비교 전'}`).join(' · ')} / 일치 미확정</div>`:obj.excluded_identical_images?`<div class="candidate-line">동일 픽셀 참조 ${obj.excluded_identical_images}장 제외 · 별도 사진으로 비교하세요.</div>`:'';
      return `<article class="object">${obj.crop?`<img src="${esc(obj.crop)}" alt="물체 ${obj.index+1} crop">`:'<div class="empty">⌖</div>'}<div><div class="object-title"><b>#${obj.index+1} ${esc(names[obj.category]||obj.category)}</b><span class="pill small ${accepted?'online':'amber'}">${accepted?'검사 통과':obj.quality==='detected'?'검출 후보':obj.quality==='rejected'?'거절':'검토 필요'}</span></div><div class="object-coords">bbox [${obj.bbox.join(', ')}] · score ${obj.score.toFixed(3)}<br>center (${obj.center.map(n=>n.toFixed(1)).join(', ')})</div>${tags?`<div class="feature-tags">${tags}</div>`:''}${obj.reasons?.length?`<p class="object-reason">${esc(obj.reasons.join(' · '))}</p>`:''}${obj.feature_status==='invalid_json'?'<p class="object-reason">특징 JSON 검증 실패 · 원문은 내보내기에서 확인</p>':''}${obj.feature_status==='limit_skipped'?'<p class="object-reason">요청당 특징 처리 제한으로 생략</p>':''}${candidates}<div class="object-bottom"><span>${obj.embedding_dim?obj.embedding_dim+'차원 · ':''}${obj.features?'특징 검토 전':r.status==='complete'?'특징 없음':'품목·특징 분석 전'}</span>${accepted&&obj.embedding_dim?`<button class="text-button" data-register="${obj.index}">물품 등록 ＋</button>`:''}</div></div></article>`;
    }).join(''):'<div class="empty small-empty"><span>⌖</span><b>검출된 후보가 없습니다.</b><p>장면이 비었다고 확정할 수는 없습니다.<br>화각·조명·임계값을 확인하세요.</p></div>';
    $('objects').querySelectorAll('[data-register]').forEach(button=>button.onclick=()=>openRegister(Number(button.dataset.register)));renderHistory();}
  function renderHistory(){$('history').innerHTML=observations.length?observations.map(r=>`<button class="history-item ${result?.id===r.id?'selected':''}" data-observation="${esc(r.id)}">${time(r.created)} · ${sources[r.source]||esc(r.source)} · ${r.items.length}개</button>`).join(''):'<span class="muted">저장된 관측이 없습니다.</span>';$('history').querySelectorAll('[data-observation]').forEach(button=>button.onclick=()=>{followMonitor=false;setResult(observations.find(r=>r.id===button.dataset.observation));});}
  async function refreshObservations(selectId){observations=await api('observations');if(selectId)setResult(observations.find(r=>r.id===selectId));else if(!result&&observations.length)setResult(observations[0]);renderHistory();}
  async function refreshRegistry(){try{registered=await api('registry');$('registryCount').textContent=registered.length;$('registryList').innerHTML=registered.length?registered.map(item=>`<article class="panel registry-card"><img src="${esc(item.references[0]?.image||'')}" alt="${esc(item.name)} 참조 사진"><div><span class="item-id">${esc(item.id)}</span><h3>${esc(item.name)}</h3><p>${esc(names[item.category])} · 참조 ${item.reference_count}장</p><div class="feature-tags">${Object.values(item.references[0]?.features||{}).map(v=>`<span>${esc(v)}</span>`).join('')}</div><p>${esc(item.notes||'관리자 메모 없음')}</p><div class="ref-strip">${item.references.map(r=>`<span class="ref-thumb"><img src="${esc(r.image)}" alt="참조 사진"><button type="button" title="이 참조 사진 삭제" data-ref-delete="${esc(r.id)}" data-item="${esc(item.id)}">×</button></span>`).join('')}</div><div class="registry-actions"><button type="button" class="button secondary compact" data-reg-edit="${esc(item.id)}">수정</button><button type="button" class="button secondary compact" data-reg-merge="${esc(item.id)}">ID 변경 / 합치기</button><button type="button" class="button danger compact" data-reg-delete="${esc(item.id)}">삭제</button></div></div></article>`).join(''):'<div class="panel empty"><span>▦</span><b>아직 등록된 물품이 없습니다.</b><p>관측 콘솔에서 물건을 분석한 뒤<br>검사 통과 항목의 물품 등록을 선택하세요.</p></div>';}catch(e){toast(e.message,true);}}
  // v0.2.59: registry editing
  document.addEventListener('click',async event=>{
    // inside the beta shell this page lives in a shadow root: use the real clicked node
    const origin=(event.composedPath&&event.composedPath()[0])||event.target;const t=origin.closest&&origin.closest('[data-reg-edit],[data-reg-merge],[data-reg-delete],[data-ref-delete]');if(!t)return;
    try{
      if(t.dataset.regEdit){const item=registered.find(i=>i.id===t.dataset.regEdit);
        const name=prompt('표시 이름',item.name);if(name===null)return;
        const notes=prompt('관리자 메모',item.notes||'');if(notes===null)return;
        const cats=Object.keys(names).filter(k=>activeCategoryIds.has(k));
        const category=prompt('품목 ID ('+cats.join(', ')+')',item.category);if(category===null)return;
        await api('registry',{operation:'update',id:item.id,name,notes,category:category.trim()});toast('수정 완료');}
      else if(t.dataset.regMerge){const target=prompt(`새 ID를 입력하세요.
이미 있는 ID를 입력하면 그 물품으로 참조 사진이 합쳐집니다. (현재: ${t.dataset.regMerge})`,'');if(!target)return;
        const r=await api('registry',{operation:'merge',id:t.dataset.regMerge,target:target.trim()});toast(r.merged?`${r.id}로 합침 · 사진 ${r.moved}장 이동, 중복 ${r.duplicates_removed}장 제외`:`ID 변경 → ${r.id}`);}
      else if(t.dataset.regDelete){if(!confirm(`${t.dataset.regDelete} 물품과 참조 사진을 모두 삭제할까요? 되돌릴 수 없습니다.`))return;
        const r=await api('registry',{operation:'delete',id:t.dataset.regDelete});toast(`삭제 완료 · 참조 사진 ${r.references_deleted}장`);}
      else if(t.dataset.refDelete){if(!confirm('이 참조 사진을 삭제할까요? 되돌릴 수 없습니다.'))return;
        const r=await api('registry',{operation:'delete_reference',ref_id:t.dataset.refDelete});toast(`참조 사진 삭제 · 남은 ${r.remaining}장`);}
      await refreshRegistry();
    }catch(e){toast(e.message,true);}
  });
  function openRegister(index){registerIndex=index;registerTarget={observation_id:result.id,index:index};const obj=result.items.find(o=>o.index===index);$('registerSummary').textContent=`${names[obj.category]} · 관측 ${time(result.captured)} · 참조 사진 1장`;$('itemCategory').replaceChildren(...Object.entries(names).filter(([key])=>activeCategoryIds.has(key)).map(([key,label])=>new Option(label,key)));$('itemCategory').value=obj.category;$('itemId').value='';$('itemName').value=(obj.features?.colors&&obj.features.colors!=='unknown'?obj.features.colors+' ':'')+names[obj.category];$('itemNotes').value='';$('registerDialog').showModal();$('itemId').focus();}
  $('closeDialog').onclick=()=>$('registerDialog').close();
  $('registerForm').onsubmit=action(async()=>{const r=await api('register',{observation_id:registerTarget.observation_id,index:registerTarget.index,item_id:$('itemId').value,category:$('itemCategory').value,name:$('itemName').value,notes:$('itemNotes').value});$('registerDialog').close();toast(r.added_reference?'물품과 참조 사진을 저장했습니다.':'동일한 참조 사진은 중복 저장하지 않았습니다.');await refreshRegistry();});
  function onState(s){const firstState=state===null;state=s;monitorSummary(s);renderConfidences(s);const active=s.active;$('connection').textContent='LOCAL CONNECTED';$('connection').className='pill online';$('systemState').textContent=active?'처리 중':s.monitor?'자동 감시 중':'분석 준비 완료';$('systemDot').style.background=active?'var(--green)':'var(--mint)';$('jobDescription').textContent=active?`${kinds[active.kind]||active.kind} · ${sources[active.source]||active.source} · ${Math.max(0,s.time-active.started).toFixed(0)}초`:(s.gpu_resident_enabled?`${activeCategoryIds.size}개 품목 · OWL/Sig 상주 · 순차 추론`:`${activeCategoryIds.size}개 품목 · 메모리 절약 순차 로딩`);$('gpuMemory').textContent=s.metrics.gpu_used_mib!=null?`${(s.metrics.gpu_used_mib/1024).toFixed(1)} / ${(s.metrics.gpu_total_mib/1024).toFixed(0)} GB`:'측정 대기';$('ramMemory').textContent=s.metrics.ram_used_gib.toFixed(1)+' GB';$('queueSize').textContent=s.queue_size;$('monitorButton').textContent=s.monitor?'Ⅱ 감시 중지':'▷ 자동 감시';$('monitorButton').className='button '+(s.monitor?'primary':'secondary');for(const id of ['analyzeButton','detectButton','sampleButton'])$(id).disabled=s.queue_size>=2;modelCards(s);cameras(s);logs(s);hydrateSettings(s);cameraReadout(s);if(followMonitor&&s.monitor&&s.latest[s.monitor_camera])setResult(s.latest[s.monitor_camera]);for(const job of s.jobs){if(job.id===lastSearchId&&job.status==='complete'&&job.search_result&&lastSearchRendered!==job.id){lastSearchRendered=job.id;renderSearch(job.search_result);if($('searchThenLocate')?.checked)window.dispatchEvent(new CustomEvent('search-target',{detail:job.search_result.candidates[0]||null}));}if(['complete','failed','cancelled'].includes(job.status)&&!completed.has(job.id)){completed.add(job.id);if(firstState)continue;if(job.status==='complete'&&job.result){refreshObservations(job.id).catch(e=>toast(e.message,true));}else if(job.status==='failed')toast(job.message,true);}}
  }
  function feedback(id,message,error=false){const el=$(id);el.textContent=message;el.className='operation-feedback '+(error?'failed':'success');}
  function monitorSummary(s){
    const enabled=s.settings.auto_features;
    feedback('monitorFeedback',`${sources[s.monitor_camera]||'탑뷰'} 자동 감시 ${s.monitor?'켜짐':'꺼짐'} · 자동 분석 ${enabled?'켜짐':'꺼짐'}${enabled?' (감지 후 '+s.settings.analysis_delay+'초 대기)':''} · ${s.monitor?'감시 간격 '+s.settings.interval+'초':enabled?'자동 분석을 실행하려면 자동 감시를 시작하세요.':'박스 검출만 수행합니다.'}`);
  }
  $('monitorButton').onclick=async()=>{
    const button=$('monitorButton');button.disabled=true;button.textContent='감시 상태 변경 중…';
    try{
      const current=await api('state'),enabled=!current.monitor;
      await api('monitor',{enabled,camera:$('cameraSelect').value});
      const verified=await api('state');onState(verified);
      if(verified.monitor!==enabled)throw new Error('감시 상태가 적용되지 않았습니다. 다시 시도하세요.');
      followMonitor=enabled;
      feedback('monitorFeedback',enabled?`${sources[verified.monitor_camera]} 자동 감시 켜짐 · ${verified.settings.interval}초 간격 · 자동 특징 분석 ${verified.settings.auto_features?'켜짐':'꺼짐'}`:'자동 감시 꺼짐');
    }catch(error){feedback('monitorFeedback','감시 변경 실패: '+error.message,true);toast(error.message,true);}
    finally{button.disabled=false;if(state){button.textContent=state.monitor?'Ⅱ 감시 중지':'▷ 자동 감시';}}
  };
  $('cancelButton').onclick=action(async()=>{await api('cancel',{});toast('중단을 요청했습니다. 진행 중 연산 종료 후 GPU를 해제합니다.');});
  $('showCandidates').onchange=action(async()=>{await api('overlay',{show_candidates:$('showCandidates').checked});});
  function analyze(kind){return action(async()=>{followMonitor=false;const job=await api('analyze',{kind,camera:$('cameraSelect').value,with_features:$('withFeatures').checked});toast(`${kinds[kind]} 요청을 접수했습니다. 우측 로그에서 진행 상태를 확인하세요.`);});}
  $('analyzeButton').onclick=analyze('analyze');$('detectButton').onclick=analyze('detect');
  $('followLatest').onclick=()=>{followMonitor=true;const latest=state?.latest[$('cameraSelect').value];if(latest)setResult(latest);else toast('선택 카메라의 감시 프레임이 아직 없습니다. 자동 감시를 시작하세요.');};
  $('resetHistory').onclick=action(async()=>{
    const reset=await api('observations/reset',{});
    result=null;resultSignature='';observations=[];followMonitor=false;completed.clear();
    $('detectedCount').textContent='0';$('resultStatus').textContent='초기화됨';
    $('snapshot').innerHTML='<div class="empty"><b>최근 감지 결과를 초기화했습니다.</b><p>분석 또는 자동 감시를 다시 시작하세요.</p></div>';
    $('objects').innerHTML='<div class="empty"><p>검출 결과 없음</p></div>';
    $('snapshotMeta').textContent='초기화됨';$('snapshotFoot').textContent='등록 물품과 참조 사진은 유지됩니다.';
    renderHistory();onState(await api('state'));toast(`최근 관측 ${reset.cleared}건 초기화 완료 · 등록 물품 유지`);
  });
  $('sampleButton').onclick=action(async()=>{followMonitor=false;await api('sample',{with_features:$('withFeatures').checked});toast('검증용 지갑 사진을 분석합니다. 실제 생중계 입력과 구분해 표시합니다.');});
  function fileData(file){if(!file)throw new Error('파일을 선택하세요.');if(file.size>10*1024*1024)throw new Error('이미지는 10MB 이하로 줄여주세요.');return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('파일 읽기 실패'));reader.readAsDataURL(file);});}
  $('analyzeUpload').onchange=action(async e=>{const data=await fileData(e.target.files[0]);followMonitor=false;await api('analyze',{kind:'analyze',data_url:data,with_features:$('withFeatures').checked});e.target.value='';toast('업로드 사진 분석을 접수했습니다.');});
  function renderSearch(r){$('searchResult').innerHTML=`<div class="notice">${esc(r.query)}${r.used_text?' → '+esc(r.used_text):''} · 후보 순위이며 개체 일치 확정이 아닙니다.</div>`+(r.candidates.length?'<div class="search-candidates">'+r.candidates.map(c=>`<article class="panel registry-card"><img src="${esc(c.image)}" alt="${esc(c.name)}"><div><span class="item-id">${esc(c.id)}</span><h3>${esc(c.name)}</h3><p>${esc(names[c.category])}</p><div class="search-score">최종 ${(c.matching_score??c.similarity).toFixed(3)} · 사진 ${c.similarity.toFixed(3)}</div><p>${colorStatus[c.color_comparison?.status]||'색상 비교 전'}</p><span class="pill small amber">검토할 후보</span></div></article>`).join('')+'</div>':'<div class="panel empty"><b>해당 조건의 등록 후보가 없습니다.</b></div>');}
  async function search(data){const job=await api('search',{...data,category:$('searchCategory').value});lastSearchId=job.id;$('searchResult').innerHTML='<div class="panel empty"><span>⌕</span><b>SigLIP2로 등록 물품을 비교하고 있습니다.</b><p>오른쪽 모델 로그에서 진행 상태를 확인하세요.</p></div>';}
  $('searchButton').onclick=action(async()=>search({text:$('searchText').value}));$('searchText').onkeydown=e=>{if(e.key==='Enter')$('searchButton').click();};
  $('searchUpload').onchange=action(async e=>{const data=await fileData(e.target.files[0]);await search({data_url:data,text:$('searchText').value});e.target.value='';});
  $('settingsForm').onsubmit=async event=>{
    event.preventDefault();const button=$('settingsForm').querySelector('button[type=submit]');button.disabled=true;button.textContent='설정 저장 중…';
    feedback('settingsFeedback','설정을 저장하고 서버 적용 상태를 확인하고 있습니다.');
    try{
      const cameras={};
      for(const key of ['top','arm']){
        const [width,height]=$(key+'Resolution').value.split('x').map(Number);
        cameras[key]={enabled:$(key+'Enabled').checked,source:$(key+'Source').value,width,height,device_path:selectedPaths[key]};
      }
      const roi=$('roi').value.trim();
      await api('settings',{cameras,exclude_aruco:$('excludeAruco').checked,interval:Number($('interval').value),threshold:Number($('threshold').value),roi:roi?JSON.parse(roi):null,auto_features:$('autoFeatures').checked,analysis_delay:Number($('analysisDelay').value),feature_limit:Number($('featureLimit').value)});
      settingsLoaded=false;const verified=await api('state');onState(verified);
      feedback('settingsFeedback',`저장 완료 (${new Date().toLocaleTimeString('ko-KR')}) · 감시 간격 ${verified.settings.interval}초 / 분석 대기 ${verified.settings.analysis_delay}초 / 자동 분석 ${verified.settings.auto_features?'켜짐':'꺼짐'}`);
      toast('설정 저장·서버 적용 확인 완료');
    }catch(error){feedback('settingsFeedback','저장 실패: '+error.message,true);toast(error.message,true);}
    finally{button.disabled=false;button.textContent='설정 저장·카메라 재연결 ↗';}
  };
  let statePending=false;setInterval(async()=>{if(document.hidden||statePending)return;statePending=true;try{onState(await api('state'));}catch(e){$('connection').textContent='연결 재시도 중';}finally{statePending=false;}},1000);
  setInterval(()=>$('clock').textContent=new Date().toLocaleTimeString('ko-KR',{hour12:false}),1000);
  api('state').then(onState).catch(e=>toast(e.message,true));refreshObservations().catch(e=>toast(e.message,true));

  async function refreshCategories(){try{const data=await api('categories');activeCategoryIds=new Set(data.items.filter(r=>r.enabled).map(r=>r.id));for(const r of data.items)names[r.id]=r.name;const picker=$('searchCategory');if(picker){const selected=picker.value;picker.replaceChildren(new Option('전체 품목',''),...data.items.map(r=>new Option(r.name+(r.enabled?'':' (검출 꺼짐)'),r.id)));if(data.items.some(r=>r.id===selected))picker.value=selected;}}catch(e){console.warn('카테고리 조회 실패',e)}}
  refreshCategories();setInterval(refreshCategories,10000);
})();
