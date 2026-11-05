const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(questionFetch,otherFetch){
 const timers=new Map(),calls=[];let timerId=0;
 const doc={readyState:'complete',activeElement:null,addEventListener(){}};
 class Element{
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.events={};this.style={};this.className='';this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.classList={add:name=>{this.className+=' '+name;},remove:name=>{this.className=this.className.split(' ').filter(c=>c!==name).join(' ');}};}
  append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
  appendChild(node){this.append(node);return node;}
  attachShadow(){this.shadowRoot=new Element('shadow');return this.shadowRoot;}
  setAttribute(k,v){this.attributes[k]=v;}
  getAttribute(k){return this.attributes[k]??null;}
  addEventListener(k,fn){(this.events[k]??=[]).push(fn);}
  dispatchEvent(e){for(const fn of this.events[e.type]||[])fn(e);}
  focus(){doc.activeElement=this;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}
  replaceChildren(...nodes){for(const n of this.children)n.parent=null;this.children=[];this.append(...nodes);}
  matches(selector){if(selector.startsWith('.'))return selector.slice(1).split('.').every(c=>this.className.split(' ').includes(c));if(selector.startsWith('['))return this.getAttribute(selector.slice(1,-1))!==null;return this.tag===selector;}
  querySelectorAll(selector){return this.children.flatMap(n=>[...(n.matches(selector)?[n]:[]),...n.querySelectorAll(selector)]);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 }
 doc.body=new Element('body');doc.createElement=tag=>new Element(tag);doc.querySelector=sel=>doc.body.querySelector(sel);
 doc.currentScript={src:'http://127.0.0.1:8100/chat-widget/widget.js',getAttribute(){return null;}};
 const window={};
 const context=vm.createContext({document:doc,window,location:new URL('http://127.0.0.1:8100/lost'),URL,AbortController,
  Event:class{constructor(type){this.type=type;}preventDefault(){}},
  setTimeout(fn,delay){const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},
  fetch(url,init={}){const route=new URL(url).pathname;if(route!=='/chat/questions')return otherFetch?otherFetch(route):Promise.resolve({ok:true,json:async()=>route==='/chat/health'?{ready:true,search_mode:'demo_sqlite'}:{items:[]}});calls.push({body:JSON.parse(init.body),signal:init.signal});return questionFetch(init,calls.length);}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/chat-widget/widget.js'),'utf8'),context);
 const root=doc.body.children[0].shadowRoot,get=sel=>root.querySelector(sel);
 return {doc,root,get,calls,timers,window,clear(){root.querySelectorAll('button').find(n=>n.textContent==='대화 지우기').dispatchEvent({type:'click'});},open(){window.LostFoundChat.open();for(const [id,t] of [...timers])if(t.delay===0){timers.delete(id);t.fn();}},send(q){get('textarea').value=q;get('form').dispatchEvent({type:'submit',preventDefault(){}});}};
}
const ok=answer=>({ok:true,json:async()=>({answer,agent:'guidance',status:'answered',sources:[]})});

test('closing while waiting never restores focus to the hidden input',async()=>{
 let resolve;const s=setup(()=>new Promise(r=>{resolve=r;}));const external={focus(){s.doc.activeElement=this;}};external.focus();s.open();await tick();
 s.send('사진 입력 방법');s.window.LostFoundChat.close();assert.equal(s.doc.activeElement,external);
 resolve(ok('안내'));await tick();assert.equal(s.doc.activeElement,external);assert.equal(s.get('.send').disabled,false);
});

test('retrying an older failure does not delete a later successful question',async()=>{
 const s=setup((_init,n)=>n===1?Promise.reject(Error('offline')):Promise.resolve(ok('안내')));s.open();await tick();
 s.send('첫 질문');await tick();s.send('두 번째 질문');await tick();s.get('.retry').dispatchEvent({type:'click'});await tick();
 const users=s.root.querySelectorAll('.msg.user').map(n=>n.children[0].textContent);
 assert.deepEqual(users,['두 번째 질문','첫 질문']);
});

test('an old retry button cannot remove messages during another pending request',async()=>{
 let resolve;const s=setup((_init,n)=>n===1?Promise.reject(Error('offline')):new Promise(r=>{resolve=r;}));s.open();await tick();s.send('첫 질문');await tick();
 const retry=s.get('.retry');s.send('다음 질문');const before=s.root.querySelectorAll('.msg').length;retry.dispatchEvent({type:'click'});
 assert.equal(s.root.querySelectorAll('.msg').length,before);assert.equal(s.calls.length,2);resolve(ok('안내'));await tick();
});

test('a timed out response body unlocks send and offers retry',async()=>{
 const s=setup(init=>Promise.resolve({ok:true,json:()=>new Promise((_resolve,reject)=>init.signal?.addEventListener('abort',()=>reject(Error('aborted'))))}));s.open();await tick();s.send('지갑 찾아줘');await tick();
 const deadline=[...s.timers.values()].find(t=>t.delay===30000);assert.ok(deadline,'question deadline is registered');deadline.fn();await tick();
 assert.equal(s.get('.send').disabled,false);assert.ok(s.get('.retry'));assert.match(s.get('.msg.error').children[0].textContent,/시간/);
});

test('overlength input stays intact and is not silently truncated or sent',async()=>{
 const s=setup(()=>Promise.resolve(ok('안내')));s.open();await tick();const text='가'.repeat(501);s.send(text);await tick();
 assert.equal(s.calls.length,0);assert.equal(s.get('textarea').value,text);assert.equal(s.root.querySelectorAll('.msg.user').length,0);
});

test('malformed success does not enter history and remains retryable',async()=>{
 const s=setup((_init,n)=>n===1?Promise.resolve({ok:true,json:async()=>({answer:'잘못된 응답',sources:[null]})}):Promise.resolve(ok('정상 안내')));s.open();await tick();s.send('실패한 질문');await tick();
 assert.ok(s.get('.retry'));assert.equal(s.get('.send').disabled,false);s.send('새 질문');await tick();assert.deepEqual(s.calls[1].body.history,[]);
});

test('successful request clears its timer and preserves next draft',async()=>{
 let resolve;const s=setup(()=>new Promise(r=>{resolve=r;}));s.open();await tick();s.send('첫 질문');s.get('textarea').value='작성 중인 다음 질문';resolve(ok('안내'));await tick();
 assert.equal(s.get('textarea').value,'작성 중인 다음 질문');assert.equal(s.get('.send').disabled,false);assert.equal([...s.timers.values()].filter(t=>t.delay===30000).length,0);
});

test('clear cancels the pending request, removes the draft, and allows a new question immediately',async()=>{
 let resolve;const s=setup(()=>new Promise(r=>{resolve=r;}));s.open();await tick();s.send('지갑 찾아줘');s.get('textarea').value='보내지 않은 설명';s.clear();
 assert.equal(s.calls[0].signal.aborted,true);assert.equal(s.get('.send').disabled,false);
 assert.equal(s.get('textarea').value,'');assert.equal(s.root.querySelectorAll('.msg').length,0);resolve(ok('삭제한 질문의 답변'));await tick();
 assert.equal(s.root.querySelectorAll('.msg').length,0);
});

test('late success from a cleared conversation cannot enter history or unlock a newer request',async()=>{
 const pending=[];const s=setup(()=>new Promise(resolve=>pending.push(resolve)));s.open();await tick();s.send('이전 지갑 질문');s.clear();s.send('새 USB 질문');
 assert.equal(s.calls.length,2);assert.deepEqual(s.calls[1].body.history,[]);pending[0](ok('오래된 답변'));await tick();
 assert.equal(s.get('.send').disabled,true);
 assert.equal(s.root.querySelectorAll('.bubble').some(n=>n.textContent==='오래된 답변'),false);
 pending[1](ok('새 답변'));await tick();assert.equal(s.get('.send').disabled,false);
});

test('late failure from a cleared conversation does not add an error or change new conversation state',async()=>{
 const pending=[];const s=setup(()=>new Promise((resolve,reject)=>pending.push({resolve,reject})));s.open();await tick();s.send('이전 질문');s.clear();s.send('새 질문');
 assert.equal(pending.length,2);pending[0].reject(Error('old offline'));await tick();
 assert.equal(s.root.querySelectorAll('.msg.error').length,0);assert.equal(s.get('.send').disabled,true);pending[1].resolve(ok('새 답변'));await tick();
});

test('retrying a failed question preserves the next unsent draft',async()=>{
 const s=setup((_init,n)=>n===1?Promise.reject(Error('offline')):Promise.resolve(ok('안내')));s.open();await tick();s.send('실패한 질문');await tick();
 s.get('textarea').value='보내지 않은 새 질문';s.get('.retry').dispatchEvent({type:'click'});await tick();assert.equal(s.get('textarea').value,'보내지 않은 새 질문');
});

test('reopening retries health after a temporary connection failure',async()=>{
 let healthCalls=0;const s=setup(()=>Promise.resolve(ok('안내')),route=>{if(route==='/chat/health'){healthCalls++;if(healthCalls===1)return Promise.reject(Error('offline'));return Promise.resolve({ok:true,json:async()=>({ready:true,search_mode:'demo_sqlite'})});}return Promise.resolve({ok:true,json:async()=>({items:[]})});});
 s.open();await tick();s.window.LostFoundChat.close();s.open();await tick();assert.equal(healthCalls,2);assert.match(s.get('.mode').textContent,/가상 물건 검색/);
});

test('retry keeps the original question context even after a different item was discussed',async()=>{
 const s=setup((_init,n)=>n===2?Promise.reject(Error('offline')):Promise.resolve(ok('안내')));s.open();await tick();
 s.send('검정 지갑 찾아줘');await tick();s.send('그럼 빨간색은?');await tick();const retry=s.get('.retry');
 s.send('회색 USB 찾아줘');await tick();retry.dispatchEvent({type:'click'});await tick();
 assert.deepEqual(s.calls[3].body.history,['검정 지갑 찾아줘']);
 s.send('그럼 흰색은?');await tick();assert.deepEqual(s.calls[4].body.history,['검정 지갑 찾아줘','그럼 빨간색은?']);
});
