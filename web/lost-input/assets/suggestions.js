(function(root){
  const normalize=value=>String(value||'').normalize('NFKC').toLowerCase().replace(/[\s\u200b-\u200d\ufeff?？.!]/g,'');
  function rank(items,query){
    const q=normalize(query);
    return items.map((item,index)=>{
      const text=normalize(item.text),keys=item.keywords||[];
      let score=!q?1:text.includes(q)?30:q.includes(text)?20:0;
      for(const key of keys){const k=normalize(key);if(q&&(q.includes(k)||k.includes(q)))score+=8;}
      return {item,index,score};
    }).filter(row=>row.score>0).sort((a,b)=>b.score-a.score||(b.item.count||0)-(a.item.count||0)||a.index-b.index).slice(0,3).map(row=>row.item);
  }
  const api={normalize,rank};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.GuidanceSuggestions=api;
})(typeof window==='undefined'?{}:window);
