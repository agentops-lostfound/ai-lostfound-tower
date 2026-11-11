"""로컬 탑뷰 검증 화면. python -m vision.topview_bridge.server --config ..."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .adapters import anchors, check_calibration, frames, get_json, now, storage_snapshot
from .detector import detect
from .reconcile import compare, layout_digest, layout_rows, validate_regions


class Bridge:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.config = validate_regions(json.loads(self.config_path.read_text(encoding="utf8")))
        self.out = self.config_path.parent
        self.lock = threading.RLock()
        self.analyze_lock = threading.Lock()
        self.stop = threading.Event()
        self.jpeg = self.frame = None
        self.frame_at = None
        self.frame_tick = 0
        self.camera_error = "카메라 연결 중"
        self.db_error = "DB 연결 중"
        self.snapshot = None
        self.result = None
        self.analysis_error = None
        self.analyzing = False
        self.stage = "준비 중"
        self.auto = False
        self.last_analysis = 0
        self.previous_counts = {}
        self.current_busy = True
        self.change_epoch = 0
        self.calibration_frames = {}
        for target in (self.camera_loop, self.db_loop, self.auto_loop):
            threading.Thread(target=target, daemon=True).start()

    def camera_loop(self):
        while not self.stop.is_set():
            try:
                for jpeg, frame, at, tick in frames(self.config, self.stop):
                    with self.lock:
                        self.jpeg, self.frame, self.frame_at, self.frame_tick = jpeg, frame, at, tick
                        self.camera_error = None
            except Exception as exc:
                with self.lock:
                    self.camera_error = f"카메라: {type(exc).__name__}: {exc}"
                self.stop.wait(2)

    def read_db(self):
        return storage_snapshot(self.config["tower_url"], os.environ.get("TOPVIEW_TOWER_TOKEN"))

    def busy(self):
        state = get_json(self.config["tower_url"].rstrip("/") + "/api/admin/live/state?detail=1",
                         token=os.environ.get("TOPVIEW_TOWER_TOKEN"))
        control = state.get("robot_control", {})
        # Unknown API shapes must not be mistaken for an idle robot.
        if "busy" not in state:
            raise ValueError("관제탑 응답에 busy 상태 없음")
        return bool(state["busy"] or control.get("active_job"))

    def db_loop(self):
        while not self.stop.is_set():
            try:
                snapshot = self.read_db()
                busy = self.busy()
                with self.lock:
                    if busy or (self.snapshot and layout_digest(snapshot) != layout_digest(self.snapshot)):
                        self.change_epoch += 1
                    self.snapshot, self.db_error, self.current_busy = snapshot, None, busy
            except Exception as exc:
                with self.lock:
                    self.db_error = f"DB: {type(exc).__name__}: {exc}"
                    self.current_busy = True
            self.stop.wait(3)

    def auto_loop(self):
        while not self.stop.wait(1):
            if self.auto and time.monotonic() - self.last_analysis > self.config.get("interval_seconds", 15):
                self.start_analysis()

    def start_analysis(self):
        if not self.analyze_lock.acquire(blocking=False):
            return False
        with self.lock:
            self.analyzing = True
            self.analysis_error = None
            self.stage = "DB 기준 조회"
        threading.Thread(target=self.analyze, daemon=True).start()
        return True

    def analyze(self):
        before = after = None
        db_reason = None
        try:
            with self.lock:
                start_epoch = self.change_epoch
            try:
                before = self.read_db()
                busy_before = self.busy()
            except Exception as exc:
                db_reason = f"DB 연결/상태 조회 실패: {type(exc).__name__}: {exc}"
                busy_before = True
            with self.lock:
                if self.frame is None or self.camera_error or time.monotonic()-self.frame_tick > 3:
                    raise RuntimeError(self.camera_error or "최신 탑뷰 프레임 없음")
                jpeg, frame = self.jpeg, self.frame.copy()
                captured_at, frame_tick = self.frame_at, self.frame_tick
                config = copy.deepcopy(self.config)
            calibration_error = check_calibration(frame, config, config["camera_id"])
            if calibration_error:
                raise RuntimeError(calibration_error)
            frame_id = hashlib.sha256(jpeg).hexdigest()[:20]
            self.stage = "OWLv2 · SigLIP2 분석 중"
            observation = detect(jpeg, config, self.out / "detector.stderr.log")
            observation.update(frame_id=frame_id, captured_at=captured_at, source="studio:topview")
            self.stage = "분석 후 DB 재조회"
            try:
                after = self.read_db()
                busy_after = self.busy()
            except Exception as exc:
                db_reason = f"분석 후 DB 조회 실패: {type(exc).__name__}: {exc}"
                busy_after = True
            elapsed = time.monotonic()-frame_tick
            if elapsed > config.get("max_result_age_seconds", 90):
                db_reason = "분석 프레임이 오래됨 — 재검증 필요"
            with self.lock:
                if self.camera_error or time.monotonic()-self.frame_tick > 3:
                    db_reason = "분석 중 카메라 연결 끊김"
                elif check_calibration(self.frame, config, config["camera_id"]):
                    db_reason = "분석 중 카메라/보관판 이동"
                if self.config != config:
                    db_reason = "분석 중 영역 변경"
                if self.change_epoch != start_epoch:
                    db_reason = "분석 중 DB 변경/로봇 동작 감지 — 재검증 필요"
            comparison = compare(observation, before, after, config, unavailable=db_reason,
                                 busy=busy_before or busy_after)
            digest = layout_digest(after) if after else None
            new_counts = {}
            if time.monotonic()-self.last_analysis > config.get("max_result_age_seconds", 90):
                self.previous_counts = {}
            for row in comparison["slots"]:
                signature = (row["state"], row["detected_count"], digest)
                previous = self.previous_counts.get(row["slot_id"])
                count = previous[1]+1 if previous and previous[0] == signature else 1
                row["consecutive_observations"] = count
                row["persistent_candidate"] = count >= 3 and row["state"] in {
                    "missing_candidate", "unexpected_candidate", "category_mismatch", "multiple"}
                new_counts[row["slot_id"]] = (signature, count)
            result = {"analyzed_at": now(), "calibration_version": config.get("calibration_version"),
                      "observation": observation, "comparison": comparison,
                      "db_before": before, "db_after": after, "elapsed_seconds": round(elapsed, 2)}
            (self.out / "analysis.jpg").write_bytes(jpeg)
            temp = self.out / "latest.tmp"
            temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
            temp.replace(self.out / "latest.json")
            with self.lock:
                self.result = result
                self.previous_counts = new_counts
                if after:
                    self.snapshot = after
                self.stage = "분석 완료"
        except Exception as exc:
            with self.lock:
                self.previous_counts = {}
                self.analysis_error = f"{type(exc).__name__}: {exc}"
                self.stage = "분석 실패 — 오류 확인"
        finally:
            with self.lock:
                self.analyzing = False
                self.last_analysis = time.monotonic()
            self.analyze_lock.release()

    def state(self):
        with self.lock:
            result = copy.deepcopy(self.result)
            stale = result and (time.time() - datetime.fromisoformat(result["observation"]["captured_at"]).timestamp()
                                > self.config.get("max_result_age_seconds", 90))
            db_changed = result and self.snapshot and result["db_after"] and layout_digest(self.snapshot) != layout_digest(result["db_after"])
            camera_error = self.camera_error or ("카메라 프레임 수신 지연" if time.monotonic()-self.frame_tick > 3 else None)
            invalid = self.db_error or camera_error or ("새 DB 배정 — 재검증 필요" if db_changed else None)
            invalid = invalid or ("관제탑 로봇 동작 중" if self.current_busy else None)
            invalid = invalid or ("결과 만료 — 재검증 필요" if stale else None)
            if result and self.analysis_error:
                invalid = "새 분석 실패 — 이전 결과 표시"
            if result and invalid:
                for row in result["comparison"]["slots"]:
                    row.update(state="unavailable", detail=invalid, persistent_candidate=False)
            return {"camera": {"error": camera_error, "captured_at": self.frame_at,
                               "age_seconds": round(time.monotonic()-self.frame_tick, 1) if self.frame_tick else None},
                    "db": {"error": self.db_error, "received_at": self.snapshot.get("received_at") if self.snapshot else None,
                           "source": self.config["tower_url"] + "/api/admin/storage",
                           "slots": layout_rows(self.snapshot) if self.snapshot else {}, "busy": self.current_busy},
                    "analyzing": self.analyzing, "stage": self.stage, "error": self.analysis_error,
                    "auto": self.auto, "result": result, "config": self.config}

    def calibration_snapshot(self):
        with self.lock:
            if self.frame is None or self.camera_error or time.monotonic()-self.frame_tick > 3:
                raise ValueError("최신 카메라 프레임 없음")
            reference = anchors(self.frame)
            if not reference:
                raise ValueError("최소 1개 기준 마커가 보여야 합니다.")
            key = hashlib.sha256(self.jpeg).hexdigest()
            self.calibration_frames = {k: v for k, v in self.calibration_frames.items() if time.monotonic()-v[0] < 300}
            self.calibration_frames[key] = (time.monotonic(), reference, [self.frame.shape[1], self.frame.shape[0]])
            return {"reference_id": key, "jpeg": base64.b64encode(self.jpeg).decode(), "captured_at": self.frame_at}

    def save_regions(self, regions, reference_id):
        with self.lock:
            if self.analyzing:
                raise ValueError("분석이 끝난 후 영역을 저장하세요.")
            if self.frame is None or self.camera_error or time.monotonic()-self.frame_tick > 3:
                raise ValueError("최신 카메라 프레임 없음")
            frozen = self.calibration_frames.get(reference_id)
            if frozen is None or time.monotonic()-frozen[0] > 300:
                raise ValueError("영역 편집 사진이 만료됨 — 편집을 다시 시작하세요.")
            config = copy.deepcopy(self.config)
            config.update(regions=regions, anchors=frozen[1], calibration_version=now(), image_size_px=frozen[2])
            validate_regions(config)
            error = check_calibration(self.frame, config, config["camera_id"])
            if error:
                raise ValueError(error)
            self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf8")
            self.config = config
            self.result = None
            self.previous_counts = {}


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, value, content_type="application/json; charset=utf-8", status=200):
            raw = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, dict) else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if not self.valid_host():
                return self.send({"error": "로컬 호스트만 허용"}, status=403)
            path = self.path.split("?")[0]
            if path == "/":
                self.send(Path(__file__).with_name("dashboard.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self.send(bridge.state())
            elif path == "/api/calibration":
                try:
                    self.send(bridge.calibration_snapshot())
                except ValueError as exc:
                    self.send({"error": str(exc)}, status=409)
            elif path == "/api/frame":
                with bridge.lock:
                    raw = bridge.jpeg
                self.send(raw or b"", "image/jpeg", 200 if raw else 503)
            elif path == "/api/analysis-frame":
                path = bridge.out / "analysis.jpg"
                self.send(path.read_bytes() if path.exists() else b"", "image/jpeg", 200 if path.exists() else 404)
            else:
                self.send({"error": "not found"}, status=404)

        def do_POST(self):
            # Same-origin only: prevent another website from starting GPU jobs or changing ROIs.
            expected = f"http://{self.headers.get('Host')}"
            if not self.valid_host() or self.headers.get("Origin") != expected or self.headers.get("X-Topview-Request") != "1":
                return self.send({"error": "동일 출처 요청만 허용"}, status=403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 32_768:
                    raise ValueError("잘못된 요청 크기")
                payload = json.loads(self.rfile.read(length))
                if self.path == "/api/analyze":
                    self.send({"started": bridge.start_analysis()})
                elif self.path == "/api/auto":
                    if not isinstance(payload.get("enabled"), bool):
                        raise ValueError("enabled는 boolean이어야 합니다.")
                    bridge.auto = payload["enabled"]
                    self.send({"enabled": bridge.auto})
                elif self.path == "/api/regions":
                    bridge.save_regions(payload["regions"], payload["reference_id"])
                    self.send({"saved": True})
                else:
                    self.send({"error": "not found"}, status=404)
            except (ValueError, KeyError, TypeError) as exc:
                self.send({"error": str(exc)}, status=400)

        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    bridge = Bridge(args.config)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(bridge))
    print(f"탑뷰 검증: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        bridge.stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
