'use strict';
let auditedSnapshot=null;
globalThis.CollectionAudit={sync(data,working,valid){
 $('auditRun').disabled=working||!valid;
 if(auditedSnapshot&&(!valid||data!==auditedSnapshot)){$('auditResult').hidden=true;auditedSnapshot=null;$('auditStatus').textContent='최신 기록을 확인한 뒤 다시 점검해주세요.';}
}};
$('auditRun').onclick=async()=>{
 if(busy||!fresh)return;busy=true;render();$('auditResult').hidden=true;$('auditStatus').textContent='가상 기록을 대조하고 있습니다…';
 try{const result=await api('/collection-audit');if(result.mode!=='demo_sqlite'||result.revision!==snapshot.revision)throw Error('시연 데이터가 변경되었습니다. 새로고침 후 다시 점검해주세요.');
  auditedSnapshot=snapshot;$('auditSummary').textContent=`물건 ${result.counts.items}개 · 회수 ${result.counts.collections}건 · 상태 이력 ${result.counts.events}건 · 불일치 ${result.issue_count}건`;
  $('auditTime').textContent='점검 시각 '+timeLabel(result.checked_at)+' · '+result.scope;
  $('auditIssues').replaceChildren();for(const issue of result.issues){const row=el('div',undefined,'alert-row');row.append(el('strong',issue.message),el('span',[issue.item_id,issue.collection_id?'회수 #'+issue.collection_id:''].filter(Boolean).join(' · ')));$('auditIssues').append(row);}
  if(result.truncated)$('auditIssues').append(el('p','불일치가 많아 처음 50건만 표시했습니다.','hint'));
  $('auditResult').hidden=false;$('auditStatus').textContent=result.status==='ok'?'가상 기록 사이의 불일치가 발견되지 않았습니다.':'확인이 필요한 기록이 있습니다. 자동 수정하지 않았습니다.';
 }catch(error){$('auditResult').hidden=true;$('auditStatus').textContent=error.message;}
 finally{busy=false;render();}
};
CollectionAudit.sync(snapshot,busy,fresh);
