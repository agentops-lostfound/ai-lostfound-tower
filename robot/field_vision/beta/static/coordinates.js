(() => {
 const panel=document.createElement('section');panel.className='panel form-panel';
 panel.innerHTML=`<h3>보관함 좌표 · 4점 기준</h3><p>좌상 → 우상 → 우하 → 좌하 순서입니다. 임시 모드는 가상 꼭짓점을 사용하며 실제 마커를 검출한 것이 아닙니다.</p><label>기준 모드 <select id="coordMode"><option value="temporary">임시 4점 · 마커 없이 테스트</option><option value="aruco">실제 ArUco 4개 · 중심 기준</option></select></label><label>ArUco 사전 <select id="coordDictionary">${['DICT_4X4_1000','DICT_5X5_1000','DICT_6X6_1000','DICT_7X7_1000','DICT_ARUCO_ORIGINAL'].map(v=>`<option>${v}</option>`).join('')}</select></label><label>ID 순서 (좌상,우상,우하,좌하)<input id="coordIds" value="0,1,2,3"></label><div class="field-pair"><label>基準 가로 mm (선택)<input id="coordWidth" type="number" min="1" placeholder="未입력 시 0~1 좌표만 사용"></label><label>기준 세로 mm (선택)<input id="coordHeight" type="number" min="1"></label></div><p>실제 마커 모드의 치수는 마커 중심 사이 거리입니다. 임의 치수를 넣으면 실제 mm 위치가 아닙니다.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button id="coordRefresh" class="button secondary">현재 영상·상태 갱신</button><button id="coordPick" class="button secondary">임시 꼭짓점 4개 다시 지정</button><button id="coordSave" class="button primary">좌표 기준 저장</button><button id="coordDefault" class="button secondary">임시 기본값 불러오기</button></div><p id="coordMessage" role="status"></p><canvas id="coordCanvas" style="width:100%;max-width:960px;touch-action:none;cursor:crosshair"></canvas><p>지정 모드가 아닐 때 영상을 클릭하면 저장된 기준으로 좌표를 시험합니다. 원점은 좌상, 오른쪽이 +X, 아래쪽이 +Y입니다.</p>`;
 panel.innerHTML=panel.innerHTML.replace('基準','기준').replace('未입력','미입력');
 document.getElementById('tab-settings').append(panel);
 const $=id=>document.getElementById(id),canvas=$('coordCanvas'),ctx=canvas.getContext('2d'),image=new Image();
 let config,points=[],picking=false,drawPoints=[];
 const status=document.createElement('div');status.id='coordClickStatus';status.style.cssText='padding:12px;background:#23382f;color:#ffc65a;font-weight:bold;position:sticky;bottom:10px;z-index:5';canvas.after(status);const message=t=>{$('coordMessage').textContent=t;status.textContent=t;};
 function draw(){
 if(!image.naturalWidth)return;
 ctx.drawImage(image,0,0,canvas.width,canvas.height);
 const p=picking?points:drawPoints;if(!p.length)return;
 ctx.strokeStyle='#ffc65a';ctx.lineWidth=5;ctx.beginPath();
 p.forEach(([x,y],i)=>{const a=x*canvas.width,b=y*canvas.height;i?ctx.lineTo(a,b):ctx.moveTo(a,b);});
 if(p.length===4)ctx.closePath();ctx.stroke();
 p.forEach(([x,y],i)=>{const a=x*canvas.width,b=y*canvas.height;ctx.fillStyle='#ffc65a';ctx.beginPath();ctx.arc(a,b,13,0,2*Math.PI);ctx.fill();ctx.fillStyle='#101b15';ctx.font='bold 20px sans-serif';ctx.textAlign='center';ctx.fillText(String(i+1),a,b+7);ctx.textAlign='left';ctx.fillStyle='#101b15';ctx.fillRect(a+18,b-20,95,29);ctx.fillStyle='#ffc65a';ctx.font='bold 17px sans-serif';ctx.fillText(['좌상','우상','우하','좌하'][i],a+24,b);});
 }
 function hydrate(c){config=c;$('coordMode').value=c.mode;$('coordDictionary').value=c.dictionary;$('coordIds').value=c.ids.join(',');$('coordWidth').value=c.width_mm??'';$('coordHeight').value=c.height_mm??'';points=c.points;drawPoints=c.mode==='temporary'?points:[];picking=false;draw();}
 async function refresh(){try{
 const response=await (window.visionFetch||fetch)('/api/coordinates');const r=await response.json();if(!response.ok)throw Error(r.detail||'좌표 조회 실패');
 hydrate(r.config);
 image.onload=()=>{canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
 drawPoints=r.config.mode==='aruco'?(r.status.ready?r.status.corners_pixels.map(([x,y])=>[x/canvas.width,y/canvas.height]):[]):r.config.points;draw();};
 image.src='/api/region/frame.jpg?t='+Date.now();
 message((r.config.mode==='temporary'?'임시 기준 · ':'실제 마커 기준 · ')+(r.status.ready?(r.config.mode==='aruco'?'마커 4개 검출 · ID '+r.config.ids.join(' → '):'좌표 변환 준비됨'):'미준비: '+r.status.reason+' · 이전 임시 테두리는 사용하지 않습니다.'));
 }catch(e){drawPoints=[];draw();message(e.message);}}

 image.onload=()=>{canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;draw();};
 $('coordRefresh').onclick=refresh;
 $('coordPick').onclick=()=>{picking=true;points=[];$('coordMode').value='temporary';message('선택 시작 0/4 · 바로 아래 노란 테두리 설정 영상에서 1번 좌상을 클릭하세요.');canvas.style.outline='4px solid #ffc65a';canvas.scrollIntoView({block:'center',behavior:'smooth'});draw();};
 canvas.onclick=async e=>{const r=canvas.getBoundingClientRect(),p=[(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height];if(picking){points.push(p);message('선택 '+points.length+'/4 · '+(points.length<4?'다음: '+['좌상','우상','우하','좌하'][points.length]:'네 점 선택 완료'));draw();if(points.length===4){picking=false;drawPoints=points;draw();canvas.style.outline='';message('4점 선택 완료 · 좌표 기준 저장을 누르세요.');}return;}try{const res=await (window.visionFetch||fetch)('/api/coordinates/point',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({point:[p[0]*canvas.width,p[1]*canvas.height]})});const v=await res.json();if(!res.ok)throw Error(v.detail);message((v.temporary?'임시 기준 · ':'실제 마커 기준 · ')+(v.inside?'영역 내부':'영역 외부')+' · 정규화 '+v.normalized.map(x=>x.toFixed(3)).join(', ')+(v.mm?' · mm '+v.mm.map(x=>x.toFixed(1)).join(', '):' · 실측 치수 미입력'));}catch(e){message(e.message);}};
 $('coordSave').onclick=async()=>{try{if(picking||points.length!==4)throw Error('네 꼭짓점을 모두 선택하세요. 현재 '+points.length+'/4');const c={mode:$('coordMode').value,dictionary:$('coordDictionary').value,ids:$('coordIds').value.split(',').map(v=>Number(v.trim())),points,width_mm:$('coordWidth').value?Number($('coordWidth').value):null,height_mm:$('coordHeight').value?Number($('coordHeight').value):null};const r=await (window.visionFetch||fetch)('/api/coordinates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(c)});const v=await r.json();if(!r.ok)throw Error(v.detail);await refresh();message('저장 완료 · '+$('coordMessage').textContent+' · 이동 없음');}catch(e){message('저장 실패: '+e.message);}};
 $('coordDefault').onclick=()=>{hydrate({mode:'temporary',points:[[.12,.16],[.91,.16],[.93,.86],[.09,.86]],dictionary:'DICT_4X4_1000',ids:[0,1,2,3],width_mm:null,height_mm:null});message('임시 기본값을 불러왔습니다. 저장하면 적용됩니다.');};
 $('coordMode').onchange=()=>{if($('coordMode').value==='aruco'){drawPoints=[];draw();message('실제 모드 선택 · 좌표 기준 저장 후 실제 마커 위치를 불러옵니다.');}};
 refresh();
})();
