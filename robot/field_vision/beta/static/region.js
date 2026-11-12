(() => {
  const panel=document.createElement('section');panel.className='panel form-panel';
  panel.innerHTML=`<h3>탑뷰 보관함 분석 영역</h3><p>초록색 판 자동 찾기 또는 영상에서 드래그로 지정하세요. 감시·분석을 중단한 뒤 적용합니다. 영역은 탑뷰에만 적용됩니다.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button type="button" class="button secondary" data-region="auto">초록색 판 자동 설정</button><button type="button" class="button secondary" id="regionRefresh">현재 영상 갱신</button><button type="button" class="button primary" data-region="manual">드래그 영역 적용</button><button type="button" class="button secondary" data-region="default">기본 영역으로 초기화</button><button type="button" class="button secondary" data-region="clear">전체 화면 사용</button></div><p id="regionMessage" role="status">기본값은 현재 HD 탑뷰의 보관함 위치입니다. 카메라가 이동하면 다시 설정하세요.</p><canvas id="regionCanvas" style="width:100%;max-width:960px;touch-action:none;cursor:crosshair"></canvas><h4>저장된 분석 영역 · 실시간 미리보기</h4><img id="regionPreview" style="width:100%;max-width:640px" alt="저장된 보관함 분석 영역">`;
  document.getElementById('tab-settings').append(panel);
  const markerSetting=document.createElement('label');markerSetting.className='check';
  markerSetting.innerHTML='<input type="checkbox" id="excludeAruco" checked>ArUco 위치 마커를 물품 검출에서 제외 (탑뷰 전용)';
  document.getElementById('settingsForm').prepend(markerSetting);
  (window.visionFetch||fetch)('/api/state').then(r=>r.json()).then(s=>{document.getElementById('excludeAruco').checked=s.settings.exclude_aruco!==false;});
  const canvas=document.getElementById('regionCanvas'),ctx=canvas.getContext('2d'),img=new Image();
  let selected=null,start=null;
  const message=t=>document.getElementById('regionMessage').textContent=t;
  function draw(){if(!img.naturalWidth)return;ctx.drawImage(img,0,0,canvas.width,canvas.height);if(selected){const [x,y,r,b]=selected;ctx.fillStyle='#0008';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,x*canvas.width,y*canvas.height,(r-x)*canvas.width,(b-y)*canvas.height,x*canvas.width,y*canvas.height,(r-x)*canvas.width,(b-y)*canvas.height);ctx.strokeStyle='#00ffc0';ctx.lineWidth=3;ctx.strokeRect(x*canvas.width,y*canvas.height,(r-x)*canvas.width,(b-y)*canvas.height);}}
  async function refresh(){try{const s=await(await (window.visionFetch||fetch)('/api/state')).json();selected=s.settings.roi;img.src='/api/region/frame.jpg?t='+Date.now();preview();}catch(e){message(e.message);}}
  function preview(){document.getElementById('regionPreview').src='/api/region/frame.jpg?crop=true&t='+Date.now();}
  img.onload=()=>{canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;draw();};img.onerror=()=>message('탑뷰 영상이 없습니다. 카메라 연결을 확인하세요.');
  function point(e){const r=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];}
  canvas.onpointerdown=e=>{start=point(e);canvas.setPointerCapture(e.pointerId);};
  canvas.onpointermove=e=>{if(!start)return;const p=point(e);selected=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];draw();};
  canvas.onpointerup=()=>{start=null;message('선택 영역을 확인한 뒤 「드래그 영역 적용」을 누르세요.');};
  canvas.onpointercancel=()=>{start=null;};
  document.getElementById('regionRefresh').onclick=refresh;
  panel.querySelectorAll('[data-region]').forEach(button=>button.onclick=async()=>{button.disabled=true;message('영역 적용 중…');try{if(button.dataset.region==='manual'&&(!selected||selected[2]-selected[0]<.02||selected[3]-selected[1]<.02))throw Error('영상에서 충분한 크기의 영역을 드래그하세요.');const r=await (window.visionFetch||fetch)('/api/region',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:button.dataset.region,roi:selected})});const v=await r.json();if(!r.ok)throw Error(v.detail||'영역 저장 실패');selected=v.roi;document.getElementById('roi').value=selected?JSON.stringify(selected):'';draw();preview();message('저장 완료 · '+(selected?'테두리 내부만 탐지합니다.':'전체 영상을 탐지합니다.'));}catch(e){message('적용 실패: '+e.message);}finally{button.disabled=false;}});
  setInterval(()=>{if(document.getElementById('tab-settings').classList.contains('active'))preview();},1500);
  refresh();
})();
