"""Canonical production-facing adapter smoke regressions; CPU only."""
import copy
import unittest
from agents.vision_adapter import adapt_report

FEATURES = {"category":"power_bank","colors":["black"],"shape":"rectangle",
 "materials":["plastic"],"logos_or_text":[],"sticker_status":"unknown",
 "stickers":[],"distinctive_features":[]}

def scene():
    return {"sequence":{"status":"complete"},
            "calibration":{"valid":True,"correspondence_count":8,"max_reprojection_error_mm":1.0},
            "objects":[{"id":0,"confidence":0.85,"bbox":[10.,20.,60.,80.],
               "center_px":[35.,50.],"center_world_mm":[100.,200.],
               "calibration_valid":True,"qwen":{"status":"ok","features":copy.deepcopy(FEATURES)}}]}

class UnifiedAdapterTest(unittest.TestCase):
    def test_valid_two_marker_mm(self):
        d=adapt_report(scene())
        self.assertEqual(len(d),1)
        self.assertEqual(d[0]['center'],[35.,50.])
        self.assertEqual(d[0]['center_mm'],[100.,200.])
        self.assertEqual(d[0]['features']['category'],'보조배터리')

    def test_calibration_missing_keeps_features_blocks_mm(self):
        r=scene();r['calibration']['valid']=False
        d=adapt_report(r)
        self.assertEqual(len(d),1)
        self.assertNotIn('center_mm',d[0])

    def test_one_marker_blocks_mm(self):
        r=scene();r['calibration']['correspondence_count']=4
        self.assertNotIn('center_mm',adapt_report(r)[0])

    def test_invalid_reprojection_blocks_mm(self):
        for value in (None,float('nan'),float('inf'),-1,4.2):
            r=scene();r['calibration']['max_reprojection_error_mm']=value
            self.assertNotIn('center_mm',adapt_report(r)[0])

    def test_missing_object_calibration_blocks_mm(self):
        r=scene();del r['objects'][0]['calibration_valid']
        self.assertNotIn('center_mm',adapt_report(r)[0])

    def test_failed_sequence_blocks_mm(self):
        r=scene();r['sequence']['status']='failed'
        d=adapt_report(r)
        self.assertEqual(len(d),1)
        self.assertNotIn('center_mm',d[0])

    def test_failed_qwen_blocks_mm(self):
        r=scene();r['objects'][0]['qwen']['status']='failed'
        d=adapt_report(r)
        self.assertEqual(len(d),1)
        self.assertNotIn('center_mm',d[0])

    def test_unknown_category_blocks_mm(self):
        r=scene();r['objects'][0]['qwen']['features']['category']='other'
        d=adapt_report(r)
        self.assertEqual(len(d),1)
        self.assertNotIn('center_mm',d[0])

    def test_duplicate_object_id_rejects_scene(self):
        r=scene();r['objects'].append(copy.deepcopy(r['objects'][0]))
        self.assertEqual(adapt_report(r),[])

    def test_nan_geometry_skipped(self):
        r=scene();r['objects'][0]['center_px']=[float('nan'),50]
        self.assertEqual(adapt_report(r),[])

if __name__=='__main__':unittest.main()
