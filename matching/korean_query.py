"""Evidence-preserving Korean rules, dictionary slots, phrase translation."""
import re
from time import perf_counter
from .translated_query import OpusQueryParser

CATEGORIES = [
 ('card_wallet',r'카드\s*지갑|카드홀더'), ('power_bank',r'보조\s*배터리'),
 ('usb',r'USB|유에스비|메모리\s*스틱'), ('lip_balm',r'립밤'), ('hand_cream',r'핸드크림'),
 ('wallet',r'지갑'), ('phone',r'아이폰|스마트폰|휴대폰|핸드폰|폰')]
COLORS = [
 ('dark blue',r'진한\s*파란색|진한\s*파랑|짙은\s*파란색'),
 ('navy',r'남색|곤색|네이비'), ('blue',r'파란색|파란|파랑|푸른색|푸른|퍼런색'),
 ('white',r'하얀색|하얀|흰색|흰'), ('black',r'검정색|검정|검은색|검은|까만색|까만'),
 ('red',r'빨간색|빨간|빨강|빨갛|붉은색'), ('yellow',r'노란색|노란|노랑'),
 ('green',r'초록색|초록|녹색'), ('pink',r'분홍색|분홍|핑크'), ('orange',r'주황색|주황'),
 ('purple',r'보라색|보라'), ('gray',r'회색'), ('brown',r'갈색'), ('silver',r'은색'), ('gold',r'금색|황금색')]
DETAIL = r'스티커|데칼|깨|파손|박살|작살|흠집|긁|금이|금이나|균열|카메라|렌즈|로고|적혀|쓰여|써\s*있|가죽|플라스틱|무늬|테두리|가장자리|원통|사각|직사각'


def span(text, start, end, value=None):
    item={'text':text[start:end], 'start':start, 'end':end}
    if value is not None:
        item['normalized']=value
    return item


def extract_korean(text):
    if not isinstance(text,str) or not text.strip() or len(text)>1500:
        raise ValueError('Description must contain 1..1500 characters')
    warnings=[]
    evidence={'category':[], 'colors':[], 'stickers':[], 'logos_or_text':[], 'free_phrases':[], 'negated_colors':[], 'scoped_colors':[]}
    for m in re.finditer(r'[A-Za-z][A-Za-z0-9-]{1,30}',text):
        if m.group().lower() not in ('usb','iphone'):
            evidence['logos_or_text'].append(span(text,*m.span()))
    occupied=set()
    categories=[]
    for value,pattern in CATEGORIES:
        for m in re.finditer(pattern,text,re.I):
            if any(i in occupied for i in range(*m.span())):
                continue
            occupied.update(range(*m.span()))
            if re.match(r'\s*(?:은|는|이|가)?\s*아니',text[m.end():]):
                warnings.append('Negated category requires review.')
                continue
            evidence['category'].append(span(text,*m.span(),value))
            if value not in categories:
                categories.append(value)
    category=categories[0] if len(categories)==1 else 'unknown'
    if len(categories)>1:
        warnings.append('Multiple Korean category mentions require review.')
    occupied=set()
    colors=[]
    for value,pattern in COLORS:
        for m in re.finditer(pattern,text):
            if any(i in occupied for i in range(*m.span())):
                continue
            occupied.update(range(*m.span()))
            after=text[m.end():]
            if re.match(r'\s*(?:은|는|이|가|도)?\s*아니',after):
                evidence['negated_colors'].append(span(text,*m.span(),value))
                continue
            if re.match(r'\s*(?:화면|케이스|커버|스티커|로고)',after):
                evidence['scoped_colors'].append(span(text,*m.span(),value))
                continue
            evidence['colors'].append(span(text,*m.span(),value))
            if value not in colors:
                colors.append(value)
    color_spans=evidence['colors']
    if len(colors)>1 and any(re.match(r'\s*(?:인지|또는|아니면)',text[e['end']:]) for e in color_spans):
        warnings.append('Korean color alternatives were left unspecified.')
        colors=[]
    if evidence['scoped_colors'] and not colors:
        warnings.append('Only a component color was stated; body color is unknown.')
    sticker='unknown'
    statuses=[]
    for clause in re.finditer(r'[^.!?。\n,]+',text):
        part=clause.group()
        if re.search(r'스티커|데칼',part):
            # Unknown status must not be interpreted as absence or presence.
            if re.search(r'모르|기억\s*안|불확실',part):
                warnings.append('Sticker status is uncertain in the Korean source.')
            else:
                absent=bool(re.search(r'(?:스티커|데칼).*(?:없|안\s*붙)',part))
                scoped=bool(re.search(r'(?:뒷면|뒤쪽|앞면|옆면|뒤|앞)(?:에|에는|쪽에는)',part))
                if absent and scoped:
                    warnings.append('Scoped Korean sticker absence is not global absence.')
                else:
                    statuses.append('absent' if absent else 'present')
            evidence['stickers'].append(span(text,*clause.span()))
        if re.search(DETAIL,part):
            # Keep linked location/severity/negation in the original clause, not isolated words.
            evidence['free_phrases'].append(span(text,*clause.span()))
    if len(set(statuses))==1:
        sticker=statuses[0]
    elif len(set(statuses))>1:
        warnings.append('Conflicting sticker statements require review.')
    return {'features':{'category':category,'colors':colors,'sticker_status':sticker},
            'evidence':evidence,'warnings':warnings,'needs_clarification':bool(warnings)}


