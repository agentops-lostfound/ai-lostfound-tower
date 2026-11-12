(() => {
 const $=id=>document.getElementById(id);let busy=false,refreshing=false,edgeBusy=false;
 async function api(path,data){const r=await (window.visionFetch||fetch)('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const d=await r.json().catch(()=>{throw Error('서버 응답 오류 (HTTP '+r.status+')');});if(!r.ok)throw Error(d.detail||'요청 실패');return d;}
 const fmt=a=>a.map(v=>Number(v).toFixed(1)).join(', ');
 const operation=document.createElement('p');operation.id='operationStatus';operation.setAttribute('role','status');$('phase').after(operation);async function act(fn){if(busy)return;busy=true;operation.textContent='요청 처리 중…';try{await fn();operation.textContent='요청 접수 완료';await poll();}catch(e){operation.textContent='실행 실패: '+e.message;}finally{busy=false;}}
 async function stop(){try{await api('prototype/stop',{});$('phase').textContent='STOP 요청 · 자동 재개 없음';}catch(e){$('phase').textContent='정지 응답 실패: '+e.message;}}
 $('stop').onclick=stop;
 $('connect').onclick=()=>act(()=>api('manual/connect',{}));
 $('registerGripper').onclick=()=>{if(confirm('팔을 멈추고, 물건을 치운 배경에서 50% 열린 고정 손가락이 잘 보이나요?'))act(()=>api('prototype/gripper/register',{}));};
 $('openGripper').onclick=()=>act(()=>api('prototype/gripper/open',{}));
 $('home').onclick=()=>act(()=>api('prototype/home/go',{}));
 const homeFeedback=document.createElement('p');homeFeedback.id='homeSaveFeedback';homeFeedback.setAttribute('role','status');homeFeedback.setAttribute('aria-live','polite');homeFeedback.style.cssText='padding:12px;background:#233d2b;line-height:1.7;white-space:pre-wrap';$('saveHome').after(homeFeedback);
 homeFeedback.textContent='저장 버튼을 누르면 이곳에 완료 또는 실패 이유가 표시됩니다.';
 let savingHome=false;
 $('saveHome').onclick=async()=>{
  if(savingHome)return;savingHome=true;const button=$('saveHome'),label=button.textContent;button.disabled=true;button.textContent='HOME 저장 중…';homeFeedback.textContent='현재 관절값을 읽어 저장하고 있습니다…';
  try{
   const response=await api('prototype/home/save',{});const saved=response.home;
   if(!saved)throw Error('저장 응답에 HOME이 없습니다.');
   const verified=(await api('prototype/state')).home.home;
   if(!verified||verified.created!==saved.created||JSON.stringify(verified.raw_ticks)!==JSON.stringify(saved.raw_ticks))throw Error('저장 후 서버 재조회가 일치하지 않습니다.');
   homeFeedback.textContent='✓ HOME 저장 완료 · '+new Date(saved.created*1000).toLocaleString('ko-KR')+'\n'+Object.entries(saved.raw_ticks).map(([n,v])=>n+': '+v).join(' / ');
   await poll();
  }catch(e){homeFeedback.textContent='✕ HOME 저장 실패: '+e.message;}
  finally{savingHome=false;button.textContent=label;await poll();}
 };
 let targetJobId=null,targetReady=false,targetSearching=false;
 function invalidateTarget(){targetJobId=null;targetReady=false;$('start').disabled=true;$('targetFeedback').textContent='입력이 바뀌었습니다. 대상 검색을 다시 실행하세요.';}
 $('targetText').oninput=invalidateTarget;
 $('targetCategory').onchange=invalidateTarget;
 $('targetPhoto').onchange=()=>{invalidateTarget();$('targetPreview').hidden=true;};
 const readPhoto=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('사진 읽기 실패'));reader.readAsDataURL(file);});
 $('targetSearch').onclick=()=>act(async()=>{
  targetReady=false;targetJobId=null;$('start').disabled=true;
  const text=$('targetText').value.trim(),file=$('targetPhoto').files[0];
  if(!text&&!file)throw Error('목표 사진 또는 설명을 입력하세요.');
  const data_url=file?await readPhoto(file):null;
  if(data_url){$('targetPreview').src=data_url;$('targetPreview').hidden=false;}
  const job=await api('search',{text,data_url,category:$('targetCategory').value});
  targetJobId=job.id;targetSearching=true;
  $('targetCategory').disabled=true;$('targetText').disabled=true;$('targetPhoto').disabled=true;$('targetSearch').disabled=true;
  $('targetFeedback').textContent='입력한 사진·설명으로 검색 중… 완료 후 결과가 여기에 표시됩니다.';
 });
 async function updateTarget(){
  if(!targetSearching)return;
  const state=await api('state'),job=state.jobs.find(j=>j.id===targetJobId);
  if(!job||!['complete','failed','cancelled'].includes(job.status))return;
  targetSearching=false;$('targetCategory').disabled=false;$('targetText').disabled=false;$('targetPhoto').disabled=false;$('targetSearch').disabled=false;
  const candidate=job.search_result?.candidates?.[0];targetReady=job.status==='complete'&&!!candidate;
  $('targetFeedback').textContent=targetReady?'이번 집기 목표: '+candidate.name+' ('+candidate.id+') · 점수 '+Number(candidate.matching_score??candidate.similarity).toFixed(3)+' · 맞으면 시작 버튼을 누르세요.':'대상 검색 실패: '+(job.message||'등록 후보 없음');
 }
 $('start').onclick=()=>act(async()=>{
  if(!targetReady||!targetJobId)throw Error('이 화면에서 목표 사진·설명을 입력하고 대상 검색을 먼저 완료하세요.');
  await api('prototype/start',{search_job_id:targetJobId,simple_mode:$('simpleMode').checked,measure_only:$('measureOnly').checked,relaxed:$('relaxed').checked,approach_height_mm:Number($('approachHeight').value),grasp_height_mm:Number($('graspHeight').value)});
 });
 async function poll(){if(refreshing||document.hidden)return;refreshing=true;try{const s=await api('prototype/state'),a=s.action,m=s.manual,h=s.home;
 $('phase').textContent=(a.running?'진행 중 · ':'대기/정지 · ')+a.message+' · 장비 '+(m.connected?'연결됨':'미연결');
 $('registerGripper').disabled=a.running||!m.connected||!!m.active;
 $('openGripper').disabled=a.running||!m.connected||!!m.active||m.latched;
 $('connect').disabled=a.running||m.connected;$('start').disabled=a.running||!m.connected||!h.home||!!h.validation_error||targetSearching||!targetReady;$('home').disabled=a.running||!m.connected||!h.home||!!h.validation_error;$('saveHome').disabled=a.running||!m.connected||!!m.active;
 $('homeInfo').textContent=h.home?h.home.label+' · 저장 '+new Date(h.home.created*1000).toLocaleString('ko-KR')+' · '+(h.validation_error?'복귀 불가: '+h.validation_error:'현재 범위 검사 통과'):'준비자세 HOME이 없습니다.';$('homeInfo').className=h.validation_error?'warning':'';
 if(savingHome)$('saveHome').disabled=true;
 await updateTarget();
 if(s.plan)$('plan').textContent='검출 #'+s.plan.frame_id+' · 보관함 ['+fmt(s.plan.board_mm)+']mm · 접근 ['+fmt(s.plan.approach_xyz_mm)+']mm · 집기 ['+fmt(s.plan.grasp_xyz_mm)+']mm · 물품 긴 축 '+(s.plan.long_axis_robot_radians*180/Math.PI).toFixed(1)+'°'+(s.plan.opening_selection?' · 선택 개방 '+s.plan.opening_selection.percent+'% · '+(s.plan.opening_selection.verified?'실측 폭 확인':s.plan.opening_selection.warning):'');
 const d=s.position_diagnostic;
 if(d)$('positionDiagnostic').textContent='기록 '+d.trial_id+' · '+new Date(d.captured*1000).toLocaleString('ko-KR')+'\nIK 계산 오차 ['+fmt(d.ik_error.delta_mm)+']mm · 거리 '+d.ik_error.distance_mm.toFixed(1)+'mm\n관절 추종 오차 ['+fmt(d.following_error.delta_mm)+']mm · 거리 '+d.following_error.distance_mm.toFixed(1)+'mm\n검출 목표 대비 모델 위치 차이 ['+fmt(d.total_model_error.delta_mm)+']mm\n'+d.note+(d.observation?'\n이번 실측: 탑뷰 오른쪽 '+d.observation.board_delta_mm[0]+'mm / 위쪽 '+(-d.observation.board_delta_mm[1])+'mm · 보정 '+(d.observation.applied?'적용':'미적용')+(d.observation.planning_check?'\n보정 위치 경로: '+(d.observation.planning_check.reachable?'계산 통과':d.observation.planning_check.reason):''):'');
 const log=$('events');log.replaceChildren();[...a.events].reverse().forEach(e=>{const p=document.createElement('p');p.textContent=new Date(e.time*1000).toLocaleTimeString('ko-KR')+' · '+e.phase+' · '+e.message;log.append(p);});
 }catch(e){$('phase').textContent='서버 연결 오류: '+e.message;}finally{refreshing=false;}}
 async function edges(){if(edgeBusy||document.hidden)return;edgeBusy=true;try{const d=await api('prototype/edges');$('edgeInfo').textContent='왼쪽 간격 '+(d.left_gap_pixels==null?'미검출':d.left_gap_pixels.toFixed(1)+'px')+' / 오른쪽 '+(d.right_gap_pixels==null?'미검출':d.right_gap_pixels.toFixed(1)+'px')+' · '+(d.bilateral_contact_candidate?'양쪽 접촉 후보 (실제 접촉 미확정)':d.reason);$('armEdges').src='/api/prototype/arm.jpg?t='+Date.now();}catch(e){$('edgeInfo').textContent='영상 판정 불가: '+e.message;}finally{edgeBusy=false;}}
 document.addEventListener('keydown',e=>{if(e.key==='Escape'||e.code==='Space'&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)){e.preventDefault();stop();}});
 poll();edges();setInterval(poll,500);setInterval(edges,750);

 async function refreshCategories(){try{const data=await api('categories');const picker=$('targetCategory');if(!picker)return;const selected=picker.value;picker.replaceChildren(new Option('전체 등록 품목',''),...data.items.map(r=>new Option(r.name+(r.enabled?'':' (검출 꺼짐)'),r.id)));if(data.items.some(r=>r.id===selected))picker.value=selected;}catch(e){console.warn('카테고리 조회 실패',e)}}
 refreshCategories();setInterval(refreshCategories,10000);
})();
