// 11/8 챗봇 위젯 — 작은 떠 있는 창(접기·크기·자리 기억)과 진행률(0~100%) 시험. LF-13 변재원
// 실행: node --test tests/test_chat_widget_window.cjs
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const SRC=fs.readFileSync(path.join(__dirname,'../web/chat-widget/widget.js'),'utf8');

function setup({questionFetch,storage,width=1280,height=900}={}){
 const timers=new Map(),calls=[];let timerId=0;const clock={t:0};
 const doc={readyState:'complete',activeElement:null,addEventListener(){}};
 class Element{
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.events={};this.style={};this.className='';this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.classList={add:n=>{if(!this.className.split(' ').includes(n))this.className+=' '+n;},remove:n=>{this.className=this.className.split(' ').filter(c=>c!==n).join(' ');}};}
  set innerHTML(v){this._html=v;} get innerHTML(){return this._html||'';}
  append(...nodes){for(const n of nodes){if(n.parent)n.remove();n.parent=this;this.children.push(n);}}
  appendChild(node){this.append(node);return node;}
  attachShadow(){this.shadowRoot=new Element('shadow');return this.shadowRoot;}
  setAttribute(k,v){this.attributes[k]=String(v);}
  getAttribute(k){return this.attributes[k]??null;}
  addEventListener(k,fn){(this.events[k]??=[]).push(fn);}
  removeEventListener(k,fn){this.events[k]=(this.events[k]||[]).filter(f=>f!==fn);}
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
 const window={innerWidth:width,innerHeight:height};
 const ctx={document:doc,window,location:new URL('http://127.0.0.1:8100/lost'),URL,AbortController,TextDecoder,TextEncoder,
  performance:{now:()=>clock.t},
  Event:class{constructor(type){this.type=type;}preventDefault(){}},
  setTimeout(fn,delay){const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},
  fetch(url,init={}){const route=new URL(url).pathname;
   if(route!=='/chat/questions')return Promise.resolve({ok:true,json:async()=>route==='/chat/health'?{ready:true,search_mode:'demo_sqlite'}:route==='/chat/metrics'?{requests:{question:{p50_ms:2000,p95_ms:6000}}}:{items:[]}});
   calls.push({body:JSON.parse(init.body),headers:init.headers,signal:init.signal});return questionFetch(init,calls.length);}};
 if(storage)ctx.localStorage=storage;
 vm.createContext(ctx);vm.runInContext(SRC,ctx);
 const root=doc.body.children[0].shadowRoot,get=sel=>root.querySelector(sel);
 const run=delay=>{for(const [id,t] of [...timers])if(t.delay===delay){timers.delete(id);t.fn();}};
 return {doc,root,get,calls,timers,window,clock,run,
  open(){window.LostFoundChat.open();run(0);},
  send(q){get('textarea').value=q;get('form').dispatchEvent({type:'submit',preventDefault(){}});},
  button(label){return root.querySelectorAll('button').find(b=>b.getAttribute('aria-label')===label);}};
}
const okBody=answer=>({answer,agent:'guidance',status:'answered',sources:[]});
const ok=answer=>({ok:true,json:async()=>okBody(answer)});
function memoryStorage(){const m=new Map();return {m,getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k)};}
function ndjson(lines){const enc=new TextEncoder();const chunks=lines.map(l=>enc.encode(JSON.stringify(l)+'\n'));
 // 줄이 조각 경계에 걸쳐도 읽는지: 마지막 줄을 둘로 나눔
 const last=chunks.pop();chunks.push(last.slice(0,7),last.slice(7));
 return {ok:true,status:200,headers:{get:k=>k.toLowerCase()==='content-type'?'application/x-ndjson':null},
  body:{getReader(){let i=0;return {read:async()=>i<chunks.length?{done:false,value:chunks[i++]}:{done:true},cancel(){}};}}};}

// ── 진행률 계산 ──
test('progress never decreases, stops at 95 before the answer, and is 100 when done',()=>{
 const s=setup();const P=s.window.LostFoundChat.progressModel;
 for(let seed=1;seed<=40;seed++){
  let r=seed;const rnd=()=>{r=(r*16807)%2147483647;return r/2147483647;};
  const m=P(1000+rnd()*4000,rnd()<0.5?null:5000+rnd()*8000);let prev=0;
  const names=['received','route','retrieve','write','check','rewrite','recheck'],pct={received:5,route:12,retrieve:22,write:35,check:80,rewrite:84,recheck:92};
  for(let i=0;i<60;i++){
   if(rnd()<0.3){const n=names[Math.floor(rnd()*names.length)];m.stage(n,pct[n]);}   // 순서가 뒤바뀐 단계 알림도 섞음
   const v=m.at(rnd()*20000);                                                         // 시간도 앞뒤로 흔듦
   assert.ok(v>=prev,`seed ${seed}: ${v} < ${prev}`);assert.ok(v<=95);prev=v;}
  assert.equal(m.done(),100);assert.equal(m.at(0),100);}
});

