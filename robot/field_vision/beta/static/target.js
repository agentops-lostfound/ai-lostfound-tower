(() => {
  const panel=document.createElement('section');panel.className='panel form-panel';
  panel.innerHTML='<h3>등록 물품 위치 찾기 · 개발 테스트</h3><p>등록 ID를 선택하면 현재 탑뷰를 분석해 위치 후보를 찾습니다. 정확도 보완 전이며 로봇은 이동하지 않습니다.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><select id="targetSelect" aria-label="찾을 등록 물품"></select><button id="targetReload" class="button secondary">물품 목록 갱신</button><button id="targetLocate" class="button primary">선택 물품 찾기 ↗</button></div><p id="targetMessage" role="status">감시·진행 작업을 중단하고 실행하세요.</p><div id="targetDetails"></div>';
  const live=document.getElementById('tab-live');live.prepend(panel);
  let jobId=null,rendered=null;
  const flow=document.createElement('label');flow.className='check';flow.innerHTML='<input id="searchThenLocate" type="checkbox" checked>글·사진 검색 후 1순위 후보를 탑뷰에서 자동으로 찾기 (개발용 · 일치 미확정)';
  document.querySelector('#tab-search .search-panel').append(flow);
  document.getElementById('searchText').placeholder='예: 분홍색 꽃무늬 핸드크림';
  document.querySelector('#tab-search .search-divider span').textContent='사진으로 검색 · 위 특징을 함께 입력하면 색상 비교에도 반영합니다';
  window.addEventListener('search-target',async event=>{
    const candidate=event.detail;
    if(!candidate){message('검색된 등록 물품이 없어 탑뷰 찾기를 실행하지 않았습니다.');return;}
    message('검색 1순위 후보를 탑뷰에서 찾는 중…');document.getElementById('targetDetails').textContent='';
    document.querySelector('[data-tab="live"]').click();
    try{
      const r=await (window.visionFetch||fetch)('/api/target/locate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_id:candidate.id})});
      const data=await r.json();if(!r.ok)throw Error(data.detail||'대상 찾기 실패');
      jobId=data.id;rendered=null;
      message('글·사진 검색 1순위 '+candidate.name+' → 탑뷰 위치 분석 중…');
    }catch(e){message('탑뷰 연결 실패: '+e.message);}
  });
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const message=t=>document.getElementById('targetMessage').textContent=t;
  async function registry(){try{const rows=await(await (window.visionFetch||fetch)('/api/registry')).json();const select=document.getElementById('targetSelect'),old=select.value;select.innerHTML=rows.map(r=>`<option value="${esc(r.id)}">${esc(r.id)} · ${esc(r.name)}</option>`).join('');if(rows.some(r=>r.id===old))select.value=old;}catch(e){message(e.message);}}
  document.getElementById('targetReload').onclick=registry;
  document.getElementById('targetLocate').onclick=async()=>{const button=document.getElementById('targetLocate');button.disabled=true;try{message('현재 탑뷰에서 선택 물품을 찾고 있습니다…');document.getElementById('targetDetails').textContent='';const r=await (window.visionFetch||fetch)('/api/target/locate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_id:document.getElementById('targetSelect').value})});const data=await r.json();if(!r.ok)throw Error(data.detail||'요청 실패');jobId=data.id;rendered=null;}catch(e){message('실행 실패: '+e.message);}finally{button.disabled=false;}};
  async function poll(){if(!jobId||rendered===jobId)return;try{const s=await(await (window.visionFetch||fetch)('/api/state')).json();const job=s.jobs.find(j=>j.id===jobId);if(!job)return;if(['failed','cancelled'].includes(job.status)){message('찾기 중단: '+job.message);rendered=jobId;return;}if(job.status!=='complete')return;rendered=jobId;const r=job.target_result;if(r?.board_coordinates){const c=r.board_coordinates;r.coordinateLabel=c.status==='unavailable'?'보관함 좌표 미준비: '+c.reason:(c.temporary?'임시 4점 기준':'실제 ArUco 기준')+' / '+(c.inside?'영역 내부':'영역 외부')+' / 정규화 '+c.normalized.map(v=>v.toFixed(3)).join(', ')+(c.mm?' / mm '+c.mm.map(v=>v.toFixed(1)).join(', '):' / 실측 치수 미입력');}if(!r){message('위치 결과가 없습니다. 다시 실행하세요.');return;}if(!r.best){message(r.target_id+' · 비교 가능한 물체를 찾지 못했습니다.');return;}message(r.target_id+' · 위치 후보 표시 완료 · 일치 미확정 / 로봇 이동 없음');document.getElementById('targetDetails').innerHTML=`<p>${esc(r.coordinateLabel||'보관함 좌표 없음')}</p><p>촬영 ${new Date(r.captured*1000).toLocaleTimeString('ko-KR')} · 전체 원본 영상 기준 픽셀 좌표 (현재 위치와 다를 수 있음)</p><table><thead><tr><th>후보</th><th>점수</th><th>중심 (x, y)</th><th>박스</th></tr></thead><tbody>${r.candidates.map((c,i)=>`<tr><td>${i===0?'선택 후보':'대안 후보'} #${c.index+1}</td><td>${c.matching_score.toFixed(3)}</td><td>${c.center.join(', ')}</td><td>${c.bbox.join(', ')}</td></tr>`).join('')}</tbody></table><img src="${esc(job.result.snapshot)}" style="width:100%;max-width:680px" alt="대상 찾기 당시 검출 사진"><p>라이브의 TARGET 표시는 추적이 유지되는 동안 나타납니다. 사진의 #번호와 위 선택 후보 번호를 비교하세요.</p>`;}catch(e){message(e.message);}}
  registry();setInterval(poll,1500);
})();
