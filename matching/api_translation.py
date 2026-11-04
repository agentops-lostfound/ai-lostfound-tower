"""DeepL text translation: source text only, no candidate data or model uploads."""
import json
import os
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .translated_query import extract_english


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DeepLQueryParser:
    def __init__(self, offline=False, threads=2, account=None, timeout=30, transport=None):
        if offline:
            raise ValueError('DeepL requires network access; omit --offline')
        self._key = os.environ.get('DEEPL_AUTH_KEY') or os.environ.get('DEEPL_API_KEY')
        if not self._key:
            raise ValueError('Set DEEPL_AUTH_KEY in your local terminal; do not paste the key into chat or commit it.')
        account = account or ('free' if self._key.endswith(':fx') else 'pro')
        if account not in ('free','pro') or timeout <= 0:
            raise ValueError('Invalid DeepL account or timeout')
        self.endpoint = 'https://api-free.deepl.com/v2/translate' if account=='free' else 'https://api.deepl.com/v2/translate'
        self.timeout, self.init_seconds = timeout, 0.0
        self.model_id = 'DeepL API (provider-managed)'
        self._transport = transport or build_opener(NoRedirect()).open

    def parse(self, text, on_event=None):
        if not isinstance(text,str) or not text.strip() or len(text)>1500:
            raise ValueError('Description must contain 1..1500 characters')
        started=perf_counter()
        emit=on_event or (lambda stage,value:None)
        emit('input',{'original_text':text})
        payload={'text':[text], 'source_lang':'KO', 'target_lang':'EN-US'}
        emit('prompt',{'input_tokens':None,'messages':[{'role':'translation_text','content':text}],
                      'provider':'DeepL','endpoint':self.endpoint,'source_lang':'KO','target_lang':'EN-US',
                      'note':'One HTTP request; authentication header is not logged; no automatic retries.'})
        request=Request(self.endpoint, data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
                        headers={'Authorization':'DeepL-Auth-Key '+self._key,'Content-Type':'application/json'},method='POST')
        try:
            with self._transport(request,timeout=self.timeout) as response:
                data=json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            # Never include request headers, raw response bodies or credentials in logs.
            raise RuntimeError(f'DeepL HTTP {error.code}; check API access, quota or account type. No retry performed.') from None
        except (URLError,TimeoutError,OSError):
            raise RuntimeError('DeepL connection failed or timed out. No retry performed; request billing status may be unknown.') from None
        except (ValueError,UnicodeError):
            raise ValueError('DeepL returned invalid JSON') from None
        translations=data.get('translations') if isinstance(data,dict) else None
        if not isinstance(translations,list) or len(translations)!=1 or not isinstance(translations[0],dict):
            raise ValueError('DeepL response must contain one translation')
        translation=translations[0].get('text')
        result=extract_english(translation)
        emit('model_output',{'raw_text':translation,'output_tokens':None,'elapsed_seconds':perf_counter()-started})
        emit('validated',{'translation':translation,'method':'English rules after one DeepL request',**result})
        return {'original_text':text,'translation':translation,**result,'requires_review':True,
                'model':self.model_id,'mode':'deepl_translate_then_rules','device':'remote_api',
                'timing':{'model_init_seconds':0.0,'parse_seconds':perf_counter()-started,'output_tokens':None}}
