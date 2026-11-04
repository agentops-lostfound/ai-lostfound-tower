/* Explicit user action only. Transcription is reviewed, never automatically sent. */
(function(){
 let recording=null,processing=false;
 const busy=()=>!!recording||processing;window.ChatVoice={busy};
 function controls(disabled){$('chatSend').disabled=disabled;$('chatAudio').disabled=disabled;$('chatAudioPick').disabled=disabled;$('clearChat').disabled=disabled;}
 async function transcribe(blob){
  if(blob.size>2_000_000)throw Error('음성은 60초 이하, 2MB 이하의 16kHz 모노 WAV 파일로 선택해주세요.');
  processing=true;controls(true);$('chatRecord').disabled=true;$('chatStatus').textContent='말한 내용을 글자로 바꾸고 있어요…';
  try{const url=await dataURL(blob);const result=await post('/chat/transcriptions',{audio_base64:url.split(',')[1]},90000);
   $('chatQuestion').value=result.text;updateSuggestions();$('chatQuestion').focus();$('chatStatus').textContent='인식된 글을 확인·수정한 뒤 보내기 버튼을 눌러주세요. 아직 전송하지 않았어요.';
  }finally{processing=false;controls(false);$('chatRecord').disabled=false;}
 }
 async function stop(){
  if(!recording)return;const r=recording;recording=null;processing=true;clearTimeout(r.timer);r.processor.disconnect();r.source.disconnect();r.stream.getTracks().forEach(t=>t.stop());$('chatRecord').disabled=true;
  try{
   const count=r.parts.reduce((n,p)=>n+p.length,0);if(!count)throw Error('녹음된 소리가 없어요. 글로도 질문할 수 있어요.');
   const samples=new Float32Array(count);let pos=0;for(const part of r.parts){samples.set(part,pos);pos+=part.length;}
   const frames=Math.min(960000,Math.floor(count*16000/r.context.sampleRate));if(frames<1)throw Error('녹음이 너무 짧아요.');
   const offline=new OfflineAudioContext(1,frames,16000),buffer=offline.createBuffer(1,count,r.context.sampleRate);buffer.copyToChannel(samples,0);const source=offline.createBufferSource();source.buffer=buffer;source.connect(offline.destination);source.start();
   const pcm=(await offline.startRendering()).getChannelData(0),wav=new ArrayBuffer(44+pcm.length*2),view=new DataView(wav);
   const ascii=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
   ascii(0,'RIFF');view.setUint32(4,36+pcm.length*2,true);ascii(8,'WAVEfmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);ascii(36,'data');view.setUint32(40,pcm.length*2,true);for(let i=0;i<pcm.length;i++)view.setInt16(44+i*2,Math.max(-32768,Math.min(32767,Math.round(pcm[i]*32767))),true);
   await transcribe(new Blob([wav],{type:'audio/wav'}));
  }catch(error){$('chatStatus').textContent=error.message;}
  finally{processing=false;await r.context.close();$('chatRecord').textContent='음성 질문';$('chatRecord').disabled=false;controls(false);}
 }
 $('chatRecord').onclick=async()=>{
  if(recording){await stop();return;}if(processing||chatBusy)return;
  if(recorder){$('chatStatus').textContent='왼쪽 물건 설명 녹음을 먼저 끝내주세요.';return;}
  let stream,context;processing=true;controls(true);$('chatRecord').disabled=true;
  try{
   if(!navigator.mediaDevices?.getUserMedia)throw Error('이 창에서는 녹음이 지원되지 않아요. 일반 브라우저나 WAV 파일을 사용해주세요.');
   stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true},video:false});context=new AudioContext();await context.resume();
   const source=context.createMediaStreamSource(stream),processor=context.createScriptProcessor(4096,1,1),parts=[];
   processor.onaudioprocess=e=>parts.push(new Float32Array(e.inputBuffer.getChannelData(0)));source.connect(processor);processor.connect(context.destination);
   recording={stream,context,source,processor,parts,timer:setTimeout(stop,60000)};$('chatRecord').textContent='녹음 끝내기';$('chatStatus').textContent='녹음 중 · 최대 60초. 끝내면 글자로 확인할 수 있어요.';
  }catch(error){stream?.getTracks().forEach(t=>t.stop());if(context)await context.close();controls(false);$('chatStatus').textContent='마이크를 확인하거나 글로 질문해주세요. '+error.message;}
  finally{processing=false;$('chatRecord').disabled=false;}
 };
 $('chatAudio').onchange=async()=>{const file=$('chatAudio').files[0];if(!file||busy()||chatBusy)return;try{await transcribe(file);}catch(error){$('chatStatus').textContent=error.message;}finally{$('chatAudio').value='';}};
 $('chatAudioPick').onclick=()=>{if(!busy()&&!chatBusy)$('chatAudio').click();};
 window.addEventListener('pagehide',()=>{if(recording){clearTimeout(recording.timer);recording.stream.getTracks().forEach(t=>t.stop());recording.processor.disconnect();recording.context.close();recording=null;}});
})();
