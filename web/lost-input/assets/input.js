
const $=id=>document.getElementById(id);
let proposal=null,confirmedSearchContext=null,inputRevision=0,inputBusy=false;
const metadataFields=['lost_date','lost_line','lost_station'];
// Include cleared values so confirming never silently restores the old metadata.
const meta=()=>Object.fromEntries(metadataFields.map(k=>[k,$(k).value.trim()]));
function notice(message,error=false){$('notice').className=error?'notice error':'notice';$('notice').textContent=message;}
function invalidateInput(sourceChanged=false){
 inputRevision++;setConfirmedSearch(null);
 if(sourceChanged){proposal=null;$('review').hidden=true;$('transcript').textContent='';}
 notice(inputBusy?'입력이 바뀌었습니다. 처리 중인 결과는 적용하지 않습니다. 완료 후 다시 정리하거나 확인해주세요.':sourceChanged?'설명이 바뀌었습니다. 설명 정리하기를 다시 눌러주세요.':'수정한 내용을 다시 확인해주세요.');
}
$('mode').onchange=()=>{
 $('textBox').hidden=$('mode').value!=='text';$('recordBox').hidden=$('mode').value!=='audio';recordedWav=null;$('file').value='';
 $('fileBox').hidden=$('mode').value==='text';$('file').accept=$('mode').value==='photo'?'image/jpeg,image/png,image/webp':'.wav,audio/wav';
 $('fileHelp').textContent=$('mode').value==='photo'?'찾을 물건 하나만 보이는 JPEG·PNG·WebP 사진 · 최대 5MB':'위 버튼으로 녹음하거나, 60초 이하 16kHz 모노 PCM16 WAV 파일을 선택하세요';
 invalidateInput(true);
};
$('file').addEventListener('change',()=>{recordedWav=null;invalidateInput(true);});
function dataURL(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('파일을 읽지 못했습니다. 파일을 다시 선택해주세요.'));reader.onabort=reader.onerror;reader.readAsDataURL(file);});}
async function post(path,body,timeout=60000){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
 try{
  const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});
  let data;try{data=await res.json();}catch{throw Error('서버 응답을 확인하지 못했습니다. 입력은 유지됩니다. 잠시 후 다시 시도해주세요.');}
  if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:'입력 내용을 확인해주세요');return data;
 }catch(error){
  if(error.name==='AbortError')throw Error('처리가 오래 걸리고 있어요. 입력은 유지됩니다. 잠시 후 다시 시도하거나 글로 입력해주세요.');
  if(error instanceof TypeError)throw Error('서버에 연결하지 못했습니다. 입력은 유지됩니다. 연결을 확인한 뒤 다시 시도해주세요.');throw error;
 }finally{clearTimeout(timer);}
}
function lockInput(locked){inputBusy=locked;$('prepare').disabled=locked;$('confirm').disabled=locked;$('record').disabled=locked;}
$('entry').onsubmit=async e=>{
 e.preventDefault();if(inputBusy||recorder)return;setConfirmedSearch(null);const revision=++inputRevision;
 proposal=null;$('review').hidden=true;lockInput(true);notice('설명을 정리하고 있습니다…');
 try{
  const mode=$('mode').value;let body=meta();
  if(mode==='text')body.text=$('text').value;
  else{
   const f=mode==='audio'&&recordedWav?recordedWav:$('file').files[0];if(!f)throw Error('파일을 선택하거나 녹음해주세요');
   if(!f.size||f.size>(mode==='photo'?5*1024*1024:2_000_000))throw Error(mode==='photo'?'사진은 비어 있지 않은 5MB 이하 파일을 선택해주세요.':'음성은 비어 있지 않은 60초 이하 16kHz 모노 PCM16 WAV 파일을 선택해주세요.');
   if(mode==='photo'&&!['image/jpeg','image/png','image/webp'].includes(f.type))throw Error('JPEG·PNG·WebP 사진을 선택해주세요.');
   if(mode==='audio'&&f.type&&!['audio/wav','audio/x-wav','audio/wave','audio/vnd.wave'].includes(f.type))throw Error('16kHz 모노 PCM16 WAV 파일을 선택해주세요.');
   const url=await dataURL(f);if(revision!==inputRevision)return;if(mode==='photo')body.photo=url;else body.audio_base64=url.split(',')[1];
  }
  const result=await post('/descriptions/'+mode,body,mode==='photo'?105000:60000);
  if(revision!==inputRevision)return;
  if(!result?.proposal_id||!result.description||typeof result.description!=='object')throw Error('정리 결과를 확인하지 못했습니다. 다시 시도해주세요.');
  proposal=result;$('category').value=proposal.description.category;
  for(const k of ['color','shape','mark','material','visible_text'])$(k).value=proposal.description[k]||'';
  for(const k of metadataFields)if(!$(k).value&&proposal[k])$(k).value=proposal[k];
  $('transcript').textContent=proposal.transcript?'인식된 말: '+proposal.transcript:'';$('warnings').textContent=(proposal.warnings||[]).join(' ');$('review').hidden=false;
  requestAnimationFrame(()=>{if(revision===inputRevision){$('review').scrollIntoView({behavior:'smooth',block:'start'});$('review').focus({preventScroll:true});}});
  notice('내용을 수정하고, 분실 날짜·호선·역을 채운 뒤 확인해주세요.');
 }catch(err){if(revision===inputRevision)notice(err.message,true);}finally{lockInput(false);}
};
$('confirm').onclick=async()=>{
 if(!proposal||inputBusy||recorder)return;const revision=inputRevision;lockInput(true);setConfirmedSearch(null);
 try{
  let description={...proposal.description,category:$('category').value};for(const k of ['color','shape','mark','material','visible_text']){if($(k).value.trim())description[k]=$(k).value.trim();else delete description[k];}
  const handoff=await post('/descriptions/'+proposal.proposal_id+'/confirm',{confirmed:true,description,...meta()});
  if(revision!==inputRevision)return;setConfirmedSearch(handoff);notice('설명을 확인했습니다. 이 설명으로 후보 검색을 누르면 날짜·호선·역도 검색에 사용합니다. 실제 DB 조회에는 본인인증·필수 동의 연결이 필요합니다.');
 }catch(err){if(revision===inputRevision)notice(err.message,true);}finally{lockInput(false);}
};

