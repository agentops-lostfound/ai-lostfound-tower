import base64
import io
import json
import unittest
import wave
from datetime import date
from unittest.mock import MagicMock, patch
from agents.lost_input import DescriptionService, text_features, location, build_description_graph
from agents.lost_photo import OllamaPhoto, prepare_photo


class DescriptionTests(unittest.TestCase):
    def test_explicit_text_fields_and_location(self):
        desc, _ = text_features("검은 플라스틱 립밤에 별 모양 스티커가 있어요")
        self.assertEqual(desc, {"category": "립밤", "color": "검정", "material": "플라스틱", "mark": "별 모양 스티커"})
        self.assertEqual(location({}, "어제 1호선 중앙역", date(2026, 11, 4)),
                         {"lost_date": "2026-11-03", "lost_line": "1호선", "lost_station": "중앙역"})

    def test_ambiguous_color_and_negation_are_not_guessed(self):
        desc, warnings = text_features("검정 아니고 흰색 립밤")
        self.assertNotIn("color", desc)
        self.assertTrue(warnings)

    def test_no_material_inferred_and_pii_rejected(self):
        self.assertNotIn("material", text_features("검정 립밤")[0])
        with self.assertRaises(ValueError):
            text_features("립밤 연락처 010-1234-5678")

    def test_black_color_does_not_also_match_silver(self):
        desc, warnings = text_features("햄스터 키링 달린 검은색 휴대폰")
        self.assertEqual(desc["color"], "검정")
        self.assertEqual(desc["category"], "모형폰")
        self.assertEqual(warnings, [])
        self.assertEqual(text_features("은색 휴대폰")[0]["color"], "회색")

    def test_keyring_preserved_without_claiming_sticker(self):
        from agents.lost_search import matching_query
        desc, _ = text_features("햄스터 키링 달린 검은색 휴대폰")
        self.assertEqual(desc["mark"], "햄스터 키링")
        query = matching_query(desc)
        self.assertEqual(query["sticker_status"], "unknown")
        self.assertEqual(query["free_text"], "햄스터 키링")
        self.assertEqual(query["category"], "phone")
        self.assertEqual(query["colors"], ["black"])
        self.assertEqual(matching_query(text_features("별 스티커와 토끼 키링 달린 립밤")[0])["sticker_status"], "present")
        self.assertNotIn("mark", text_features("키링 없는 검정 휴대폰")[0])

    def test_search_preview_uses_confirmed_handoff_and_hides_private_fields(self):
        from agents.lost_search import preview_candidates
        service = DescriptionService()
        proposal = service.from_text({"text": "햄스터 키링 달린 검은색 휴대폰", "lost_date": "2026-11-03", "lost_line": "1호선", "lost_station": "다대포해수욕장역"})
        with self.assertRaises(ValueError):
            preview_candidates(proposal, [])
        handoff = service.confirm(proposal["proposal_id"], {"confirmed": True})
        candidates = [{"item_id": "A-W01", "features": {"category": "모형폰", "color": "검정", "mark": "햄스터 키링"}},
                      {"item_id": "A-W02", "features": {"category": "립밤", "color": "갈색", "mark": "비공개 정답"}}]
        result = preview_candidates(handoff, candidates)
        self.assertIn("A-W01", result["candidate_item_ids"])
        self.assertNotIn("A-W02", result["candidate_item_ids"])
        self.assertNotIn("비공개 정답", str(result))
        self.assertTrue(result["review_required"])
        self.assertFalse(result["reservation_created"])

    def test_retired_category_lipbalm_is_not_handed_to_search(self):
        """11/9 카드지갑은 운영 품목이 아님: 제안은 '확인 불가' + 안내, 직접 카드지갑으로 확인해도 검색으로 넘기지 않음"""
        service = DescriptionService()
        meta = {"lost_date": "2026-11-03", "lost_line": "1호선", "lost_station": "중앙역"}
        proposal = service.from_text({"text": "흰색 카드지갑", **meta})
        self.assertEqual(proposal["description"]["category"], "확인 불가")
        self.assertIn("운영하지 않는 품목", proposal["warnings"][0])
        with self.assertRaises(ValueError) as cm:
            service.confirm(proposal["proposal_id"], {"confirmed": True})          # 품목을 다시 골라야 함
        self.assertIn("품목", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            service.confirm(proposal["proposal_id"], {"confirmed": True, "description": {"category": "지갑", "color": "흰색"}})
        self.assertIn("운영하지 않는 품목", str(cm.exception))
        handoff = service.confirm(proposal["proposal_id"], {"confirmed": True, "description": {"category": "핸드크림", "color": "흰색"}})
        self.assertEqual(handoff["description"]["category"], "핸드크림")

    def test_preview_then_edited_confirmation_without_identity_bypass(self):
        service = DescriptionService()
        proposal = service.from_text({"text": "검정 립밤", "lost_date": "2026-11-03", "lost_line": "1호선", "lost_station": "중앙역"})
        with self.assertRaises(ValueError):
            service.confirm(proposal["proposal_id"], {})
        handoff = service.confirm(proposal["proposal_id"], {"confirmed": True, "description": {"category": "립밤", "color": "갈색"}, "identity_verified": True})
        self.assertEqual(handoff["description"]["color"], "갈색")
        self.assertFalse(handoff["identity_verified"])
        self.assertNotIn("transcript", handoff)
        self.assertNotIn("photo", handoff)

    def test_missing_context_unknown_category_expired_token(self):
        service = DescriptionService(ttl=10)
        proposal = service.from_text({"text": "작은 물건"})
        self.assertIn("lost_date", proposal["missing_fields"])
        with self.assertRaises(ValueError):
            service.confirm(proposal["proposal_id"], {"confirmed": True})
        with patch("agents.lost_input.time.monotonic", return_value=10**15), self.assertRaises(ValueError):
            service.confirm(proposal["proposal_id"], {"confirmed": True})

    def test_client_edit_cannot_mutate_stored_proposal(self):
        service = DescriptionService()
        proposal = service.from_text({"text": "검정 립밤"})
        proposal["description"]["category"] = "USB"
        self.assertEqual(service._pending[proposal["proposal_id"]][1]["description"]["category"], "립밤")

    def test_speech_closes_worker_and_requires_review(self):
        worker = MagicMock()
        worker.__enter__.return_value = worker
        worker.transcribe.return_value = {"status": "transcribed", "text": "어제 1호선 중앙역 검정 립밤"}
        service = DescriptionService(transcriber=lambda: worker)
        result = service.from_audio("server-owned-temp.wav", {})
        self.assertEqual(result["description"]["category"], "립밤")
        self.assertTrue(result["requires_confirmation"])
        worker.__exit__.assert_called_once()
        self.assertNotIn("transcript", service._pending[result["proposal_id"]][1])

    def test_no_speech_or_unavailable_model_does_not_invent_description(self):
        service = DescriptionService()
        with self.assertRaises(RuntimeError):
            service.from_audio("unused", {})
        worker = MagicMock(); worker.__enter__.return_value = worker
        worker.transcribe.return_value = {"status": "no_speech", "text": ""}
        with self.assertRaises(ValueError):
            DescriptionService(transcriber=lambda: worker).from_audio("unused", {})

    def test_langgraph_extraction_produces_review_proposal(self):
        result = build_description_graph(DescriptionService()).invoke({"payload": {"text": "회색 보조배터리"}})
        self.assertEqual(result["proposal"]["description"], {"category": "보조배터리", "color": "회색"})
        self.assertTrue(result["proposal"]["requires_confirmation"])


class PhotoTests(unittest.TestCase):
    @staticmethod
    def photo():
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (80, 60), "gray").save(buf, format="PNG")
        return buf.getvalue()

    def test_separate_questions_map_only_category_and_color(self):
        replies = iter(["power_bank", "gray"])
        requests = []
        def request(payload):
            requests.append(payload)
            return {"message": {"content": json.dumps({"answer": next(replies)})}}
        desc = OllamaPhoto(request=request)(self.photo())
        self.assertEqual(desc, {"category": "보조배터리", "color": "회색"})
        self.assertEqual(len(requests), 2)
        self.assertNotIn("materials", requests[0]["format"]["properties"])

    def test_multiple_items_and_invalid_model_output_rejected(self):
        with self.assertRaises(ValueError):
            OllamaPhoto(request=lambda _: {"message": {"content": '{"answer":"multiple_items"}'}})(self.photo())
        with self.assertRaises(RuntimeError):
            OllamaPhoto(request=lambda _: {"message": {"content": '{"answer":"invented"}'}})(self.photo())
        with self.assertRaises(ValueError):
            prepare_photo(b"not an image")


class LostApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from agents.lost_api import create_app
        self.client = TestClient(create_app(DescriptionService()), base_url='http://127.0.0.1')

    def test_suggestion_endpoint_counts_valid_choices_and_serves_ui_assets(self):
        item = self.client.get('/guidance/suggestions').json()['items'][3]
        result = self.client.post('/guidance/questions', json={
            'question': item['text'], 'suggestion_id': item['id']})
        self.assertEqual(result.status_code, 200)
        ranked = self.client.get('/guidance/suggestions').json()
        self.assertEqual(ranked['items'][0]['id'], item['id'])
        self.assertEqual(ranked['items'][0]['count'], 1)
        self.assertFalse(ranked['personal_questions_saved'])
        for asset in ['input.js', 'chat.js', 'suggestions.js', 'style.css']:
            self.assertEqual(self.client.get('/input-assets/' + asset).status_code, 200)

    def test_text_preview_and_document_guidance(self):
        page = self.client.get("/input")
        self.assertEqual(page.status_code, 200)
        self.assertIn("설명 정리하기", page.text)
        r = self.client.post("/descriptions/text", json={"text": "검정 립밤"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/health").json()["guidance_rag"], "project_documents_with_policy_gaps")
        r = self.client.post("/guidance/questions", json={"question": "몇 시까지?"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "answered")           # 11/6 시연 운영 기준(운영시간)
        self.assertIn("시연 기준", r.json()["answer"])

    def test_station_name_is_not_fabric_material(self):
        self.assertNotIn("material", text_features("인천역에서 검정 립밤을 잃었어요")[0])
        self.assertEqual(text_features("천 재질 립밤")[0]["material"], "천")

    def test_invalid_audio_and_missing_speech_model(self):
        self.assertEqual(self.client.post("/descriptions/audio", json={"audio_base64": "bad"}).status_code, 422)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b"\0\0" * 16000)
        r = self.client.post("/descriptions/audio", json={"audio_base64": base64.b64encode(buf.getvalue()).decode()})
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":
    unittest.main()
