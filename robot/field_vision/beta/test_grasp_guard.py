import unittest
from .grasp_guard import decide


class GuardTests(unittest.TestCase):
    def test_initial_projected_overlap_does_not_stop_as_contact(self):
        telemetry={'load_magnitude':0,'current_magnitude':0}
        visual={'valid':True,'bilateral_contact_candidate':True}
        self.assertFalse(decide(telemetry,telemetry,visual,visual,50)['stop_closing'])

    def test_load_rise_stops_without_claiming_success(self):
        result=decide({'load_magnitude':3,'current_magnitude':2},{'load_magnitude':20,'current_magnitude':2},{},{},30)
        self.assertTrue(result['stop_closing']);self.assertFalse(result['grasp_success'])

    def test_new_visual_contact_stops(self):
        t={'load_magnitude':0,'current_magnitude':0}
        self.assertTrue(decide(t,t,{},dict(valid=True,bilateral_contact_candidate=True),30)['stop_closing'])
