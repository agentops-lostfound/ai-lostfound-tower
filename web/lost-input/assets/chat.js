/* Public guidance only. Chat text lives in this page's DOM, never localStorage. */
let chatBusy=false,faqItems=[],visibleSuggestions=[],activeSuggestion=-1,selectedFaq=null,chatHistory=[];
document.addEventListener('searchcontextchange',()=>{chatHistory=[];});
const scrollChat=()=>{const area=$('chatScroll');area.scrollTo({top:area.scrollHeight,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});};
function chatLine(role,text){
 const li=document.createElement('li');li.className='chat-'+role;
 const label=document.createElement('div');label.className='message-label';label.textContent=role==='user'?'나':'안내 도우미';
 const bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=text;li.append(label,bubble);$('chatLog').append(li);
 while($('chatLog').children.length>20)$('chatLog').firstElementChild.remove();scrollChat();return li;
}
function hideSuggestions(){visibleSuggestions=[];activeSuggestion=-1;$('suggestions').hidden=true;$('chatQuestion').setAttribute('aria-expanded','false');$('chatQuestion').removeAttribute('aria-activedescendant');}
function selectSuggestion(item){$('chatQuestion').value=item.text;selectedFaq=item;hideSuggestions();updateCount();$('chatQuestion').focus();}
function updateCount(){$('charCount').textContent=$('chatQuestion').value.length+'/500';}
function updateSuggestions(){
 selectedFaq=null;updateCount();const query=$('chatQuestion').value.trim();if(!query||chatBusy){hideSuggestions();return;}
 visibleSuggestions=GuidanceSuggestions.rank(faqItems,query);activeSuggestion=-1;const box=$('suggestions');box.replaceChildren();
 if(!visibleSuggestions.length){hideSuggestions();return;}
 const heading=document.createElement('div');heading.className='suggestion-heading';heading.textContent='이런 질문을 찾으셨나요?';box.append(heading);
 visibleSuggestions.forEach((item,index)=>{const option=document.createElement('button');option.type='button';option.id='suggestion-'+index;option.className='suggestion-option';option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.textContent=item.text;option.onmousedown=e=>e.preventDefault();option.onclick=()=>selectSuggestion(item);box.append(option);});
 box.hidden=false;$('chatQuestion').setAttribute('aria-expanded','true');
}
function moveSuggestion(delta){
 activeSuggestion=(activeSuggestion+delta+visibleSuggestions.length)%visibleSuggestions.length;
 $('suggestions').querySelectorAll('[role=option]').forEach((option,index)=>{option.classList.toggle('active',index===activeSuggestion);option.setAttribute('aria-selected',String(index===activeSuggestion));});
 $('chatQuestion').setAttribute('aria-activedescendant','suggestion-'+activeSuggestion);
}
function renderFaq(){
 const cards=$('faqCards');cards.replaceChildren();faqItems.slice(0,3).forEach((item,index)=>{
  const button=document.createElement('button');button.className='faq-card';button.type='button';
  const number=document.createElement('span');number.className='faq-number';number.textContent=String(index+1).padStart(2,'0');const text=document.createElement('span');text.textContent=item.text;const arrow=document.createElement('span');arrow.className='faq-arrow';arrow.textContent='↗';button.append(number,text,arrow);
  button.onclick=()=>{if(chatBusy)return;selectSuggestion(item);$('chatForm').requestSubmit();};cards.append(button);
 });
 $('faqLabel').replaceChildren(document.createTextNode(faqItems.some(item=>item.count>0)?'많이 선택한 질문':'먼저 물어보세요'));
 const tag=document.createElement('span');tag.textContent=faqItems.some(item=>item.count>0)?'이번 서버 실행 기준':'추천 질문';$('faqLabel').append(tag);
}
async function loadFaq(){try{const response=await fetch('/guidance/suggestions');if(!response.ok)throw Error();const data=await response.json();faqItems=data.items;renderFaq();}catch{ $('faqCards').textContent='추천 질문을 불러오지 못했어요. 아래에서 직접 질문해주세요.';}}
function addSources(li,sources){
 if(!sources.length)return;const details=document.createElement('details');details.className='sources';const summary=document.createElement('summary');summary.textContent='안내 근거 '+sources.length+'개 보기';details.append(summary);const list=document.createElement('ul');
 for(const source of sources){const item=document.createElement('li');let url;try{url=new URL(source.url,location.origin);}catch{continue;}if(!(url.protocol==='https:'&&url.hostname==='github.com')&&!(url.origin===location.origin&&url.pathname==='/guidance/documents/site-help'))continue;
  const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.textContent=source.title;const quote=document.createElement('blockquote');quote.textContent=source.evidence;item.append(link,quote);list.append(item);
 }details.append(list);li.append(details);
}
$('chatForm').onsubmit=async e=>{
 e.preventDefault();if(chatBusy||window.ChatVoice?.busy())return;const question=$('chatQuestion').value.trim();if(!question)return;
 const faq=selectedFaq?.text===question?selectedFaq:faqItems.find(item=>item.text===question);chatBusy=true;$('chatSend').disabled=true;$('clearChat').disabled=true;hideSuggestions();$('chatWelcome').hidden=true;$('faqArea').hidden=true;chatLine('user',question);
 $('chatRecord').disabled=true;$('chatAudio').disabled=true;$('chatAudioPick').disabled=true;
 const pending=chatLine('assistant','질문을 확인하고 있어요…');pending.classList.add('pending');$('chatStatus').textContent='답변 준비 중';
 try{
  const response=await post('/chat/questions',{question,history:chatHistory,suggestion_id:faq?.id,search_context:confirmedSearchContext||undefined});chatHistory=[...chatHistory,question].slice(-4);pending.remove();const li=chatLine('assistant',response.answer);const badge=document.createElement('span');badge.className='answer-badge';badge.textContent=response.agent==='search'||response.agent==='both'?(response.database_mode==='demo_sqlite'?'가상 DB 시연':'물건 검색 안내'):response.generation_used?'문서 검색 + AI 답변':response.status==='answered'?(response.sources.length?'문서 근거 안내':'대화 안내'):response.status==='partial'||response.status==='policy_pending'?'확정 안내가 필요한 내용':'질문을 조금 더 구체적으로';li.append(badge);if(response.context_used){const note=document.createElement('span');note.className='answer-badge';note.textContent='앞선 질문을 이어서 이해했어요';li.append(note);}addSources(li,response.sources);addCandidates(li,response.candidates||[]);$('chatStatus').textContent=response.agent==='search'||response.agent==='both'?'검색 안내 완료 · 후보는 본인 물건 확정이 아닙니다':'안내 완료 · 출처를 확인할 수 있어요';$('chatQuestion').value='';selectedFaq=null;updateCount();await loadFaq();scrollChat();
 }catch(error){pending.remove();const li=chatLine('assistant',error.message);const retry=document.createElement('button');retry.type='button';retry.className='retry-button';retry.textContent='질문 다시 보내기';retry.onclick=()=>{if(chatBusy)return;$('chatQuestion').value=question;$('chatForm').requestSubmit();};li.append(retry);$('chatStatus').textContent='전송하지 못했어요. 내용을 확인하고 다시 시도해주세요.';}
 finally{chatBusy=false;$('chatSend').disabled=false;$('clearChat').disabled=false;$('chatRecord').disabled=false;$('chatAudio').disabled=false;$('chatAudioPick').disabled=false;}
};
$('chatQuestion').addEventListener('input',updateSuggestions);
$('chatQuestion').addEventListener('keydown',event=>{
 if(event.isComposing||event.keyCode===229)return;
 if(event.key==='Escape'){hideSuggestions();return;}
 if(visibleSuggestions.length&&(event.key==='ArrowDown'||event.key==='ArrowUp')){event.preventDefault();moveSuggestion(event.key==='ArrowDown'?1:-1);return;}
 if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();if(activeSuggestion>=0){selectSuggestion(visibleSuggestions[activeSuggestion]);}else $('chatForm').requestSubmit();}
});
document.addEventListener('click',event=>{if(!event.target.closest('.composer'))hideSuggestions();});
$('clearChat').onclick=()=>{if(chatBusy)return;chatHistory=[];$('chatLog').replaceChildren();$('chatWelcome').hidden=false;$('faqArea').hidden=false;$('chatStatus').textContent='이 화면의 대화를 지웠어요';hideSuggestions();$('chatScroll').scrollTop=0;};
loadFaq();
function addCandidates(li,candidates){
 if(!candidates.length)return;const cards=document.createElement('div');cards.className='candidate-cards';
 for(const candidate of candidates){const card=document.createElement('div');card.className='candidate-card';const title=document.createElement('strong');title.textContent=[candidate.color,candidate.category==='모형폰'?'휴대폰':candidate.category].filter(Boolean).join(' ');const info=document.createElement('span');info.textContent='후보 '+candidate.candidate_no;card.append(title,info);cards.append(card);}li.append(cards);
}
fetch('/health').then(r=>r.json()).then(data=>{
 $('chatMode').textContent=data.chat_search_mode==='demo_sqlite'?'안내 + 가상 물건 DB 시연':data.chat_search_mode==='postgres'?'안내 + 인증 연계가 필요한 DB 조회':'문서 기반 이용 안내';
}).catch(()=>{$('chatMode').textContent='연결 상태를 확인해주세요';});

$('searchReviewed').onclick=()=>{if(chatBusy||window.ChatVoice?.busy()||!confirmedSearchContext)return;$('chatQuestion').value='확인한 설명으로 찾아줘';$('chatForm').requestSubmit();$('guidance').scrollIntoView({behavior:'smooth',block:'start'});};
