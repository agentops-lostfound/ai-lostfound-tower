import unittest
from run_pipeline import match_report
from test_qwen_bridge import fixture, FakeMatcher


class Parser:
    def parse(self, text):
        return {'features': {'category': 'phone'}, 'needs_clarification': False,
                'requires_review': True}


class PipelineTests(unittest.TestCase):
    def test_report_coordinates_and_review_survive_integration(self):
        report, _ = fixture()
        report['calibration']={'valid':True,'correspondence_count':8,'max_reprojection_error_mm':.5}
        report['objects'][0].update(confidence=.9, calibration_valid=True, center_world_mm=[25,35])
        result=match_report(report,'query',Parser(),FakeMatcher())
        self.assertEqual(result['candidates'][0]['center_mm'],[25,35])
        self.assertEqual(result['matching']['engine_decision']['status'],'matched')
        self.assertEqual(result['matching']['final_decision']['status'],'needs_confirmation')
        self.assertFalse(result['robot_authorized'])

    def test_incomplete_report_never_exposes_target_candidates(self):
        report, _ = fixture()
        report['sequence']['status']='failed'
        report['objects'][0]['confidence']=.9
        result=match_report(report,'query',Parser(),FakeMatcher())
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['matching']['contract_result']['reason'],'sequence_incomplete')