test('time fill uses p50/p95 and caps below the next guaranteed stage',()=>{
 const s=setup();const P=s.window.LostFoundChat.progressModel;
 const a=P(3000,null);assert.ok(Math.abs(a.at(3000)-60)<=1,'p50 에서 약 60%');assert.equal(a.at(1e7),95);
 const b=P(2000,6000);assert.ok(Math.abs(b.at(6000)-90)<=1,'p95 에서 약 90%');
 const c=P(1000,null);c.stage('write',35);assert.equal(c.at(1e7),79,'답 쓰기 중에는 근거 확인(80) 바로 아래까지만');
 c.stage('check',80);assert.equal(c.at(1e7),95);assert.equal(c.stageText(),'근거 확인');
});

// ── 진행 막대 표시 ──
test('a slow answer shows a progressbar with aria values, then 100% and the answer',async()=>{
 let resolve;const s=setup({questionFetch:()=>new Promise(r=>{resolve=r;})});s.open();await tick();
 s.send('지갑 찾아줘');assert.equal(s.get('.prog'),null,'0.3초 전에는 막대 없음');
 s.clock.t=300;s.run(300);const bar=s.get('.prog');assert.ok(bar);assert.equal(bar.getAttribute('role'),'progressbar');
 const seen=[];for(let t=450;t<=12000;t+=150){s.clock.t=t;s.run(150);seen.push(Number(bar.getAttribute('aria-valuenow')));}
 assert.deepEqual(seen,[...seen].sort((x,y)=>x-y));assert.ok(seen.at(-1)<=95&&seen.at(-1)>=80);
 assert.match(bar.querySelector('b').textContent,/^답 준비 중 \d+%/);assert.equal(bar.querySelector('.est').textContent,'예상');
 resolve(ok('안내'));await tick();
 assert.equal(bar.getAttribute('aria-valuenow'),'100');assert.ok(s.root.querySelectorAll('.bubble').some(n=>n.textContent==='안내'));
 assert.equal(s.root.querySelectorAll('.msg.pending').length,0);
 s.run(350);s.run(450);assert.equal(s.get('.prog'),null,'잠깐 보인 뒤 사라짐');
});

test('an answer within 0.3s never draws the bar (no flicker for rule answers)',async()=>{
 const s=setup({questionFetch:()=>Promise.resolve(ok('규칙 답'))});s.open();await tick();
 s.send('운영 시간');await tick();s.clock.t=300;s.run(300);s.run(150);
 assert.equal(s.get('.prog'),null);assert.ok(s.root.querySelectorAll('.bubble').some(n=>n.textContent==='규칙 답'));
});

test('streamed stages move the bar and the last line becomes the normal answer',async()=>{
 let resolve;const s=setup({questionFetch:()=>new Promise(r=>{resolve=r;})});s.open();await tick();
 s.send('지갑은 어느 쪽이 위로?');assert.match(s.calls[0].headers.Accept,/application\/x-ndjson/);
 assert.equal(s.calls[0].body.stream,undefined,'본문은 그대로(스트림은 Accept 로만 요청)');
 s.clock.t=300;s.run(300);
 resolve(ndjson([{stage:'received',pct:5},{stage:'retrieve',pct:22},{stage:'write',pct:35},{stage:'check',pct:80},{done:true,...okBody('스트림 답')}]));
 for(let i=0;i<8;i++)await tick();
 assert.ok(s.root.querySelectorAll('.bubble').some(n=>n.textContent==='스트림 답'));
 assert.equal(s.get('.send').disabled,false);assert.equal(s.root.querySelectorAll('.msg.error').length,0);
});

