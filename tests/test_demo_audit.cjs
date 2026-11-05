const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(){
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,disabled:false,textContent:'',children:[],append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;}});return nodes.get(id);};
 const result={mode:'demo_sqlite',revision:'a'.repeat(32),checked_at:'2026-11-05T03:00:00Z',status:'ok',issue_count:0,issues:[],counts:{items:6,collections:1,events:3},scope:'가상 기록 · 실물 확인 아님'};
 const context=vm.createContext({$:get,snapshot:{revision:result.revision},busy:false,fresh:true,api:async()=>structuredClone(result),timeLabel:()=> '11/5',
  el:(tag,text)=>({textContent:text,children:[],append(...v){this.children.push(...v);}}),render:()=>context.CollectionAudit?.sync(context.snapshot,context.busy,context.fresh)});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/collection-desk/assets/audit.js'),'utf8'),context);return {get,result,context};
}
test('read-only audit result is invalidated when collection snapshot changes',async()=>{
 const s=setup();await s.get('auditRun').onclick();assert.equal(s.get('auditResult').hidden,false);assert.match(s.get('auditStatus').textContent,/불일치가 발견되지/);
 s.context.snapshot={revision:'a'.repeat(32)};s.context.CollectionAudit.sync(s.context.snapshot,false,true);assert.equal(s.get('auditResult').hidden,true);
 await s.get('auditRun').onclick();s.context.CollectionAudit.sync(s.context.snapshot,false,false);assert.equal(s.get('auditResult').hidden,true);
});
test('inconsistent audit displays issues as text and never offers automatic repair',async()=>{
 const s=setup();s.result.status='attention';s.result.issue_count=1;s.result.issues=[{message:'이력 누락',item_id:'A-W01',collection_id:1}];await s.get('auditRun').onclick();
 assert.equal(s.get('auditIssues').children.length,1);assert.match(s.get('auditStatus').textContent,/자동 수정하지/);
});
