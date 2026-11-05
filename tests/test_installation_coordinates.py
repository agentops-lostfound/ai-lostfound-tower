import copy
import unittest
from vision.installation_coordinates import load_installation,preview_point,preview_report
from vision.installation_coordinates import coordinate_chain, work_context


class InstallationCoordinatesTests(unittest.TestCase):
    def fixture(self):
        c=load_installation()
        r={'coordinate_context':work_context({'markers_mm':c['source_markers_mm']}),
           'calibration':{'valid':True,'homography':[[1,0,0],[0,1,0],[0,0,1]],
                          'correspondence_count':8,'max_reprojection_error_mm':0.2},
           'objects':[{'id':0,'bbox':[12,12,16,16],'center_px':[999,999],
                       'center_world_mm':[999,999],'calibration_valid':True}]}
        return r,c

    def test_chain_recomputes_center_and_updates_settings(self):
        r,c=self.fixture()
        a=coordinate_chain(r,c)
        self.assertEqual(a['objects'][0]['approach_xyz_mm'],[162,143,280])
        changed=copy.deepcopy(c)
        changed['work_xy_to_installation_xy']['offset_mm'][0]+=10
        changed['approach_z_mm']=200
        b=coordinate_chain(r,changed)
        self.assertEqual(b['objects'][0]['approach_xyz_mm'],[172,143,200])
        self.assertNotEqual(a['config_sha256'],b['config_sha256'])
        self.assertFalse(b['robot_authorized'])

    def test_missing_or_changed_source_frame_blocks_coordinates(self):
        for missing in [True,False]:
            r,c=self.fixture()
            if missing:r.pop('coordinate_context')
            else:r['coordinate_context']['markers_mm']['0'][0][0]=42
            row=coordinate_chain(r,c)['objects'][0]
            self.assertEqual(row['status'],'work_frame_unverified')
            self.assertNotIn('approach_xyz_mm',row)

    def test_invalid_homography_and_calibration_are_blocked(self):
        r,c=self.fixture()
        r['calibration']['homography']=[[1]]
        self.assertEqual(coordinate_chain(r,c)['objects'][0]['status'],'invalid_homography')
        r['calibration']['valid']=False
        self.assertEqual(coordinate_chain(r,c)['objects'][0]['status'],'calibration_unavailable')

    def test_duplicate_identity_rejected(self):
        r,c=self.fixture();r['objects']*=2
        with self.assertRaises(ValueError):coordinate_chain(r,c)

    def test_shared_corners_match_measured_geometry(self):
        c=load_installation()
        self.assertEqual(preview_point([14,14],c)['xy_mm'],[162,143])
        self.assertEqual(preview_point([338,164],c)['xy_mm'],[-162,293])
        self.assertEqual(preview_point([0,0],c)['xy_mm'],[176,129])

    def test_z_is_separate_from_floor_and_not_motion_permission(self):
        c=load_installation();c['approach_z_mm']=200
        r=preview_point([14,14],c)
        self.assertEqual(r['approach_xyz_mm'],[162,143,200])
        self.assertFalse(r['robot_authorized'])

    def test_invalid_coordinates_fail(self):
        for p in [[float('nan'),0],[True,0],[1],None]:
            with self.assertRaises(ValueError):preview_point(p,load_installation())

    def test_calibration_failure_does_not_expose_preview(self):
        obj={'id':1,'center_world_mm':[14,14],'calibration_valid':True}
        r=preview_report({'calibration':{'valid':False},'objects':[obj]},load_installation())
        self.assertNotIn('approach_xyz_mm',r['objects'][0])
        self.assertFalse(r['robot_authorized'])
