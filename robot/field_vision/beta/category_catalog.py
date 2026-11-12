"""Persisted, editable detection vocabulary; existing item rows are untouched."""
import json,re,threading,time
from pathlib import Path

LOCK=threading.RLock()


class Catalog:
    def __init__(self,path,classes,prompts,names):
        self.path=Path(path);self.classes=classes;self.prompts=prompts;self.names=names
        defaults=[dict(id=k,name=names.get(k,k),description=v,prompts=list(prompts[k]),enabled=True) for k,v in classes.items()]
        self.rows=json.loads(self.path.read_text(encoding='utf8')) if self.path.exists() else defaults
        self.validate(self.rows);self.apply()

    def validate(self,rows):
        if not isinstance(rows,list) or len(rows)>32:raise ValueError('카테고리는 최대32개입니다.')
        seen=set()
        for r in rows:
            if not isinstance(r,dict) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}',str(r.get('id',''))):raise ValueError('카테고리 ID는 영문 소문자로 시작하는 영문·숫자·밑줄40자 이내입니다.')
            if r['id'] in seen:raise ValueError('중복 카테고리 ID입니다.')
            seen.add(r['id'])
            if not isinstance(r.get('name'),str) or not 1<=len(r['name'].strip())<=50:raise ValueError('표시 이름은1~50자입니다.')
            if not isinstance(r.get('description'),str) or not 1<=len(r['description'].strip())<=160:raise ValueError('영어 물품 설명은1~160자입니다.')
            if not re.search('[A-Za-z]',r['description']):raise ValueError('영어 물품 설명을 입력하세요. 예: portable power bank')
            if type(r.get('enabled')) is not bool:raise ValueError('활성화 값이 필요합니다.')
            if not isinstance(r.get('prompts'),list) or not 1<=len(r['prompts'])<=5 or any(not isinstance(p,str) or not 1<=len(p.strip())<=160 or not re.search('[A-Za-z]',p) for p in r['prompts']):raise ValueError('영어 검출 문구는1~5개, 각160자 이내입니다.')

    def apply(self):
        self.classes.clear();self.prompts.clear();self.names.clear()
        for r in self.rows:
            self.names[r['id']]=r['name']
            if r['enabled']:
                self.classes[r['id']]=r['description'];self.prompts[r['id']]=list(r['prompts'])

    def snapshot(self):
        with LOCK:return json.loads(json.dumps(self.rows))

    def change(self,operation,row=None,category_id=None):
        with LOCK:
            rows=self.snapshot()
            if operation=='save':
                if row is None:raise ValueError('카테고리 입력이 필요합니다.')
                rows=[r for r in rows if r['id']!=row.get('id')]+[row]
            elif operation=='delete':
                if not any(r['id']==category_id for r in rows):raise ValueError('카테고리를 찾지 못했습니다.')
                rows=[r for r in rows if r['id']!=category_id]
            else:raise ValueError('지원하지 않는 카테고리 작업')
            self.validate(rows)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(self.path)
            self.rows=rows;self.apply()
            return self.snapshot()
