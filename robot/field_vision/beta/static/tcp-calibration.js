(()=>{
 const $=id=>document.getElementById(id);let busy=false,referenceValid=false,moving=false,lastMove=null,refreshId=0;
 const fmt=a=>a.map(v=>Number(v).toFixed(1)).join(', ');
 async function api(path,data){const r=await (window.visionFetch||fetch)('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw Error(d.detail||'요청 실패');return d;}
 function render(s){
  const diversity=s.pose_diversity; $('poseDiversity').textContent=diversity?`등록 ${diversity.count}개 · ${diversity.ready?'기울기 분리 가능':'기울기 다양성 부족 · 앞뒤·좌우 기울기를 바꿔 추가하세요'} · 조건수 ${diversity.condition_number?.toFixed(1)||'미계산'}`:'상태 확인 필요';
  $('active').textContent=s.validation_error?'보정 무효: '+s.validation_error:s.active?'공통 보정 적용 중 · 별도 검증 '+s.active.verification.error_mm.toFixed(1)+'mm · 모든 물품 공통':'공통 실측 보정 미적용 · 기존 임시 기준';
  const fit=s.draft.fit;$('activate').disabled=!fit?.verified||busy;
  $('fit').textContent=fit?'베이스 평행 이동 ['+fmt(fit.base_translation_mm)+']mm\n집게 중심의 로컬 오프셋 ['+fmt(fit.tcp_local_mm)+']mm\n정합 RMS '+fit.rms_mm.toFixed(2)+'mm · 최대 '+fit.max_error_mm.toFixed(2)+'mm\n'+(fit.verified?'별도 검증 통과 '+fit.verification.error_mm.toFixed(2)+'mm':'별도 지점 검증 필요'):'미계산 · 최소 4개 자세 필요';
  $('samples').replaceChildren();s.draft.samples.forEach((sample,index)=>{const tr=document.createElement('tr');const angle=Math.acos(Math.max(-1,Math.min(1,-sample.rotation[2][2])))*180/Math.PI;
   [index+1,fmt(sample.board_mm)+' / '+Number(sample.height_mm).toFixed(1),angle.toFixed(1)+'°'].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});
   const td=document.createElement('td'),button=document.createElement('button');button.textContent='삭제';button.dataset.sampleDelete=sample.id;button.disabled=busy||moving;button.onclick=()=>perform('delete',{sample_id:sample.id});td.append(button);tr.append(td);$('samples').append(tr);
  });
 }
 async function perform(operation,extra={}){
  if(busy)return;
  if(['reset','disable'].includes(operation)&&!confirm(operation==='reset'?'등록 목록을 새로 시작할까요? 현재 적용 보정은 유지됩니다.':'공통 보정을 해제하고 기존 임시 기준으로 돌아갈까요?'))return;
  busy=true;document.querySelectorAll('[data-operation]').forEach(b=>b.disabled=true);referenceButtons();$('feedback').textContent='처리 중…';
  try{const result=await api('prototype/tcp',{operation,board_mm:[Number($('x').value),Number($('y').value)],height_mm:Number($('z').value),...extra});render(result);$('feedback').textContent='✓ '+({capture:'기준 자세 등록 완료',fit:'공통 오차 계산 완료 · 별도 지점 검증을 진행하세요',verify:'별도 지점 검증 통과',activate:'모든 물품 공통 위치 보정 적용 완료',reset:'새 보정 목록 준비',disable:'공통 보정 해제 완료',delete:'기준 자세 삭제 완료'}[operation]);}
  catch(e){$('feedback').textContent='✕ '+e.message;}
  finally{busy=false;document.querySelectorAll('[data-operation]').forEach(b=>b.disabled=false);referenceButtons();try{render(await api('prototype/tcp'));}catch(e){$('feedback').textContent+='\n조회 실패: '+e.message;}}
 }
 document.querySelectorAll('[data-operation]').forEach(b=>b.onclick=()=>perform(b.dataset.operation));
 $('stop').onclick=async()=>{try{await api('prototype/stop',{});$('feedback').textContent='STOP 요청 완료';}catch(e){$('feedback').textContent=e.message;}};
 document.addEventListener('keydown',e=>{if(e.key==='Escape')$('stop').click();});
 function referenceQuery(){return 'point='+encodeURIComponent($('referencePoint').value)+'&height_mm='+encodeURIComponent($('referenceHeight').value);}
 function referenceButtons(){
  document.querySelectorAll('[data-sample-delete]').forEach(b=>b.disabled=busy||moving);
  $('referenceMove').disabled=busy||moving||!referenceValid;
  for(const id of ['referenceObserve','referenceVerify'])$(id).disabled=busy||moving||!lastMove?.finished||lastMove.key!==$('referencePoint').value;
 }
 async function referenceRefresh(){
  const id=++refreshId;referenceValid=false;referenceButtons();
  try{const r=await api('prototype/tcp/reference?'+referenceQuery());if(id!==refreshId)return;referenceValid=true;lastMove=r.last_move;
   $('referenceInfo').textContent='ArUco '+r.target.detected_ids.length+'개 검출 · 저장 치수 '+r.target.width_mm.toFixed(1)+' × '+r.target.height_board_mm.toFixed(1)+'mm\n목표 보관함 ['+fmt(r.target.board_mm)+']mm · 로봇 ['+fmt(r.target.target_robot_mm)+']mm\n'+r.target.note;
   $('x').value=r.target.board_mm[0];$('y').value=r.target.board_mm[1];$('top').src='/api/prototype/tcp/reference.jpg?'+referenceQuery()+'&t='+Date.now();
  }catch(e){if(id!==refreshId)return;$('referenceInfo').textContent='기준점 준비 불가: '+e.message;}
  finally{if(id===refreshId)referenceButtons();}
 }
 $('referenceRefresh').onclick=referenceRefresh;
 for(const id of ['referencePoint','referenceHeight'])$(id).onchange=()=>{for(const field of ['observedRight','observedUp','observedHeight'])$(field).value='';referenceRefresh();};
 $('referenceMove').onclick=async()=>{
  if(busy||moving||!referenceValid)return;busy=true;referenceButtons();$('feedback').textContent='기준점 경로 계산·이동 요청 중…';
  try{await api('prototype/tcp/reference',{operation:'move',point:$('referencePoint').value,height_mm:Number($('referenceHeight').value)});moving=true;$('feedback').textContent='기준점 이동 요청 접수 · 종료까지 기다려주세요.';for(const field of ['observedRight','observedUp','observedHeight'])$(field).value='';}
  catch(e){$('feedback').textContent='기준점 이동 실패: '+e.message;}finally{busy=false;referenceButtons();}
 };
 async function observe(verification){
  if(busy||moving||!lastMove?.finished)return;
  if(['observedRight','observedUp','observedHeight'].some(id=>$(id).value.trim()==='')){$('feedback').textContent='실물 차이와 실제 높이를 모두 입력하세요. 차이가 없으면 0을 입력합니다.';return;}
  busy=true;referenceButtons();
  try{await api('prototype/tcp/reference',{operation:verification?'observe_verify':'observe',move_id:lastMove.move_id,required_board_motion_mm:[Number($('observedRight').value),-Number($('observedUp').value)],actual_height_mm:Number($('observedHeight').value)});render(await api('prototype/tcp'));$('feedback').textContent=verification?'✓ 별도 실물 검증 통과':'✓ 실물 관측 등록 완료 · 목표 좌표를 실측값으로 복사하지 않았습니다.';}
  catch(e){$('feedback').textContent='실물 관측 등록 실패: '+e.message;}finally{busy=false;referenceButtons();}
 }
 $('referenceObserve').onclick=()=>observe(false);$('referenceVerify').onclick=()=>observe(true);
 let polling=false;async function motionState(){if(polling||document.hidden)return;polling=true;try{const r=await api('prototype/state');moving=r.action.running;$('referenceMoveInfo').textContent=(moving?'진행 중 · ':'대기/정지 · ')+r.action.message;
  if(!moving){const result=await api('prototype/tcp/reference?'+referenceQuery());lastMove=result.last_move;if(lastMove?.finished)$('referenceMoveInfo').textContent+='\n최근 기준점 이동: '+(lastMove.status==='arrived'?'이동·50% 개방 완료':lastMove.error||'정지')+' · 실물 정합 미확정';}
  if(lastMove?.feedback_model_pose){const p=lastMove.feedback_model_pose.xyz_mm,d=p.map((v,i)=>v-lastMove.target_robot_mm[i]);$('referenceFeedbackInfo').textContent='관절 피드백의 모델 위치 ['+fmt(p)+']mm\n계산 목표 대비 차이 ['+fmt(d)+']mm · 거리 '+Math.hypot(...d).toFixed(1)+'mm\n실제 집게 중심의 실측 좌표가 아닙니다.';}
  referenceButtons();
 }catch(e){$('referenceMoveInfo').textContent='상태 확인 실패: '+e.message;referenceValid=false;referenceButtons();}finally{polling=false;}}
 $('top').onerror=()=>{if($('top').src.includes('/tcp/reference.jpg')){$('referenceImageStatus').textContent='목표 표시 불가 · 원본 영상을 표시합니다. 마커 4개를 확인하세요.';$('top').src='/api/cameras/top/frame.jpg?t='+Date.now();}};
 $('top').onload=()=>{if($('top').src.includes('/tcp/reference.jpg'))$('referenceImageStatus').textContent='노랑: 자동 계산한 목표의 마커 평면 투영점';};
 referenceRefresh();motionState();setInterval(motionState,1000);
 api('prototype/tcp').then(render).catch(e=>$('feedback').textContent='상태 조회 실패: '+e.message);
 let frameBusy=false;async function frames(){if(frameBusy||document.hidden)return;frameBusy=true;try{$('arm').src='/api/prototype/arm.jpg?t='+Date.now();$('top').src='/api/prototype/tcp/reference.jpg?'+referenceQuery()+'&t='+Date.now();}finally{frameBusy=false;}}
 frames();setInterval(frames,1000);
})();