class KoreanFirstParser:
    def __init__(self,offline=False,threads=2,translator=None):
        self.translator=translator or OpusQueryParser(offline=offline,threads=threads)
        self.model_id='Korean dictionary/rules + '+self.translator.model_id
        self.init_seconds=self.translator.init_seconds

    def parse(self,text,on_event=None):
        started=perf_counter()
        emit=on_event or (lambda stage,value:None)
        emit('input',{'original_text':text})
        extracted=extract_korean(text)
        emit('korean_extraction',extracted)
        phrases=[s['text'].strip() for s in extracted['evidence']['free_phrases']]
        translation=''
        tokens=0
        translation_seconds=0.0
        if phrases:
            result=self.translator.parse('\n'.join(phrases),on_event=lambda stage,value: emit(stage,value) if stage in ('prompt','model_output') else None)
            translation=result['translation']
            tokens=result['timing']['output_tokens']
            translation_seconds=result['timing']['parse_seconds']
        warnings=list(extracted['warnings'])
        if re.search(r'\bgold\b',translation,re.I) and not re.search(r'금색|황금',text):
            warnings.append('Translation contains gold without a Korean gold-color statement; inspect crack ambiguity.')
        free=translation
        for logo in extracted['evidence']['logos_or_text']:
            if logo['text'].lower() not in free.lower():
                free=(free+' Visible text: '+logo['text']+'.').strip()
        if '아이폰' in text and 'iphone' not in free.lower():
            free=('Brand: iPhone. '+free).strip()
        if re.search(r'깨|파손|박살|작살|흠집|긁|금이|금이나|균열',text) and not re.search(r'break|broke|crack|damag|shatter|scratch|scuff|chip|scrap',translation,re.I):
            warnings.append('A Korean damage statement may have been lost in phrase translation.')
        features={**extracted['features'],'free_text':free}
        emit('validated',{'features':features,'translation':translation,'warnings':warnings,
                         'method':'Korean evidence + dictionary attributes + clause translation'})
        return {'original_text':text,'features':features,'korean_extraction':extracted,'translation':translation,
                'needs_clarification':bool(warnings),'warnings':warnings,'requires_review':True,
                'model':self.model_id,'mode':'korean_first','device':'cpu',
                'timing':{'model_init_seconds':self.init_seconds,'parse_seconds':perf_counter()-started,
                          'translation_seconds':translation_seconds,'output_tokens':tokens}}
