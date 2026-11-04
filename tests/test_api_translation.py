import io
import json
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from matching.api_translation import DeepLQueryParser


class APITests(unittest.TestCase):
    def test_missing_key_no_network(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError):
                DeepLQueryParser()

    def test_payload_contains_only_user_text(self):
        transport=Mock(return_value=io.BytesIO(json.dumps({'translations':[{'text':'My white iPhone has a badly cracked back.'}]}).encode()))
        with patch.dict('os.environ',{'DEEPL_AUTH_KEY':'test-not-real:fx'}):
            parser=DeepLQueryParser(transport=transport)
            events=[]
            result=parser.parse('test description',lambda stage,value:events.append(value))
        request=transport.call_args.args[0]
        self.assertEqual(request.full_url,'https://api-free.deepl.com/v2/translate')
        self.assertEqual(json.loads(request.data),{'text':['test description'],'source_lang':'KO','target_lang':'EN-US'})
        self.assertEqual(result['features']['colors'],['white'])
        self.assertTrue(result['requires_review'])
        self.assertNotIn('test-not-real',str(events)+str(result))
        transport.assert_called_once()

    def test_api_error_is_redacted_and_not_retried(self):
        transport=Mock(side_effect=HTTPError('https://api.deepl.com',403,'sensitive response',{},None))
        with patch.dict('os.environ',{'DEEPL_AUTH_KEY':'test-not-real'}):
            with self.assertRaises(RuntimeError) as caught:
                DeepLQueryParser(transport=transport).parse('hello')
        self.assertNotIn('sensitive',str(caught.exception))
        self.assertNotIn('test-not-real',str(caught.exception))
        transport.assert_called_once()

    def test_malformed_result_and_offline_rejected(self):
        with patch.dict('os.environ',{'DEEPL_AUTH_KEY':'test-not-real'}):
            with self.assertRaises(ValueError):
                DeepLQueryParser(offline=True)
            transport=Mock(return_value=io.BytesIO(b'{"translations": []}'))
            with self.assertRaises(ValueError):
                DeepLQueryParser(transport=transport).parse('hello')
