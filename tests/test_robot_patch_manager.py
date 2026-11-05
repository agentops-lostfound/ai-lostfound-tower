"""설치 디렉터리 대신 임시 파일로 패치 적용/복원 실패 경로 시험."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import manage_robot_owner_patch as manager


class PatchManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.transport = root / "transport"
        self.transport.mkdir()
        self.candidate = root / "candidate"
        self.candidate.mkdir()
        self.backup = root / "backup"
        self.original = b"# own test fixture\nvalue = 1\n"
        self.original_hash = hashlib.sha256(self.original).hexdigest()
        self.source_patch = patch.object(manager, "EXPECTED_SOURCE", self.original_hash)
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.idle_patch = patch.object(manager, "require_idle")
        self.idle = self.idle_patch.start()
        self.addCleanup(self.idle_patch.stop)
        (self.transport / manager.FILES[0]).write_bytes(self.original)
        data = {name: f"value = {i+2}\n".encode() for i, name in enumerate(manager.FILES)}
        for name, content in data.items():
            (self.candidate / name).write_bytes(content)
        (self.candidate / "manifest.json").write_text(json.dumps({
            "status": "PREPARED_NOT_INSTALLED", "source_sha256": self.original_hash,
            "files": {name: manager.digest(content) for name, content in data.items()},
        }))

    def make_backup(self):
        return manager.backup(self.candidate, self.transport, self.backup)

    def test_check_and_backup_do_not_modify_installation(self):
        self.assertEqual(manager.check(self.candidate, self.transport)[2], "READY_NOT_INSTALLED")
        self.make_backup()
        self.assertEqual((self.transport / manager.FILES[0]).read_bytes(), self.original)
        self.assertEqual((self.backup / "original_owner.py").read_bytes(), self.original)
        self.assertEqual(sorted(p.name for p in self.transport.iterdir()), [manager.FILES[0]])

    def test_apply_then_rollback_restores_exact_original(self):
        self.make_backup()
        manager.apply(self.backup, self.transport)
        self.assertEqual(manager.check(self.candidate, self.transport)[2], "ALREADY_INSTALLED")
        manager.rollback(self.backup, self.transport)
        self.assertEqual((self.transport / manager.FILES[0]).read_bytes(), self.original)
        self.assertTrue(all(not (self.transport / n).exists() for n in manager.FILES[1:]))
        manager.rollback(self.backup, self.transport)  # 반복 복원도 동일한 결과

    def test_unknown_original_or_candidate_is_preserved(self):
        (self.transport / manager.FILES[0]).write_bytes(b"unknown = True\n")
        with self.assertRaises(RuntimeError):
            self.make_backup()
        self.assertFalse(self.backup.exists())
        (self.transport / manager.FILES[0]).write_bytes(self.original)
        (self.candidate / manager.FILES[1]).write_bytes(b"tampered = True\n")
        with self.assertRaises(RuntimeError):
            self.make_backup()
        self.assertFalse(self.backup.exists())

    def test_tampered_installed_file_blocks_rollback(self):
        self.make_backup()
        manager.apply(self.backup, self.transport)
        file = self.transport / manager.FILES[1]
        file.write_bytes(b"external_change = True\n")
        with self.assertRaises(RuntimeError):
            manager.rollback(self.backup, self.transport)
        self.assertEqual(file.read_bytes(), b"external_change = True\n")

    def test_partial_apply_failure_restores_original(self):
        self.make_backup()
        original_write = manager.atomic_write
        def fail_owner(path, content):
            if Path(path).name == manager.FILES[0] and content != self.original:
                raise OSError("simulated disk failure")
            original_write(path, content)
        with patch.object(manager, "atomic_write", side_effect=fail_owner):
            with self.assertRaises(OSError):
                manager.apply(self.backup, self.transport)
        self.assertEqual((self.transport / manager.FILES[0]).read_bytes(), self.original)
        self.assertTrue(all(not (self.transport / n).exists() for n in manager.FILES[1:]))

    def test_busy_owner_blocks_changes(self):
        self.idle.side_effect = RuntimeError("owner busy")
        with self.assertRaises(RuntimeError):
            self.make_backup()
        self.assertFalse(self.backup.exists())


    def test_manual_pose_guard_blocks_original_rollback(self):
        self.make_backup()
        manager.apply(self.backup, self.transport)
        before = (self.transport / manager.FILES[0]).read_bytes()
        guard = Path(self.temp.name) / "manual.json"
        guard.write_text("{}")
        with patch.object(manager, "MANUAL_GUARD_FILE", guard):
            with self.assertRaisesRegex(RuntimeError, "수동 자세 변경"):
                manager.rollback(self.backup, self.transport)
        self.assertEqual((self.transport / manager.FILES[0]).read_bytes(), before)
