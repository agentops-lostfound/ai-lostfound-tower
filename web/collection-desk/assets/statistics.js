'use strict';
let statsRevision=null;
const statsButtons=['statsSend','statsExampleA','statsExampleAll','statsExampleYesterday'];
globalThis.CollectionStats={sync(data,working,valid){
 for(const id of statsButtons)$(id).disabled=working||!valid;
 if(statsRevision&&data&&statsRevision!==data.revision){$('statsResult').hidden=true;statsRevision=null;$('statsStatus').textContent='시연 데이터가 초기화되어 이전 통계를 지웠습니다. 다시 조회해주세요.';}
}};
for(const [id,question] of [['statsExampleA','오늘 등록기계 A에 들어온 USB 몇 개?'],['statsExampleAll','오늘 전체 물건 접수 건수 알려줘'],['statsExampleYesterday','어제 전체 물건 접수 건수 알려줘']]){
 $(id).onclick=()=>{if(busy||!fresh)return;$('statsQuestion').value=question;$('statsForm').requestSubmit();};
}
$('statsQuestion').oninput=()=>{$('statsResult').hidden=true;statsRevision=null;$('statsStatus').textContent='질문을 수정했습니다. 통계 조회를 눌러주세요.';};
$('statsForm').onsubmit=async event=>{
 event.preventDefault();if(busy||!fresh)return;const question=$('statsQuestion').value.trim();if(!question)return;
 busy=true;render();$('statsResult').hidden=true;statsRevision=null;$('statsStatus').textContent='통계 뷰에서 접수 건수를 확인하고 있습니다…';
 try{
  const result=await api('/statistics/questions',{question});
  if(result.database_mode!=='demo_sqlite'||!Number.isSafeInteger(result.count)||result.count<0||result.revision!==snapshot.revision)throw Error('통계 결과의 시연 상태를 확인하지 못했습니다.');
  statsRevision=result.revision;$('statsCount').textContent=result.count+'건';$('statsAnswer').textContent=result.answer;
  $('statsDay').textContent=result.filters.day;$('statsMachine').textContent=result.filters.machine_id||'전체 등록기계';$('statsCategory').textContent=result.filters.category||'전체 품목';$('statsTime').textContent=timeLabel(new Date());
  $('statsRange').textContent=`조회 범위: ${result.filters.start_inclusive} 이상 ~ ${result.filters.end_exclusive} 미만 (한국 시간)`;
  $('statsSql').textContent=result.sql;$('statsParams').textContent='매개변수: '+JSON.stringify(result.parameters);$('statsSource').textContent='조회 대상: '+result.source;
  $('statsResult').hidden=false;$('statsStatus').textContent=result.count?'조회했습니다. 조건과 집계 근거를 확인하세요.':'조회 조건에 맞는 접수 기록이 0건입니다.';
 }catch(error){
  $('statsResult').hidden=true;$('statsStatus').textContent=error.message;
  if(error.status!==422){failed(error,null);try{await load();}catch{/* Collection controls remain locked until data is fresh. */}}
 }finally{busy=false;render();}
};
CollectionStats.sync(snapshot,busy,fresh);
