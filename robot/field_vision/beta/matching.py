"""Conservative explicit body-color comparison; scores are not probabilities."""
import re

FAMILIES={'light blue':'blue','sky blue':'blue','navy':'blue','blue':'blue','pink':'pink','rose':'pink',
 'red':'red','green':'green','mint':'green','yellow':'yellow','orange':'orange','purple':'purple',
 'violet':'purple','white':'white','black':'black','gray':'gray','grey':'gray','brown':'brown','beige':'beige'}

def body_color(features):
    # Never infer a body color from the old unordered colors list.
    value=str((features or {}).get('body_color','unknown')).strip().lower()
    if value in FAMILIES: return FAMILIES[value]
    return None

def color_evidence(query,reference):
    a,b=body_color(query),body_color(reference)
    if not a or not b: return {'status':'unknown','penalty':0.,'query':a,'reference':b}
    if a==b: return {'status':'same','penalty':0.,'query':a,'reference':b}
    # Pale hue boundaries can move with lighting; do not strongly penalize these pairs.
    # v0.2.62 (flow-2f846d0a): a tight YOLO crop of a black SanDisk on green foam read as
    # 'blue' -> 0.30 penalty dropped the right item from 0.90 to 0.59. Dark bodies pick up
    # the foam's green/blue cast; silver/gray metal reflects it too.
    uncertain=[{'blue','green'},{'pink','red'},{'white','gray'},{'brown','beige'},{'orange','red'},{'purple','pink'},
               {'black','blue'},{'black','green'},{'black','gray'},{'gray','blue'},{'gray','green'}]
    if {a,b} in uncertain: return {'status':'uncertain','penalty':0.,'query':a,'reference':b}
    return {'status':'conflict','penalty':.30,'query':a,'reference':b}

def text_features(text):
    text=text.lower()
    aliases={'하늘색':'blue','파란색':'blue','파란':'blue','파랑':'blue','분홍색':'pink','분홍':'pink','핑크':'pink',
             '검정':'black','검은':'black','흰색':'white','하얀':'white','초록':'green','녹색':'green','빨간':'red','빨강':'red'}
    found={v for k,v in aliases.items() if k in text}
    found.update(FAMILIES[k] for k in FAMILIES if re.search(r'\b'+re.escape(k)+r'\b',text))
    return {'body_color':next(iter(found)) if len(found)==1 else 'unknown'}


# v0.2.67: the search sentence was compared only with reference photos (SigLIP), so a word
# that exists only in an item's ID/name/notes (e.g. brand "axxen") changed nothing and the
# visually closest USB won. Distinctive words (not colors, not category words) now add a bonus.
GENERIC_WORDS={'usb','flash','drive','memory','stick','item','물건','물품','색','색깔','the','a','of','and',
               '하늘색','파란색','파란','파랑','분홍색','분홍','핑크','검정','검은','검은색','검정색','흰색','하얀','하얀색',
               '초록','녹색','빨간','빨강','빨간색','회색','은색','silver','light','sky','dark'}|set(FAMILIES)
NAME_BONUS,NAME_BONUS_MAX=.10,.20

def words(text):
    return [w for w in re.split(r'[^0-9a-z가-힣]+',str(text or '').lower()) if w]

def name_terms(text,generic=()):
    skip=GENERIC_WORDS|{w for g in generic for w in words(g)}
    return sorted({w for w in words(text) if len(w)>=2 and w not in skip})

def name_match(terms,item_id,name='',notes=''):
    own=set(words(f'{item_id} {name} {notes}'))
    hit=[t for t in terms if t in own or any(len(w)>=2 and (t in w or (len(w)>=3 and w in t)) for w in own)]
    return hit,min(NAME_BONUS_MAX,NAME_BONUS*len(hit))


# v0.2.73: "하늘색 핸드폰" ranked axxen_usb first (0.114 vs sky_phone 0.108) because text-photo
# scores are low and close across categories. A query that names exactly one category
# searches only that category.
CATEGORY_WORDS={'phone':['핸드폰','휴대폰','스마트폰','폰','phone','iphone','갤럭시'],'wallet':['지갑','카드지갑','wallet'],
                'hand_cream':['핸드크림','핸드 크림','hand cream'],'lip_balm':['립밤','립 밤','lip balm','립스틱'],
                'power_bank':['보조배터리','보조 배터리','배터리','power bank','powerbank'],'usb':['usb','유에스비','메모리','플래시']}

def query_category(text,catalog=()):
    text=str(text or '').lower();found=set()
    words={k:list(v) for k,v in CATEGORY_WORDS.items()}
    for row in catalog:
        words.setdefault(row['id'],[]).extend([row['id'].lower(),str(row.get('name','')).lower()])
    for cid,ws in words.items():
        if any(w and w in text for w in ws):found.add(cid)
    return next(iter(found)) if len(found)==1 else None
