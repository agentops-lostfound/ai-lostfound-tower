import ast
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from . import robot_link


class RobotLinkTests(unittest.TestCase):
    def test_probe_has_only_read_servo_calls(self):
        tree=ast.parse(Path(__file__).with_name('robot_probe.py').read_text(encoding='utf-8'))
        calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='packet']
        self.assertEqual(set(calls),{'read1ByteTxRx','read2ByteTxRx'})

    @patch.object(robot_link.subprocess,'run')
    @patch.object(robot_link.requests,'get')
    def test_running_session_blocks_direct_serial(self,get,run):
        def response(value):
            r=Mock();r.json.return_value=value;return r
        get.side_effect=[response([{'id':robot_link.PROJECT,'name':'test'}]),response([{'id':'f','type':'SO101_Follower','payload':{'serial_number':robot_link.SERIAL}}]),response([{'name':'active'}])]
        with self.assertRaises(ValueError):robot_link.status(True)
        run.assert_not_called()