test('a stage line updates the label with the real stage name',async()=>{
 let resolveStage;const s=setup({questionFetch:()=>new Promise(r=>{resolveStage=r;})});s.open();await tick();
 s.send('질문');s.clock.t=300;s.run(300);
 const enc=new TextEncoder();let push;const pending=[];
 resolveStage({ok:true,headers:{get:()=> 'application/x-ndjson'},body:{getReader(){return {read:()=>pending.length?Promise.resolve(pending.shift()):new Promise(r=>{push=r;}),cancel(){}};}}});
 await tick();push({done:false,value:enc.encode(JSON.stringify({stage:'check',pct:80})+'\n')});await tick();await tick();
 s.clock.t=450;s.run(150);const bar=s.get('.prog');assert.ok(Number(bar.getAttribute('aria-valuenow'))>=80);assert.match(bar.querySelector('b').textContent,/근거 확인/);
 push({done:false,value:enc.encode(JSON.stringify({done:true,...okBody('끝')})+'\n')});for(let i=0;i<6;i++)await tick();
 assert.ok(s.root.querySelectorAll('.bubble').some(n=>n.textContent==='끝'));
});

test('a stream error line shows the error and offers retry',async()=>{
 const s=setup({questionFetch:()=>Promise.resolve(ndjson([{stage:'received',pct:5},{done:true,error:true,status_code:503,detail:''}]))});s.open();await tick();
 s.send('질문');for(let i=0;i<8;i++)await tick();
 assert.match(s.get('.msg.error').children[0].textContent,/준비되지 않았어요/);assert.ok(s.get('.retry'));assert.equal(s.get('.send').disabled,false);
});

// ── 작은 떠 있는 창 ──
test('opens as a small window inside the screen, bottom-right by default',async()=>{
 const s=setup();s.open();const st=s.get('.panel').style;
 assert.deepEqual([st.width,st.height,st.left,st.top],['360px','520px',(1280-16-360)+'px',(900-16-520)+'px']);
 assert.equal(s.get('.scrim'),null,'어두운 막 없음');assert.equal(s.get('.grip').className,'grip tl');
});

test('phone width uses 92vw x 60vh at the bottom, and the size button toggles 85vh',async()=>{
 const s=setup({width:390,height:844});s.open();const st=s.get('.panel').style;
 assert.equal(st.width,Math.round(390*.92)+'px');assert.equal(st.height,Math.round(844*.6)+'px');
 assert.equal(parseInt(st.top)+parseInt(st.height)<=844-8,true);
 s.button('창 크게').dispatchEvent({type:'click'});assert.equal(st.height,Math.round(844*.85)+'px');
 assert.ok(parseInt(st.top)>=8,'화면 위로 나가지 않음');
});

test('minimize turns into a pill, a new answer marks it unread, the opener restores it',async()=>{
 let resolve;const s=setup({questionFetch:()=>new Promise(r=>{resolve=r;})});s.open();await tick();
 s.send('지갑 찾아줘');s.button('챗봇 접기').dispatchEvent({type:'click'});
 assert.ok(s.get('.wrap').className.includes('min'));assert.equal(s.doc.activeElement,s.get('.pill'));
 s.clock.t=600;s.run(300);assert.match(s.get('.pt').textContent,/답 준비 중 \d+%/);
 resolve(ok('안내'));await tick();assert.ok(s.get('.pill').className.includes('unread'));
 assert.notEqual(s.doc.activeElement,s.get('textarea'),'접힌 동안 입력칸으로 초점을 빼앗지 않음');
 s.window.LostFoundChat.toggle();assert.ok(!s.get('.wrap').className.includes('min'));assert.ok(!s.get('.pill').className.includes('unread'));
 assert.equal(s.get('.panel').hidden,false);
});

test('size and position are remembered in localStorage and clamped on reopen',async()=>{
 const store=memoryStorage();const a=setup({storage:store});a.open();a.button('창 크게').dispatchEvent({type:'click'});
 assert.equal(a.get('.panel').style.width,'480px');const saved=JSON.parse(store.getItem('lf-chat-win:/lost'));
 assert.equal(saved.size,'large');assert.equal(saved.ax,'r');assert.equal(saved.ay,'b');
 const b=setup({storage:store});b.open();assert.equal(b.get('.panel').style.width,'480px');assert.equal(b.get('.panel').style.height,'720px');
 store.setItem('lf-chat-win:/lost',JSON.stringify({ax:'l',ay:'t',dx:5000,dy:4000,w:480,h:720,size:'large'}));
 const c=setup({storage:store,width:1024,height:700});c.open();const st=c.get('.panel').style;
 assert.ok(parseInt(st.left)+parseInt(st.width)<=1024-16&&parseInt(st.top)>=16&&parseInt(st.top)+parseInt(st.height)<=700-16,'화면 안으로');
});

test('broken localStorage does not stop the window',async()=>{
 const bad={getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}};
 const s=setup({storage:bad});s.open();s.button('창 크게').dispatchEvent({type:'click'});assert.equal(s.get('.panel').style.width,'480px');
 s.window.LostFoundChat.close();assert.equal(s.get('.panel').hidden,true);
});
