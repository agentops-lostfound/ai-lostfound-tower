"""설치된 실제 SDK + 로컬 Langfuse API 대역. 클라우드 전송은 하지 않는다."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from agents import observability, prompts
from agents.chat_agents import AgentBrain


class SdkProtocolTest(unittest.TestCase):
    def test_actual_sdk_reads_staging_without_trace_posts(self):
        try:
            import langfuse  # noqa: F401
        except ImportError:
            self.skipTest('optional Langfuse SDK not installed')
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(('GET', self.path))
                body = json.dumps({'name': 'chat-planner', 'version': 7, 'type': 'text', 'prompt': 'safe SDK template',
                                   'config': {'model': 'sdk-model', 'temperature': .1, 'use_llm': True},
                                   'labels': ['staging'], 'tags': []}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                requests.append(('POST', self.path))
                self.send_response(500)
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = {'LF_LANGFUSE': '0', 'LF_PROMPT_FETCH': '1', 'LF_PROMPT_LABEL': 'staging',
               'LANGFUSE_PUBLIC_KEY': f'fake-public-{server.server_port}', 'LANGFUSE_SECRET_KEY': 'fake-private',
               'LANGFUSE_BASE_URL': f'http://127.0.0.1:{server.server_port}'}
        prompts._CACHE.clear()
        prompts._READ_CACHE.clear()
        try:
            with mock.patch.dict(os.environ, env), mock.patch.object(observability, 'client', return_value=None), prompts.usage_scope():
                payloads = []
                b = AgentBrain('base', request=lambda p: payloads.append(p) or {'message': {'content': '{"steps":["guidance"]}'}})
                self.assertEqual(b.plan('사용법 안내'), ['guidance'])
                row = prompts.loaded_versions()[0]
                self.assertEqual((row['label'], row['version'], row['model']), ('staging', 7, 'sdk-model'))
                self.assertEqual(payloads[0]['messages'][0]['content'], 'safe SDK template')
                self.assertTrue(prompts.usage_summary()['staging_provenance_complete'])
                for c in prompts._READ_CACHE.values():
                    c.shutdown()
            self.assertTrue(any('label=staging' in path for method, path in requests if method == 'GET'))
            self.assertFalse(any(method == 'POST' for method, _ in requests))
        finally:
            prompts._CACHE.clear()
            prompts._READ_CACHE.clear()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