let recordedWav=null,recorder=null;
async function finishRecording(){
 if(!recorder)return;
 const r=recorder;recorder=null;clearTimeout(r.timer);r.processor.disconnect();r.source.disconnect();r.stream.getTracks().forEach(t=>t.stop());
 $('record').disabled=true;$('recordStatus').textContent='녹음 파일을 준비하고 있습니다…';
 try{
  const count=r.parts.reduce((n,p)=>n+p.length,0);if(!count)throw Error('녹음된 소리가 없습니다');
  const samples=new Float32Array(count);let offset=0;for(const p of r.parts){samples.set(p,offset);offset+=p.length;}
  const frames=Math.min(960000,Math.floor(count*16000/r.context.sampleRate));
  const ctx=new OfflineAudioContext(1,frames,16000),buffer=ctx.createBuffer(1,count,r.context.sampleRate);buffer.copyToChannel(samples,0);
  const source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);source.start();const rendered=await ctx.startRendering(),pcm=rendered.getChannelData(0);
  const wav=new ArrayBuffer(44+pcm.length*2),v=new DataView(wav);const ascii=(pos,str)=>{for(let i=0;i<str.length;i++)v.setUint8(pos+i,str.charCodeAt(i));};
  ascii(0,'RIFF');v.setUint32(4,36+pcm.length*2,true);ascii(8,'WAVE');ascii(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);ascii(36,'data');v.setUint32(40,pcm.length*2,true);
  for(let i=0;i<pcm.length;i++){const n=Math.max(-1,Math.min(1,pcm[i]));v.setInt16(44+i*2,n<0?n*32768:n*32767,true);}
  recordedWav=new Blob([wav],{type:'audio/wav'});$('recordStatus').textContent='녹음 준비 완료 ('+(pcm.length/16000).toFixed(1)+'초). 설명 정리하기를 눌러주세요.';
 }catch(e){recordedWav=null;$('recordStatus').textContent=e.message;}
 finally{await r.context.close();$('record').textContent='다시 녹음';$('record').disabled=false;$('mode').disabled=false;$('file').disabled=false;$('prepare').disabled=false;}
}
$('record').onclick=async()=>{
 if(inputBusy)return;
 if(window.ChatVoice?.busy()){$('recordStatus').textContent='채팅의 음성 질문 처리를 먼저 끝내주세요.';return;}
 if(recorder){await finishRecording();return;}
 $('record').disabled=true;const revision=inputRevision;let stream=null,ctx=null;
 try{
  if(!navigator.mediaDevices?.getUserMedia)throw Error('이 창에서는 녹음할 수 없습니다. 일반 브라우저로 열거나 WAV 파일을 선택해주세요.');
  stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true},video:false});
  if(revision!==inputRevision||$('mode').value!=='audio'){stream.getTracks().forEach(t=>t.stop());return;}
  ctx=new AudioContext();await ctx.resume();
  if(revision!==inputRevision){stream.getTracks().forEach(t=>t.stop());await ctx.close();return;}
  const source=ctx.createMediaStreamSource(stream),processor=ctx.createScriptProcessor(4096,1,1);const parts=[];
  processor.onaudioprocess=e=>parts.push(new Float32Array(e.inputBuffer.getChannelData(0)));source.connect(processor);processor.connect(ctx.destination);
  invalidateInput(true);recorder={stream,context:ctx,source,processor,parts,timer:setTimeout(finishRecording,60000)};recordedWav=null;$('file').value='';
  $('mode').disabled=true;$('file').disabled=true;$('prepare').disabled=true;$('record').textContent='녹음 끝내기';$('recordStatus').textContent='녹음 중입니다. 물건·색·특징을 말한 뒤 녹음 끝내기를 누르세요.';
 }catch(e){stream?.getTracks().forEach(t=>t.stop());if(ctx)await ctx.close();$('recordStatus').textContent='마이크 연결을 확인해주세요. 녹음 파일 선택도 가능합니다. '+e.message;}
 finally{$('record').disabled=false;}
};
window.addEventListener('pagehide',()=>{inputRevision++;recordedWav=null;if(recorder){clearTimeout(recorder.timer);recorder.stream.getTracks().forEach(t=>t.stop());recorder.context.close();}});

function setConfirmedSearch(handoff){
 document.dispatchEvent(new Event('searchcontextchange'));
 const values=handoff?{category:handoff.description.category,color:handoff.description.color,lost_date:handoff.lost_date,lost_line:handoff.lost_line,lost_station:handoff.lost_station}:null;
 confirmedSearchContext=values?Object.fromEntries(Object.entries(values).filter(([,v])=>v)):null;
 $('searchContextNote').hidden=!confirmedSearchContext;$('searchReviewed').hidden=!confirmedSearchContext;
 $('searchContextText').textContent=confirmedSearchContext?'확인한 설명: '+Object.values(confirmedSearchContext).join(' · '):'';
}
$('entry').addEventListener('input',event=>{if(event.target.id!=='mode'&&event.target.id!=='file')invalidateInput(event.target.id==='text');});
$('review').addEventListener('input',()=>invalidateInput(false));
$('clearSearchContext').onclick=()=>setConfirmedSearch(null);
