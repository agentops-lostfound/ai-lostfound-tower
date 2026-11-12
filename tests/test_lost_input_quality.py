"""Description and synthetic-media edge cases; no operational DB or models."""
import base64
import io
import unittest
import wave
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agents.lost_api import create_app
from agents.lost_input import DescriptionService, build_description_graph
from agents.lost_photo import OllamaPhoto
from agents.search_context import checked_context


def photo_bytes():
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (8, 8), 'pink').save(output, format='PNG')
    return output.getvalue()


class InputQualityTests(unittest.TestCase):
    meta = {'lost_date': '2026-11-10', 'lost_line': '1호선', 'lost_station': '초량역'}

    def test_explicit_correction_is_used_by_service_and_http_graph(self):
        for text, category, color in [('검정 아니고 흰색 립밤', '립밤', '흰색'),
                                      ('휴대폰 말고 파랑 보조배터리', '보조배터리', '파랑'),
                                      ('빨강 아니고 보라색 립밤', '립밤', '기타')]:
            for proposal in (DescriptionService().from_text({'text': text}),
                             build_description_graph(DescriptionService()).invoke({'payload': {'text': text}})['proposal']):
                self.assertEqual(proposal['description'], {'category': category, 'color': color})

    def test_multiple_items_and_colors_remain_unknown_for_review(self):
        result = DescriptionService().from_text({'text': '검정 휴대폰과 흰색 립밤'})
        self.assertEqual(result['description']['category'], '확인 불가')
        self.assertNotIn('color', result['description'])
        self.assertEqual(len(result['warnings']), 2)

    def test_confirmed_color_and_location_are_accepted_by_search_context(self):
        service = DescriptionService()
        proposal = service.from_text({'text': '분홍 립밤', **self.meta})
        confirmed = service.confirm(proposal['proposal_id'], {'confirmed': True})
        context = {**self.meta, 'category': confirmed['description']['category'], 'color': confirmed['description']['color']}
        self.assertEqual(checked_context(context)['color'], '분홍')
        for payload in ({'description': {'category': '립밤', 'color': '투명빨강'}}, {'lost_line': '아무호선'}, {'lost_station': ''}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                service.confirm(proposal['proposal_id'], {'confirmed': True, **payload})

    def test_unknown_color_is_omitted_instead_of_becoming_an_invalid_search_condition(self):
        service = DescriptionService()
        proposal = service.from_text({'text': '립밤', **self.meta})
        confirmed = service.confirm(proposal['proposal_id'], {'confirmed': True, 'description': {'category': '립밤', 'color': '확인 불가'}})
        self.assertNotIn('color', confirmed['description'])

    def test_invalid_metadata_is_rejected_before_inference(self):
        photo, speech = MagicMock(), MagicMock()
        service = DescriptionService(photo_extractor=photo, transcriber=speech)
        for action in (lambda: service.from_photo(b'photo', {'lost_date': 'invalid'}),
                       lambda: service.from_audio('unused.wav', {'lost_date': 'invalid'})):
            with self.assertRaises(ValueError):
                action()
        photo.assert_not_called(); speech.assert_not_called()

    def test_pink_photo_matches_text_and_invalid_top_level_response_is_controlled(self):
        import json
        replies = iter(['lip_balm', 'pink'])
        model = OllamaPhoto(request=lambda _: {'message': {'content': json.dumps({'answer': next(replies)})}})
        self.assertEqual(model(photo_bytes()), {'category': '립밤', 'color': '분홍'})
        for raw in ('null', '[]', '1', '{"answer":[]}'):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                OllamaPhoto(request=lambda _: {'message': {'content': raw}})(photo_bytes())

    def test_photo_backend_failure_does_not_leak_details_or_save_a_proposal(self):
        service = DescriptionService(photo_extractor=MagicMock(side_effect=TimeoutError('synthetic-internal-secret')))
        with TestClient(create_app(service), base_url='http://127.0.0.1') as client:
            photo = 'data:image/png;base64,' + base64.b64encode(photo_bytes()).decode()
            response = client.post('/descriptions/photo', json={'photo': photo})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('synthetic-internal-secret', response.text)
        self.assertIn('글로 설명', response.json()['detail'])
        self.assertFalse(service._pending)

    def test_malformed_speech_response_is_controlled_and_worker_is_closed(self):
        for result in (None, [], 'transcribed'):
            worker = MagicMock(); worker.__enter__.return_value = worker; worker.transcribe.return_value = result
            service = DescriptionService(transcriber=lambda: worker)
            with self.assertRaises(RuntimeError):
                service.from_audio('unused.wav', {})
            worker.__exit__.assert_called_once()
            self.assertFalse(service._pending)
