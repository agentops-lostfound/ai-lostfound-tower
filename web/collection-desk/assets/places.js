'use strict';
let placeData=null,placeOffset=0,placeLoading=false,placeAttempted=false;
function drawPlaces(){
 const locked=busy||!fresh||placeLoading;
 $('placeMachine').disabled=locked;$('placeReload').disabled=locked;$('placeSave').disabled=locked||!placeData;
 $('placePrev').disabled=locked||!placeData||placeOffset===0;$('placeNext').disabled=locked||!placeData||placeData.next_offset===null;
 if(!placeData){$('placeList').replaceChildren();$('placeScope').textContent='';$('placePage').textContent='';return;}
 $('placeScope').textContent=placeData.line+' '+placeData.station+'역 · 같은 역의 장소만 추천합니다.';
 $('placePage').textContent=`전체 ${placeData.total}곳 · ${placeData.total?placeOffset+1:0}–${Math.min(placeOffset+5,placeData.total)}번째`;
 const list=$('placeList');list.replaceChildren();
 for(const place of placeData.places){const line=el('div',undefined,'item-row'),text=el('span');text.append(el('strong',place.label),el('small',place.line+' '+place.station+'역'));line.append(text);list.append(line);}
 if(!placeData.places.length)list.append(el('div','이 목록에 장소가 없습니다. 이전 목록을 확인하거나 새 장소를 추가하세요.','empty'));
}
async function fetchPlaces(){
 if(placeLoading||!fresh)return false;placeAttempted=true;placeLoading=true;drawPlaces();$('placeStatus').textContent='장소 목록을 확인하고 있습니다…';
 try{const result=await api('/places?machine_id='+encodeURIComponent($('placeMachine').value)+'&offset='+placeOffset);if(result.mode!=='demo_sqlite'||result.revision!==snapshot.revision)throw Error('시연 데이터가 변경되었습니다. 위쪽 새로고침 후 다시 조회해주세요.');placeData=result;$('placeStatus').textContent='이 역의 가상 장소 목록입니다.';return true;}
 catch(error){placeData=null;$('placeList').replaceChildren();$('placePage').textContent='';$('placeStatus').textContent=error.message;return false;}
 finally{placeLoading=false;drawPlaces();}
}
globalThis.CollectionPlaces={sync(data,working,valid){
 if(placeData&&data&&placeData.revision!==data.revision){placeData=null;placeOffset=0;placeAttempted=false;$('placeLabel').value='';$('placeList').replaceChildren();$('placeStatus').textContent='시연이 초기화되었습니다. 목록을 다시 불러와주세요.';}
 drawPlaces();
 if(valid&&!working&&!placeLoading&&!placeData&&!placeAttempted)fetchPlaces();
}};
$('placeMachine').onchange=()=>{if(busy||!fresh)return;placeOffset=0;placeData=null;fetchPlaces();};
$('placeReload').onclick=()=>{if(!busy&&fresh)fetchPlaces();};
$('placePrev').onclick=()=>{if(busy||!fresh||placeLoading)return;placeOffset=Math.max(0,placeOffset-5);fetchPlaces();};
$('placeNext').onclick=()=>{if(busy||!fresh||placeLoading||!placeData||placeData.next_offset===null)return;placeOffset=placeData.next_offset;fetchPlaces();};
$('placeForm').onsubmit=async event=>{
 event.preventDefault();if(busy||!fresh||placeLoading||!placeData)return;const label=$('placeLabel').value.trim();if(!label)return;
 busy=true;render();$('placeStatus').textContent='장소를 저장하고 있습니다…';
 try{const result=await api('/places',{line:placeData.line,station:placeData.station,label});placeOffset=result.page_offset;$('placeLabel').value='';const loaded=await fetchPlaces();$('placeStatus').textContent=loaded?(result.created?'장소를 추가했습니다. 해당 목록에서 확인하세요.':'이미 등록된 장소입니다. 기존 목록을 표시합니다.'):'장소 저장은 완료했지만 목록 갱신에 실패했습니다. 목록 새로고침을 눌러주세요.';}
 catch(error){$('placeStatus').textContent=error.message;if(error.code==='stale_demo'){failed(error,null);try{await load();}catch{/* Require refresh before writing. */}}}
 finally{busy=false;render();}
};
CollectionPlaces.sync(snapshot,busy,fresh);
// The initial desk request is asynchronous. The reload button is enabled once it finishes.
if(fresh)fetchPlaces();
