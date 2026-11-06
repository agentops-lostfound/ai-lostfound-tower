"""비전 파이프라인 시험 (표준 라이브러리 unittest, GPU·웹캠 없이 실행).

실행: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import cv2  # noqa: E402
    import numpy as np  # noqa: E402
except ImportError as e:  # 비전 패키지가 없는 PC: 오류 대신 '건너뜀'으로 표시
    raise unittest.SkipTest(f"비전 시험 건너뜀: {e.name} 없음 → .venv 에서 pip install -r vision/requirements.txt") from e

from tools import hub_sync, notify as notify_mod  # noqa: E402
from tools.envfile import load_env  # noqa: E402
from vision import capture_images, prepare_dataset, train_yolo  # noqa: E402
from vision.config import make_filename, parse_filename  # noqa: E402


def make_video(path: Path, frames: int = 20, size=(320, 240)) -> None:
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, size)
    rng = np.random.default_rng(0)
    for _ in range(frames):
        vw.write(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    vw.release()


class TestConfig(unittest.TestCase):
    def test_make_and_parse(self):
        name = make_filename("card_wallet", "W01", "s1", 7)
        self.assertEqual(name, "card_wallet_W01_s1_007.jpg")
        self.assertEqual(parse_filename(name), {"category": "card_wallet", "object_id": "W01", "session": "s1", "index": 7})

    def test_six_classes_fixed(self):
        """11/6 6종 고정: 0~3번은 예전 4종 순서, 4·5번이 새 품목. 한국어는 contracts 와 같음"""
        from agents.contracts import CATEGORIES
        from vision.config import CLASS_KO, CLASSES
        self.assertEqual(CLASSES, ["card_wallet", "usb", "lip_balm", "phone", "hand_cream", "power_bank"])
        self.assertEqual(set(CLASS_KO.values()), set(CATEGORIES) - {"없음"})
        six = (ROOT / "vision/configs/data_six_class.example.yaml").read_text(encoding="utf-8")
        for i, n in enumerate(CLASSES):
            self.assertIn(f"  {i}: {n}\n", six)

    def test_underscore_names_round_trip(self):
        for cat, obj in [("lip_balm", "L01"), ("hand_cream", "H02"), ("power_bank", "B01"), ("phone", "P01")]:
            name = make_filename(cat, obj, "s3", 12)
            self.assertEqual(parse_filename(name), {"category": cat, "object_id": obj, "session": "s3", "index": 12})

    def test_legacy_names_still_read(self):
        """이미 찍은 예전 이름 사진은 새 이름으로 읽는다(새로 찍을 때는 예전 이름 불가)"""
        self.assertEqual(parse_filename("wallet_W01_s1_001.jpg")["category"], "card_wallet")
        self.assertEqual(parse_filename("lipbalm_L01_s2_010.jpg")["category"], "lip_balm")
        with self.assertRaises(ValueError):
            make_filename("wallet", "W01", "s1", 0)

    def test_index_over_999(self):
        self.assertEqual(make_filename("usb", "U02", "s2", 1234), "usb_U02_s2_1234.jpg")

    def test_invalid_names(self):
        for args in [("bag", "W01", "s1"), ("card_wallet", "w01", "s1"), ("card_wallet", "W1", "s1"), ("card_wallet", "W01", "1")]:
            with self.assertRaises(ValueError):
                make_filename(*args, 0)
        with self.assertRaises(ValueError):
            make_filename("card_wallet", "W01", "s1", -1)

    def test_parse_rejects_unknown(self):
        self.assertIsNone(parse_filename("bag_W01_s1_001.jpg"))
        self.assertIsNone(parse_filename("card_wallet_W01_s1_001.png"))
        self.assertIsNone(parse_filename("lip_W01_s1_001.jpg"))          # 6종이 아닌 이름
        self.assertIsNone(parse_filename("card__wallet_W01_s1_001.jpg"))  # 밑줄 두 개


class TestCapture(unittest.TestCase):
    def test_blur_score_orders(self):
        rng = np.random.default_rng(1)
        sharp = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
        blurry = cv2.GaussianBlur(sharp, (21, 21), 0)
        self.assertGreater(capture_images.blur_score(sharp), capture_images.blur_score(blurry))

    def test_recorder_numbering_and_csv(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            frame = np.zeros((48, 64, 3), np.uint8)
            rec = capture_images.Recorder(out, "lip_balm", "L01", "s1")
            p1, p2 = rec.save(frame), rec.save(frame)
            self.assertEqual([p1.name, p2.name], ["lip_balm_L01_s1_000.jpg", "lip_balm_L01_s1_001.jpg"])
            # 새로 시작해도 이어서 번호를 매기고 덮어쓰지 않는다
            rec2 = capture_images.Recorder(out, "lip_balm", "L01", "s1")
            self.assertEqual(rec2.save(frame).name, "lip_balm_L01_s1_002.jpg")
            # 누군가 다음 번호를 먼저 만들어도 건너뛴다
            (out / "lip_balm_L01_s1_003.jpg").write_bytes(b"x")
            self.assertEqual(rec2.save(frame).name, "lip_balm_L01_s1_004.jpg")
            with (out / "captures.csv").open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["width"], "64")

    def test_recorder_continues_after_legacy_names(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "wallet_W01_s1_000.jpg").write_bytes(b"x")       # 예전 이름으로 찍은 사진
            (out / "wallet_W01_s1_001.jpg").write_bytes(b"x")
            (out / "card_wallet_W02_s1_005.jpg").write_bytes(b"x")  # 다른 물건 — 번호에 영향 없음
            rec = capture_images.Recorder(out, "card_wallet", "W01", "s1")
            self.assertEqual(rec.save(np.zeros((8, 8, 3), np.uint8)).name, "card_wallet_W01_s1_002.jpg")

    def test_headless_run_with_video(self):
        with tempfile.TemporaryDirectory() as d:
            vid = Path(d) / "v.avi"
            make_video(vid, frames=20)
            out = Path(d) / "raw"
            args = ["--category", "phone", "--object", "P01", "--session", "s2", "--out", str(out),
                    "--source", str(vid), "--no-preview", "--auto-every", "2", "--max", "5"]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(capture_images.main(args), 0)
            files = sorted(p.name for p in (out / "s2").glob("*.jpg"))
            self.assertEqual(files, [f"phone_P01_s2_{i:03d}.jpg" for i in range(5)])
            img = cv2.imread(str(out / "s2" / files[0]))
            self.assertEqual(img.shape[:2], (240, 320))  # 저장 사진에는 안내 글자 없이 원본 크기

    def test_video_shorter_than_max(self):
        with tempfile.TemporaryDirectory() as d:
            vid = Path(d) / "v.avi"
            make_video(vid, frames=3)
            args = ["--category", "usb", "--object", "U01", "--session", "s1", "--out", str(Path(d) / "raw"),
                    "--source", str(vid), "--no-preview", "--auto-every", "1", "--max", "10"]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(capture_images.main(args), 0)
            self.assertEqual(len(list((Path(d) / "raw" / "s1").glob("*.jpg"))), 3)

    def test_bad_inputs(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            capture_images.main(["--category", "card_wallet", "--object", "W1", "--session", "s1", "--no-preview"])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()):  # 없는 영상
                capture_images.main(["--category", "card_wallet", "--object", "W01", "--session", "s1", "--out", d,
                                     "--source", str(Path(d) / "없는영상.mp4"), "--no-preview", "--auto-every", "1", "--max", "1"])
            self.assertIn("열 수 없습니다", str(cm.exception))
            with self.assertRaises(SystemExit) as cm:  # 화면 없이 자동 저장도 없음 → 아무것도 못 함
                capture_images.main(["--category", "card_wallet", "--object", "W01", "--session", "s1", "--no-preview"])
            self.assertIn("--auto-every", str(cm.exception))
            with self.assertRaises(SystemExit) as cm:  # 화면 없이 카메라 + 장수 제한 없음 → 끝없이 저장
                capture_images.main(["--category", "card_wallet", "--object", "W01", "--session", "s1", "--no-preview", "--auto-every", "5"])
            self.assertIn("--max", str(cm.exception))


class TestPrepare(unittest.TestCase):
    def make_export(self, root: Path) -> Path:
        exp = root / "export"
        (exp / "images").mkdir(parents=True)
        (exp / "labels").mkdir()
        # Label Studio 순서가 우리와 다르다고 가정: usb=0, wallet=1, phone=2, lipbalm=3
        (exp / "classes.txt").write_text("usb\nwallet\nphone\nlipbalm\n", encoding="utf-8")
        items = [
            ("a1b2c3d4-wallet_W01_s1_000", "1 0.5 0.5 0.2 0.2"),   # wallet
            ("e5f6a7b8-usb_U01_s1_000", "0 0.4 0.4 0.1 0.1"),      # usb
            ("phone_P01_s2_000", "2 0.5 0.5 0.3 0.6"),             # phone, 접두어 없음
            ("99aa88bb-lipbalm_L01_s2_000", "3 0.5 0.5 0.1 0.2"),  # lipbalm
            ("wallet_W01_s2_001", None),                           # 라벨 없음 → 빈 배경
        ]
        for stem, label in items:
            cv2.imwrite(str(exp / "images" / f"{stem}.jpg"), np.zeros((20, 20, 3), np.uint8))
            if label is not None:
                (exp / "labels" / f"{stem}.txt").write_text(label + "\n", encoding="utf-8")
        cv2.imwrite(str(exp / "images" / "random_photo.jpg"), np.zeros((20, 20, 3), np.uint8))
        return exp

    def test_split_and_remap(self):
        with tempfile.TemporaryDirectory() as d:
            exp = self.make_export(Path(d))
            out = Path(d) / "ds"
            r = prepare_dataset.prepare(exp, out, {"s2"})
            self.assertEqual(r["images"], {"train": 2, "val": 3})
            self.assertEqual(r["skipped"], ["random_photo.jpg"])
            # 접두어가 떼어지고, 예전 이름(wallet·lipbalm) classes.txt 도 새 순서(card_wallet0 usb1 lip_balm2 phone3)로 바뀐다
            self.assertEqual((out / "labels/train/wallet_W01_s1_000.txt").read_text().split()[0], "0")
            self.assertEqual((out / "labels/train/usb_U01_s1_000.txt").read_text().split()[0], "1")
            self.assertEqual((out / "labels/val/lipbalm_L01_s2_000.txt").read_text().split()[0], "2")
            self.assertEqual((out / "labels/val/phone_P01_s2_000.txt").read_text().split()[0], "3")
            self.assertEqual((out / "labels/val/wallet_W01_s2_001.txt").read_text(), "")
            self.assertIn("  3: phone", (out / "data.yaml").read_text())
            self.assertIn("  5: power_bank", (out / "data.yaml").read_text())

    def test_errors(self):
        with tempfile.TemporaryDirectory() as d:
            exp = self.make_export(Path(d))
            with self.assertRaises(SystemExit):  # 검증 세션이 없음 → val 0장
                prepare_dataset.prepare(exp, Path(d) / "a", {"s9"})
            self.assertFalse((Path(d) / "a").exists())  # 오류면 반쯤 만든 폴더를 남기지 않음
            out = Path(d) / "b"
            out.mkdir()
            (out / "x").write_text("x")
            with self.assertRaises(SystemExit):  # 덮어쓰기 방지
                prepare_dataset.prepare(exp, out, {"s2"})
            (exp / "labels" / "phone_P01_s2_000.txt").write_text("2 0.5 0.5 1.7 0.6\n")
            with self.assertRaises(ValueError):  # 좌표 범위 오류
                prepare_dataset.prepare(exp, Path(d) / "c", {"s2"})
            self.assertFalse((Path(d) / "c").exists())
            (exp / "classes.txt").write_text("usb\nbag\n")
            with self.assertRaises(SystemExit):  # 모르는 품목 이름
                prepare_dataset.prepare(exp, Path(d) / "e", {"s2"})


class TestNotify(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop("DISCORD_WEBHOOK_URL", None)

    def tearDown(self):
        os.environ.pop("DISCORD_WEBHOOK_URL", None)
        if self._env is not None:
            os.environ["DISCORD_WEBHOOK_URL"] = self._env

    def test_payload(self):
        p = notify_mod.build_payload("제목", "가" * 5000)
        self.assertEqual(p["embeds"][0]["title"], "제목")
        self.assertEqual(len(p["embeds"][0]["description"]), 4096)
        self.assertEqual(p["allowed_mentions"], {"parse": []})

    def test_missing_or_bad_url(self):
        with mock.patch.object(notify_mod, "load_env", lambda: {}), redirect_stderr(io.StringIO()) as err:
            self.assertFalse(notify_mod.notify("t", "b"))
            os.environ["DISCORD_WEBHOOK_URL"] = "https://example.com/hook"
            self.assertFalse(notify_mod.notify("t", "b"))
            os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/1/abc"
            self.assertFalse(notify_mod.notify("", " "))
        self.assertNotIn("abc", err.getvalue())  # 주소가 출력되지 않음

    def test_success_and_http_error(self):
        os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/1/secret"
        sent = {}

        class Resp:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout):
            sent["body"] = json.loads(req.data.decode("utf-8"))
            sent["ct"] = req.headers["Content-type"]
            return Resp()

        with mock.patch.object(notify_mod, "load_env", lambda: {}), mock.patch("urllib.request.urlopen", fake_open):
            self.assertTrue(notify_mod.notify("📥 접수", "물건 #A-0001"))
        self.assertEqual(sent["body"]["embeds"][0]["title"], "📥 접수")
        self.assertIn("utf-8", sent["ct"])

        import urllib.error

        def fail_open(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        with mock.patch.object(notify_mod, "load_env", lambda: {}), mock.patch("urllib.request.urlopen", fail_open), \
                redirect_stderr(io.StringIO()) as err:
            self.assertFalse(notify_mod.notify("t", "b"))
        self.assertIn("401", err.getvalue())
        self.assertNotIn("secret", err.getvalue())


class TestEnvAndHub(unittest.TestCase):
    def test_load_env_bom_and_no_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_bytes("﻿ALF_A=1\n# 주석\nALF_B=\"two\"\nBROKEN\n".encode("utf-8"))
            os.environ["ALF_B"] = "keep"
            try:
                got = load_env(p)
                self.assertEqual(got["ALF_A"], "1")
                self.assertEqual(os.environ["ALF_A"], "1")
                self.assertEqual(os.environ["ALF_B"], "keep")  # 이미 있는 값은 덮어쓰지 않음
            finally:
                for k in ("ALF_A", "ALF_B"):
                    os.environ.pop(k, None)

    def test_hub_checks_and_dry_run(self):
        with mock.patch.dict(os.environ, {"HF_DATA_REPO": "", "HF_MODEL_REPO": "org/models"}):
            with self.assertRaises(SystemExit):
                hub_sync.resolve_repo("data")
            with self.assertRaises(SystemExit):
                hub_sync.check_path("../x")
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "a.txt").write_text("hi")
                with redirect_stdout(io.StringIO()) as out:
                    hub_sync.upload("model", Path(d), "v1", dry_run=True)
                    hub_sync.download("model", "v1", Path(d) / "dl", dry_run=True)
                self.assertIn("model:org/models/v1 (1개", out.getvalue())
                self.assertFalse((Path(d) / "dl").exists())


class TestTrainPipeline(unittest.TestCase):
    """ultralytics 대신 가짜 모듈로 파이프라인 흐름(학습→검증→내보내기→기록→알림)을 시험."""

    def make_dataset(self, root: Path) -> None:
        ds = root / "datasets" / "vtest"
        for s in ("train", "val"):
            (ds / "images" / s).mkdir(parents=True)
            cv2.imwrite(str(ds / "images" / s / "wallet_W01_s1_000.jpg"), np.zeros((8, 8, 3), np.uint8))
        (ds / "data.yaml").write_text("path: .\ntrain: images/train\nval: images/val\nnames:\n  0: wallet\n", encoding="utf-8")

    def fake_ultralytics(self, root: Path, fail: bool = False):
        class Box:
            map50, map = 0.9, 0.7
            maps = [0.8, 0.7, 0.6, 0.5]

        class FakeYOLO:
            def __init__(self, w):
                self.w = w
                self.trainer = types.SimpleNamespace(best=str(root / "runs" / "best.pt"))

            def train(self, **kw):
                if fail:
                    raise RuntimeError("CUDA out of memory")
                FakeYOLO.data = kw["data"]
                (root / "runs").mkdir(exist_ok=True)
                (root / "runs" / "best.pt").write_bytes(b"pt")

            def val(self, **kw):
                return types.SimpleNamespace(box=Box())

            def export(self, format, imgsz):
                if format == "onnx":
                    p = root / "runs" / "best.onnx"
                    p.write_bytes(b"onnx")
                else:
                    p = root / "runs" / "best_openvino_model"
                    p.mkdir(exist_ok=True)
                    (p / "best.xml").write_text("<xml/>")
                return str(p)

        return types.SimpleNamespace(YOLO=FakeYOLO), FakeYOLO

    def run_main(self, root: Path, fail=False, extra=()):
        mod, cls = self.fake_ultralytics(root, fail)
        calls = []
        cwd = os.getcwd()
        os.chdir(root)
        try:
            with mock.patch.dict(sys.modules, {"ultralytics": mod}), \
                    mock.patch.object(train_yolo, "notify", lambda t, b: calls.append((t, b)) or True), \
                    mock.patch.object(train_yolo, "load_env", lambda: {}), redirect_stdout(io.StringIO()):
                try:
                    code = train_yolo.main(["--dataset", "vtest", "--name", "t1", "--epochs", "1", *extra])
                except RuntimeError:
                    code = "error"
        finally:
            os.chdir(cwd)
        return code, calls, cls

    def test_success_flow(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make_dataset(root)
            code, calls, cls = self.run_main(root)
            self.assertEqual(code, 0)
            out = root / "models" / "t1"
            for f in ("best.pt", "best.onnx", "best_openvino_model/best.xml", "metrics.json", "data.yaml"):
                self.assertTrue((out / f).exists(), f)
            m = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(m["mAP50-95"], 0.7)
            self.assertEqual(m["mAP50-95_per_class"]["phone"], 0.5)
            self.assertEqual(m["images"], {"train": 1, "val": 1})
            first = (out / "data.yaml").read_text().splitlines()[0]
            self.assertRegex(first, r"^path: ([A-Za-z]:)?/", first)  # 절대 경로로 바뀜(리눅스 /… · Windows C:/…)
            self.assertEqual([c[0] for c in calls], ["🏋️ 학습 시작", "✅ 학습 완료"])
            self.assertIn("mAP50-95 0.700", calls[1][1])

    def test_failure_notifies(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make_dataset(root)
            code, calls, _ = self.run_main(root, fail=True)
            self.assertEqual(code, "error")
            self.assertEqual(calls[-1][0], "❌ 학습 실패")
            self.assertIn("CUDA out of memory", calls[-1][1])

    def test_missing_dataset_and_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mod, _ = self.fake_ultralytics(root)
            calls = []
            cwd = os.getcwd()
            os.chdir(root)
            try:
                with mock.patch.dict(sys.modules, {"ultralytics": mod}), \
                        mock.patch.object(train_yolo, "notify", lambda t, b: calls.append(t) or True), \
                        mock.patch.object(train_yolo, "load_env", lambda: {}), redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(train_yolo.main(["--dataset", "none", "--name", "x", "--dry-run"]), 0)
                    with self.assertRaises(SystemExit):
                        train_yolo.main(["--dataset", "none", "--name", "x"])
            finally:
                os.chdir(cwd)
            self.assertIn("[계획]", out.getvalue())
            self.assertEqual(calls, ["🏋️ 학습 시작", "❌ 학습 중단"])


if __name__ == "__main__":
    unittest.main()
