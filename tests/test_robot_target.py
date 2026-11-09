import unittest
from robot.prepare_target import prepare_target
from tests import test_installation_coordinates as fixtures


class RobotTargetTests(unittest.TestCase):
    def test_target_preserves_identity_and_cannot_command_motion(self):
        report,config=fixtures.InstallationCoordinatesTests().fixture()
        result=prepare_target(report,0,config)
        self.assertEqual(result['target']['approach_xyz_mm'],[162,143,280])
        self.assertEqual(result['object_id'],0)
        self.assertFalse(result['robot_authorized'])
        self.assertIsNone(result['transport']['joint_targets'])

    def test_missing_target_rejected(self):
        report,config=fixtures.InstallationCoordinatesTests().fixture()
        with self.assertRaises(ValueError):prepare_target(report,99,config)

    def test_unverified_source_cannot_export_xyz(self):
        report,config=fixtures.InstallationCoordinatesTests().fixture()
        report.pop('coordinate_context')
        result=prepare_target(report,0,config)
        self.assertNotIn('approach_xyz_mm',result['target'])
        self.assertIn('work_frame_unverified',result['blocking_reasons'])
