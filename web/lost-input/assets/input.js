
const $=id=>document.getElementById(id);let proposal=null;const meta=()=>Object.fromEntries(['lost_date','lost_line','lost_station'].filter(k=>$(k).value).map(k=>[k,$(k).value]));
$('mode').onchange=()=>{$('textBox').hidden=$('mode').value!=='text';$('recordBox').hidden=$('mode').value!=='audio';recordedWav=null;$('fileBox').hidden=$('mode').value==='text';$('file').accept=$('mode').value==='photo'?'image/jpeg,image/png,image/webp':'.wav';$('fileHelp').textContent=$('mode').value==='photo'?'찾을 물건 하나만 보이는 사진 · 최대 5MB':'위 버튼으로 녹음하거나, 60초 이하 16kHz 모노 WAV 파일을 선택하세요';proposal=null;$('review').hidden=true;};
function dataURL(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});}
async function post(path,body,timeout=60000){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);try{const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});const data=await res.json();if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:'입력 내용을 확인해주세요');return data;}catch(error){if(error.name==='AbortError')throw Error('처리가 오래 걸리고 있어요. 잠시 후 다시 시도하거나 글로 입력해주세요.');throw error;}finally{clearTimeout(timer);}}
$('entry').onsubmit=async e=>{e.preventDefault();proposal=null;$('review').hidden=true;$('prepare').disabled=true;$('notice').className='';$('notice').textContent='설명을 정리하고 있습니다…';try{const mode=$('mode').value;let body=meta();if(mode==='text')body.text=$('text').value;else{const f=mode==='audio'&&recordedWav?recordedWav:$('file').files[0];if(!f)throw Error('파일을 선택해주세요');if(f.size>(mode==='photo'?5*1024*1024:2_000_000))throw Error('파일 크기를 줄여주세요');const url=await dataURL(f);if(mode==='photo')body.photo=url;else body.audio_base64=url.split(',')[1];}proposal=await post('/descriptions/'+mode,body);$('category').value=proposal.description.category;$('color').value=proposal.description.color||'';$('shape').value=proposal.description.shape||'';$('mark').value=proposal.description.mark||'';$('material').value=proposal.description.material||'';$('visible_text').value=proposal.description.visible_text||'';for(const k of ['lost_date','lost_line','lost_station'])if(!$(k).value&&proposal[k])$(k).value=proposal[k];$('transcript').textContent=proposal.transcript?'인식된 말: '+proposal.transcript:'';$('warnings').textContent=(proposal.warnings||[]).join(' ');$('review').hidden=false;requestAnimationFrame(()=>{ $('review').scrollIntoView({behavior:'smooth',block:'start'}); $('review').focus({preventScroll:true}); });$('notice').textContent='내용을 수정하고, 분실 날짜·호선·역을 채운 뒤 확인해주세요.';}catch(err){$('notice').className='error';$('notice').textContent=err.message;}finally{$('prepare').disabled=false;}};
$('confirm').onclick=async()=>{if(!proposal)return;$('confirm').disabled=true;try{let description={...proposal.description,category:$('category').value};for(const k of ['color','shape','mark','material','visible_text']){if($(k).value.trim())description[k]=$(k).value.trim();else delete description[k];}await post('/descriptions/'+proposal.proposal_id+'/confirm',{confirmed:true,description,...meta()});$('notice').className='';$('notice').textContent='검색에 사용할 설명이 준비됐습니다. 본인 인증·필수 동의와 실제 후보 검색은 기존 찾기 절차에서 별도로 진행해야 합니다. 이 시연에서는 검색이나 예약을 실행하지 않았습니다.';}catch(err){$('notice').className='error';$('notice').textContent=err.message;}finally{$('confirm').disabled=false;}};

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
 finally{await r.context.close();$('record').textContent='다시 녹음';$('record').disabled=false;$('mode').disabled=false;$('prepare').disabled=false;}
}
$('record').onclick=async()=>{
 if(window.ChatVoice?.busy()){$('recordStatus').textContent='채팅의 음성 질문 처리를 먼저 끝내주세요.';return;}
 if(recorder){await finishRecording();return;}
 $('record').disabled=true;let stream=null,ctx=null;
 try{
  if(!navigator.mediaDevices?.getUserMedia)throw Error('이 창에서는 녹음할 수 없습니다. 일반 브라우저로 열거나 WAV 파일을 선택해주세요.');
  stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true},video:false});ctx=new AudioContext();await ctx.resume();
  const source=ctx.createMediaStreamSource(stream),processor=ctx.createScriptProcessor(4096,1,1);const parts=[];
  processor.onaudioprocess=e=>parts.push(new Float32Array(e.inputBuffer.getChannelData(0)));source.connect(processor);processor.connect(ctx.destination);
  recorder={stream,context:ctx,source,processor,parts,timer:setTimeout(finishRecording,60000)};recordedWav=null;
  $('mode').disabled=true;$('prepare').disabled=true;$('record').textContent='녹음 끝내기';$('recordStatus').textContent='녹음 중입니다. 물건·색·특징을 말한 뒤 녹음 끝내기를 누르세요.';
 }catch(e){stream?.getTracks().forEach(t=>t.stop());if(ctx)await ctx.close();$('recordStatus').textContent='마이크 연결을 확인해주세요. 녹음 파일 선택도 가능합니다. '+e.message;}
 finally{$('record').disabled=false;}
};
window.addEventListener('pagehide',()=>{if(recorder){clearTimeout(recorder.timer);recorder.stream.getTracks().forEach(t=>t.stop());recorder.context.close();}});
