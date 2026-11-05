"""Home 후보 읽기·미리보기·저장. 모터 제어는 제공하지 않는다."""
import threading
import uuid


class HomeSettingsController:
    def __init__(self, capture_pose, save_pose, status_worker, profile_loader, action_lock):
        self.capture_pose = capture_pose
        self.save_pose = save_pose
        self.status_worker = status_worker
        self.profile_loader = profile_loader
        self.action_lock = action_lock
        self.lock = threading.Lock()
        self.thread = None
        self.candidate = None
        self.current = {"state": "idle", "message": "현재 자세를 읽은 뒤 미리보고 저장하세요."}

    @staticmethod
    def validate_request(session, epoch, confirmed):
        if confirmed is not True or not isinstance(session, str) or not session or type(epoch) is not int:
            raise ValueError("현재 소유자 상태와 사용자 확인이 필요합니다")

    def capture(self, session, epoch, *, staff_confirmed=False):
        self.validate_request(session, epoch, staff_confirmed)
        if not self.action_lock.acquire(blocking=False):
            raise RuntimeError("Home 이동 또는 설정 작업이 진행 중입니다")
        try:
            with self.lock:
                self.candidate = None
                self.current = {"state": "reading", "message": "정지 상태에서 현재 자세를 읽는 중…"}
                self.thread = threading.Thread(target=self._capture, args=(session, epoch), daemon=True)
                self.thread.start()
                return dict(self.current)
        except Exception:
            self.action_lock.release()
            raise

    def _capture(self, session, epoch):
        try:
            candidate = self.capture_pose(session, epoch)
            if (candidate.get("owner_session") != session or candidate.get("epoch") != epoch
                    or candidate.get("movement_commands_sent") != 0):
                raise RuntimeError("기록한 자세의 소유자 또는 명령 세대가 다릅니다")
            positions = candidate.get("positions")
            if not isinstance(positions, list) or len(positions) != 6:
                raise RuntimeError("6개 관절 위치가 필요합니다")
            with self.lock:
                self.candidate = {**candidate, "candidate_id": uuid.uuid4().hex}
                self.current = {"state": "preview", "message": "기록한 자세를 확인하고 Home으로 저장하세요.",
                                "positions": positions, "session": session, "epoch": epoch,
                                "candidate_id": self.candidate["candidate_id"]}
        except Exception as error:
            with self.lock:
                self.current = {"state": "error", "message": str(error)}
                self.candidate = None
        finally:
            self.action_lock.release()

    def save(self, candidate_id, session, epoch, *, name, staff_confirmed=False):
        self.validate_request(session, epoch, staff_confirmed)
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Home 이름은 1~100자로 입력하세요")
        if not self.action_lock.acquire(blocking=False):
            raise RuntimeError("Home 이동 또는 설정 작업이 진행 중입니다")
        try:
            with self.lock:
                candidate = self.candidate
                if (candidate is None or candidate.get("candidate_id") != candidate_id
                        or candidate.get("owner_session") != session or candidate.get("epoch") != epoch):
                    raise RuntimeError("현재 자세를 다시 읽어주세요. 기록 상태가 바뀌었습니다")
                current = self.status_worker.request("status")
                if (not current.get("ok") or current.get("session") != session or current.get("epoch") != epoch
                        or not current.get("stop_requested") or not current.get("hold_commanded")):
                    raise RuntimeError("정지 상태가 바뀌었습니다. 자세를 다시 읽어주세요")
                result = self.save_pose(candidate, name.strip())
                if result.get("movement_commands_sent") != 0:
                    raise RuntimeError("Home 저장 결과가 올바르지 않습니다")
                self.candidate = None
                self.current = {"state": "saved", "message": "Home 저장 완료 · 로봇 이동 없음",
                                "saved_name": result["name"], "saved_revision": result["revision"],
                                "movement_commands_sent": 0}
                return dict(self.current)
        finally:
            self.action_lock.release()

    def status(self):
        with self.lock:
            current = dict(self.current)
        try:
            profile = self.profile_loader()
            current["configured"] = {key: profile[key] for key in ("name", "revision", "positions")}
        except Exception as error:
            current.update(state="error", message="Home 설정 확인 실패: " + str(error))
        return current

    def close(self):
        thread = self.thread
        if thread is not None:
            thread.join(15)
