/* Multiple Chrome windows must not each consume two endless HTTP/1 streams. */
(() => {
 'use strict';
 const nativeFetch=window.fetch.bind(window);
 window.visionFetch=async(input,init={})=>{
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),init.timeoutMs||8000);
  try{return await nativeFetch(input,{...init,signal:init.signal||controller.signal});}
  catch(e){if(e.name==='AbortError')throw Error('요청 대기 시간이 초과됐습니다. 다른 창을 새로고침하고 다시 시도하세요.');throw e;}
  finally{clearTimeout(timer);}
 };
 const pending=new Map(),last=new WeakMap();
 function recognize(img){
  const source=img.getAttribute('src')||'';
  const match=source.match(/^\/api\/cameras\/(top|arm)\/(?:stream|frame\.jpg)(?:\?.*)?$/);
  if(match){img.dataset.liveCamera=match[1];img.removeAttribute('src');}
  else if(source&&!source.startsWith('blob:'))delete img.dataset.liveCamera;
 }
 const observer=new MutationObserver(rows=>{for(const row of rows){if(row.type==='attributes')recognize(row.target);else for(const n of row.addedNodes)if(n.nodeType===1){if(n.tagName==='IMG')recognize(n);n.querySelectorAll?.('img').forEach(recognize);}}});
 observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['src']});
 document.querySelectorAll('img').forEach(recognize);
 function abortAll(){for(const controller of pending.values())controller.abort();pending.clear();}
 async function update(img){
  if(pending.has(img)||document.hidden||img.hidden||!img.getClientRects().length)return;
  const camera=img.dataset.liveCamera;if(!camera)return;
  const controller=new AbortController();pending.set(img,controller);const timer=setTimeout(()=>controller.abort(),2500);
  try{
   const response=await nativeFetch('/api/cameras/'+camera+'/frame.jpg?t='+Date.now(),{signal:controller.signal,cache:'no-store'});
   if(!response.ok)return;
   const blob=await response.blob();if(controller.signal.aborted||document.hidden)return;
   const url=URL.createObjectURL(blob),previous=last.get(img);img.src=url;last.set(img,url);if(previous)URL.revokeObjectURL(previous);
  }catch(e){}finally{clearTimeout(timer);if(pending.get(img)===controller)pending.delete(img);}
 }
 setInterval(()=>{if(!document.hidden)document.querySelectorAll('img[data-live-camera]').forEach(update);},150);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)abortAll();});
 window.addEventListener('pagehide',abortAll);
})();
