"""관제탑 서비스 — LF-14 (docs/design/architecture.md).

한줄 설명: 화면(웹·직원 화면)이 보낸 반환 요청을 검사하고, 반환 흐름을 한 번에 하나씩 실행하고, 기록을 남긴다.

- HTTP(FastAPI)는 agents/api.py 가 이 서비스를 감싸기만 한다. 규칙은 모두 여기 있다(FastAPI 없이 시험 가능).
- 지키는 것
  - 같은 사례 번호로 두 번 실행하지 않는다(로봇이 두 번 움직이는 사고 방지) → "duplicate"
  - 로봇은 하나 → 반환 흐름은 동시에 하나만. 실행 중에 온 요청은 기다리지 않고 "busy"
  - 요청에는 개인정보를 받지 않는다: 사례 번호·접수 번호(영문·숫자·-·_ 32자 이하)와 관문 결과(참/거짓)만
- 2단계 연결(11/3): 웹은 create_claim(찾기 요청 + 웹 관문 3개 + 예약) → 방문 때 직원 화면은 start_return 에
  claim_id + 현장 관문 3개만 보낸다. 웹 관문은 저장된 값만 쓴다(직원이 다시 입력하지 않음)
"""
from __future__ import annotations

import re
import threading
from dataclasses import fields
from typing import Callable

from agents.claims import ClaimError, ClaimStore, MemoryClaimStore, parse_claim, public_view, web_gates
from agents.intake import (IntakeError, IntakeStore, MemoryIntakeStore, decode_photo, parse_features, parse_intake, receipt,
                           save_photo, valid_item_id)
from agents.contracts import (CLAIM_ID_RE, DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED,
                              DECISIONS, HANDOVER_DONE, HANDOVER_HOLD, HANDOVER_WAIT, HOLD_REASONS, STAFF_STOP_REASON)
from agents.records import MemoryRecorder, Recorder
from agents.supervisor import Outcome, ReturnRequest, run_return

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# 직원 정지 버튼을 누른 뒤 막을 로봇 동작(정지·원점 복귀는 막지 않음)
ROBOT_MOVES = ("robot_approach", "robot_grasp", "robot_verify_grasp", "robot_deliver")


class GuardedBackend:
    """반환 중 부품을 감싼다(11/4). 직원 화면 정지 버튼이 눌리면 그 뒤의 로봇 동작 요청은 부품에 보내지 않고 실패로 돌려준다.
    → 흐름은 약속대로 robot_stop + 정지(stopped) + 경보. 흐름 코드(supervisor·graph)는 바꾸지 않는다."""

    def __init__(self, backend, stop_event: threading.Event, lease_factory=None):
        self._be = backend
        self._stop = stop_event
        self._lease_factory = lease_factory    # user → GpuLease (agents/gpu_lease.py). None 이면 GPU 사용권을 쓰지 않음
        self._lease = None

    def gpu_acquire(self, user: str) -> tuple[bool, str]:
        """로봇(VLA)을 움직이기 전에 GPU 사용권을 받는다(11/4). (받음?, 못 받은 이유). 사용권 기능이 꺼져 있으면 (True, "")."""
        if self._lease_factory is None:
            return True, "꺼짐"
        if self._lease is not None:
            return True, ""
        from agents.gpu_lease import GpuBusy
        try:
            self._lease = self._lease_factory(user).acquire()
            return True, ""
        except GpuBusy as e:
            return False, str(e)
        except Exception as e:                  # 잠금 파일 오류 등 → 안전하게 못 받은 것으로
            return False, f"GPU 사용권 확인 실패({type(e).__name__})"

    def gpu_release(self) -> None:
        if self._lease is not None:
            self._lease.release()
            self._lease = None

    def __getattr__(self, name: str):
        attr = getattr(self._be, name)
        if name not in ROBOT_MOVES or not callable(attr):
            return attr

        def guarded(*a, **k):
            if self._stop.is_set():
                return {"ok": False, "reason": STAFF_STOP_REASON}
            return attr(*a, **k)
        return guarded
GATE_FIELDS = [f.name for f in fields(ReturnRequest) if f.name not in ("case_id", "item_id")]
ALLOWED = {"case_id", "item_id", *GATE_FIELDS}
VISIT_GATES = ["visitor_id_match", "inner_feature_ok", "staff_confirmed"]   # 본센터 방문 때 직원 화면이 채움
# 11/6 인계 교차 검증 3가지(키 → 화면 이름). docs/design/handover_cross_check.md
VERIFY_CHECKS = {"item_match": "물건 대조", "id_match": "신분증 대조", "feature_match": "비공개 특징"}
VISIT_ALLOWED = {"claim_id", "case_id", *VISIT_GATES}
KIOSK_RETURN_ALLOWED = {"machine_id", "claim_id", "id_no_masked"}   # 11/6 본센터 키오스크 회수: 관문 값은 화면이 못 보냄
KIOSK_RETURN_MACHINE = "CENTER"      # 회수는 본센터 키오스크만(11/5 결정)
KIOSK_MAX_FAILS = 3                  # 신분 번호를 이만큼 틀리면 그 찾기 번호는 키오스크에서 잠금(역무실 안내)


class RequestError(ValueError):
    """요청 형식 오류(HTTP 422)."""


class Unavailable(RuntimeError):
    """기록 저장소(DB)에 닿지 않아 안전하게 실행할 수 없음(HTTP 503). 중복 확인을 못 하면 로봇을 움직이지 않는다."""


class NotFound(LookupError):
    """없는 찾기 번호(HTTP 404)."""


class Conflict(RuntimeError):
    """중복 사례 번호 또는 다른 반환 진행 중(HTTP 409). kind: duplicate | busy | state(인계할 수 없는 상태)"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def parse_request(payload: object) -> ReturnRequest:
    """화면이 보낸 JSON → ReturnRequest. 모르는 칸·잘못된 값은 RequestError."""
    if not isinstance(payload, dict):
        raise RequestError("JSON 객체여야 합니다")
    unknown = sorted(set(payload) - ALLOWED)
    if unknown:
        raise RequestError(f"모르는 칸: {unknown} (개인정보는 보내지 않습니다)")
    for key in ("case_id", "item_id"):
        v = payload.get(key)
        if not isinstance(v, str) or not ID_RE.match(v):
            raise RequestError(f"{key}: 영문·숫자·-·_ 1~32자")
    gates = {}
    for key in GATE_FIELDS:
        if key not in payload:
            raise RequestError(f"{key}: 빠짐(관문 결과는 모두 보내야 합니다)")
        if not isinstance(payload[key], bool):
            raise RequestError(f"{key}: true/false 만")
        gates[key] = payload[key]
    return ReturnRequest(case_id=payload["case_id"], item_id=payload["item_id"], **gates)


def parse_visit(payload: dict) -> tuple[str, str | None, dict]:
    """직원 화면(2단계)의 요청 → (claim_id, case_id 또는 None, 현장 관문 3개)."""
    unknown = sorted(set(payload) - VISIT_ALLOWED)
    if unknown:
        raise RequestError(f"모르는 칸: {unknown} (방문 확인은 claim_id·case_id·현장 관문 3개만)")
    cid = payload.get("claim_id")
    if not isinstance(cid, str) or not CLAIM_ID_RE.match(cid):
        raise RequestError("claim_id: 찾기 번호 형식(예: C-20261103-0001)")
    case = payload.get("case_id")
    if case is not None and (not isinstance(case, str) or not ID_RE.match(case)):
        raise RequestError("case_id: 영문·숫자·-·_ 1~32자")
    gates = {}
    for key in VISIT_GATES:
        if not isinstance(payload.get(key), bool):
            raise RequestError(f"{key}: true/false 필요(직원 화면에서 확인)")
        gates[key] = payload[key]
    return cid, case, gates


class TowerService:
    def __init__(self, backend_factory: Callable[[], object], reporter, recorder: Recorder | None = None,
                 reviewer=None, flow: Callable = run_return, claims: ClaimStore | None = None,
                 intake: IntakeStore | None = None, gpu_lease=None, photo_dir=None, storage=None):
        self.backend_factory = backend_factory   # 요청마다 부품 묶음을 얻는 함수(진짜 부품이면 같은 객체를 돌려줘도 됨)
        self.reporter = reporter
        self.recorder = recorder if recorder is not None else MemoryRecorder()
        self.reviewer = reviewer
        self.flow = flow
        self.claims = claims if claims is not None else MemoryClaimStore()
        self.intake = intake if intake is not None else MemoryIntakeStore()
        self._run_lock = threading.Lock()
        self._stop_event = threading.Event()     # 직원 정지 버튼(반환을 새로 시작할 때 지움)
        self.photo_dir = photo_dir                 # 등록기계 사진 저장 폴더(None = TOWER_PHOTO_DIR 또는 저장소/data)
        self.gpu_lease = gpu_lease                 # user → GpuLease. None = GPU 사용권 안 씀(시험·가짜 부품)
        self._kiosk_fails: dict[str, int] = {}     # 키오스크 회수에서 신분 번호를 틀린 횟수(찾기 번호별)
        if storage is None:                        # 11/6 보관함 정답지(agents/storage.py). DB 모드면 PostgresStorageStore
            from agents.storage import MemoryStorageStore
            storage = MemoryStorageStore(item_lookup=self._storage_item)
        self.storage = storage

    def _storage_item(self, item_id: str) -> dict | None:
        """메모리 보관함용 물건 조회: 부품(DB·가짜 보관함) → 등록기계 접수 기록 순서로 찾는다"""
        try:
            item = self.backend_factory().db_get_item(item_id)
        except Exception:
            item = None
        if item is None:
            item = getattr(self.intake, "items", {}).get(item_id)
        if item is None:
            return None
        return {"status": item.get("status"),
                "category": item.get("category") or (item.get("features") or {}).get("category")}

    # ---------- 습득물 접수(등록기계 화면) ----------
    def list_places(self, machine_id: str, limit: int = 10) -> list[dict]:
        from agents.contracts import MACHINE_LETTERS
        if machine_id not in MACHINE_LETTERS:
            raise RequestError(f"machine_id: {list(MACHINE_LETTERS)} 중 하나")
        try:
            return self.intake.places(machine_id, max(1, min(int(limit), 30)))
        except IntakeError as e:
            raise RequestError(str(e)) from e
        except Exception as e:
            raise Unavailable(f"접수 저장소 연결 실패({type(e).__name__})") from e

    def create_item(self, payload: object) -> dict:
        """등록기계: 접수 → 접수 번호. 연락처는 저장만 하고 돌려주지 않는다.
        11/4: "photo"(data URL)를 함께 보내면 관제탑이 사진을 저장하고 photo_path 를 채운다(photo_path 와 같이 보내면 422)."""
        photo_file = None
        try:
            body = dict(payload) if isinstance(payload, dict) else payload
            photo = body.pop("photo", None) if isinstance(body, dict) else None
            if photo is not None and isinstance(body, dict) and body.get("photo_path") is not None:
                raise IntakeError("photo 와 photo_path 는 하나만")
            intake = parse_intake(body)
            if photo is not None:
                raw, ext = decode_photo(photo)
                intake["photo_path"], photo_file = save_photo(raw, ext, intake["machine_id"], self.photo_dir)
            row = self.intake.create(intake)
        except IntakeError as e:
            self._drop(photo_file)
            raise RequestError(str(e)) from e
        except Exception as e:
            self._drop(photo_file)
            raise Unavailable(f"접수 저장소 연결 실패({type(e).__name__})") from e
        return receipt(row)

    @staticmethod
    def _drop(path) -> None:
        """접수가 저장되지 않았으면 먼저 저장한 사진도 지운다(주인 없는 사진을 남기지 않게)."""
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass

    def set_item_features(self, item_id: str, payload: object) -> dict:
        """뒤에서 도는 Qwen 작업: 특징 채우기. 돌려주는 값은 공개 특징만(비공개 특징 = 확인 질문 정답)."""
        from agents.contracts import public_card
        if not valid_item_id(item_id):
            raise RequestError("item_id: 접수 번호 형식(예: A-20261103-0001)")
        try:
            feats = parse_features(payload)
            ok = self.intake.set_features(item_id, feats)
        except IntakeError as e:
            raise RequestError(str(e)) from e
        except Exception as e:
            raise Unavailable(f"접수 저장소 연결 실패({type(e).__name__})") from e
        if not ok:
            raise NotFound(f"없는 접수 번호: {item_id}")
        return {"item_id": item_id, "category": feats.get("category"), "features": public_card(
            {k: v for k, v in feats.items() if k != "category"})}

    # ---------- 찾기 요청(웹) ----------
    def create_claim(self, payload: object) -> dict:
        try:
            claim = parse_claim(payload)
        except ClaimError as e:
            raise RequestError(str(e)) from e
        try:
            row = self.claims.create(claim)
        except ClaimError as e:          # 없는 물건 등
            raise RequestError(str(e)) from e
        except Exception as e:
            raise Unavailable(f"찾기 요청 저장소 연결 실패({type(e).__name__})") from e
        return public_view(row)

    def get_claim(self, claim_id: str) -> dict | None:
        if not CLAIM_ID_RE.match(claim_id or ""):
            raise RequestError("claim_id: 찾기 번호 형식(예: C-20261103-0001)")
        try:
            row = self.claims.get(claim_id)
        except Exception as e:
            raise Unavailable(f"찾기 요청 저장소 연결 실패({type(e).__name__})") from e
        return public_view(row) if row else None

    def _request_from_claim(self, payload: dict) -> tuple[ReturnRequest, str]:
        cid, case, visit = parse_visit(payload)
        try:
            row = self.claims.get(cid)
        except Exception as e:
            raise Unavailable(f"찾기 요청 저장소 연결 실패({type(e).__name__}) — 웹 확인 결과를 못 읽어 실행하지 않음") from e
        if row is None:
            raise NotFound(f"없는 찾기 번호: {cid}")
        if row.get("status") != "booked":
            raise Conflict("duplicate", f"이미 방문 처리됐거나 취소된 찾기 요청: {cid} ({row.get('status')})")
        return ReturnRequest(case_id=case or f"R-{cid}", item_id=row["item_id"], **web_gates(row), **visit), cid

    def kiosk_return(self, payload: object) -> dict:
        """본센터 키오스크 회수(11/6, 직원 단계 제외). 화면은 관문 값을 보내지 못하고 서버가 정한다.
        - machine_id 는 CENTER 만, 본문은 machine_id·claim_id·id_no_masked 만
        - visitor_id_match: 키오스크에서 다시 입력한 가린 신분 번호 == 찾기 요청에 저장된 값 (틀리면 반환을 시작하지 않고 횟수만 센다)
        - inner_feature_ok: 웹의 확인 질문 통과(quiz_passed) 그대로
        - staff_confirmed: 로봇을 움직이기 전 직원 단계는 뺀다(11/5). 대신 제출보관함에서 직원 교차 검증(verify_handover)을
          통과해야 건넨다(11/6) — 그래서 서버가 True 로 둔다. 안전 규칙이라 PR 에서 이순필 확인 필요"""
        if not isinstance(payload, dict):
            raise RequestError("JSON 객체여야 합니다")
        unknown = sorted(set(payload) - KIOSK_RETURN_ALLOWED)
        if unknown or set(payload) != KIOSK_RETURN_ALLOWED:
            raise RequestError(f"본문은 {sorted(KIOSK_RETURN_ALLOWED)} 만 보냅니다(모르는 칸: {unknown})")
        if payload["machine_id"] != KIOSK_RETURN_MACHINE:
            raise RequestError(f"machine_id: 회수는 본센터 키오스크({KIOSK_RETURN_MACHINE})에서만 할 수 있습니다")
        cid, typed = payload["claim_id"], payload["id_no_masked"]
        if not isinstance(cid, str) or not CLAIM_ID_RE.match(cid):
            raise RequestError("claim_id: 찾기 번호 형식(예: C-20261103-0001)")
        if not isinstance(typed, str) or not typed.strip():
            raise RequestError("id_no_masked: 가린 신분 번호를 입력하세요")
        if self._kiosk_fails.get(cid, 0) >= KIOSK_MAX_FAILS:
            raise Conflict("locked", "신분 확인을 여러 번 틀려 키오스크에서는 더 할 수 없습니다. 역무실로 가 주세요")
        try:
            row = self.claims.get(cid)
        except Exception as e:
            raise Unavailable(f"찾기 요청 저장소 연결 실패({type(e).__name__}) — 신분을 확인하지 못해 실행하지 않음") from e
        if row is None:
            raise NotFound(f"없는 찾기 번호: {cid}")
        gates = web_gates(row)
        if not (gates["consent"] and gates["id_verified"] and gates["quiz_passed"]):
            raise Conflict("state", "웹 확인(동의·신분·확인 질문)이 끝나지 않은 찾기 요청 — 역무실로 가 주세요")
        if typed.strip() != row["id_no_masked"]:
            self._kiosk_fails[cid] = self._kiosk_fails.get(cid, 0) + 1
            raise RequestError("신분 번호가 맞지 않습니다. 다시 확인해 주세요")
        self._kiosk_fails.pop(cid, None)
        return self.start_return({"claim_id": cid, "visitor_id_match": True,
                                  "inner_feature_ok": gates["quiz_passed"], "staff_confirmed": True})

    def start_return(self, payload: object) -> dict:
        """1단계(관문 6개를 한 번에) 또는 2단계(claim_id + 현장 관문 3개) 요청을 받는다."""
        claim_id = None
        if isinstance(payload, dict) and "claim_id" in payload:
            req, claim_id = self._request_from_claim(payload)
        else:
            req = parse_request(payload)
        if not self._run_lock.acquire(blocking=False):
            raise Conflict("busy", "다른 반환이 진행 중입니다(로봇 1대). 끝난 뒤 다시 요청하세요")
        try:
            try:
                seen = self.recorder.has(req.case_id)
            except Exception as e:
                raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__}) — 중복 확인을 못 해 실행하지 않음") from e
            if seen:
                raise Conflict("duplicate", f"이미 처리한 사례 번호: {req.case_id}")
            self._stop_event.clear()
            be = GuardedBackend(self.backend_factory(), self._stop_event, self.gpu_lease)
            try:
                out = self.flow(req, be, self.reporter, reviewer=self.reviewer).to_dict()
            except Exception as e:   # 부품이 약속을 어기고 예외를 던진 경우 → 정지 시도 + 직원 확인
                out = self._crash(req, be, e)
            finally:
                be.gpu_release()     # 로봇 동작이 끝났거나 멈췄으면 GPU 사용권을 돌려준다
            if out.get("decision") not in DECISIONS:
                raise RuntimeError(f"알 수 없는 결정: {out.get('decision')}")
            if claim_id:
                out["claim_id"] = claim_id
                if out["decision"] == DECISION_RETURNED:
                    try:
                        self.claims.mark_visited(claim_id)
                    except Exception as e:   # 예약이 그대로면 같은 찾기 요청으로 다시 반환될 수 있음 → 직원에게 알림
                        try:
                            self.reporter.alert(req.case_id, f"방문 처리 저장 실패({type(e).__name__}) — 찾기 {claim_id} 다시 반환 금지, 직원 확인",
                                                f"물건 {req.item_id}")
                        except Exception:
                            pass
            try:
                self.recorder.save(req.item_id, out)
                out["recorded"] = True
            except Exception as e:   # 반환은 이미 끝남 → 결과는 돌려주고, 기록 실패만 알림
                out["recorded"] = False
                try:
                    self.reporter.alert(req.case_id, f"반환 기록 저장 실패({type(e).__name__}) — 직원이 기록 확인",
                                        f"물건 {req.item_id}")
                except Exception:
                    pass
            self._team_summary(req, out)
            return out
        finally:
            self._run_lock.release()

    def _team_summary(self, req: ReturnRequest, out: dict) -> None:
        """팀 대화 채널에 반환 1건당 결과 한 줄(물건·사례 번호만). 실패해도 반환 결과에는 영향 없음."""
        icon = {DECISION_RETURNED: "✅ 반환 완료", DECISION_REJECTED: "⛔ 반환 안 함",
                DECISION_STAFF: "🙋 직원 확인 필요", DECISION_STOPPED: "🛑 로봇 정지"}.get(out.get("decision"), "❔")
        saved = "" if out.get("recorded", True) else " · 기록 저장 실패"
        try:
            self.reporter.team(f"[{req.case_id}] 물건 {req.item_id} · {icon}",
                               f"{out.get('reason', '')} · {out.get('seconds', 0):.1f}초{saved}")
        except Exception:
            pass

    def _crash(self, req: ReturnRequest, be, err: Exception) -> dict:
        try:
            stopped = bool((be.robot_stop() or {}).get("ok"))
        except Exception:
            stopped = False
        reason = f"흐름 오류({type(err).__name__}) — 로봇 정지{'' if stopped else ' 실패'}, 직원 확인"
        try:
            self.reporter.alert(req.case_id, reason, f"물건 {req.item_id}")
        except Exception:
            pass
        return Outcome(req.case_id, DECISION_STOPPED, reason).to_dict()

    def _waiting_item(self, case_id: str):
        """인계할 물건 찾기: 반환 기록(바구니까지 전달) → 물건 → 지금 상태. (부품, 물건 번호, 상태)"""
        if not ID_RE.match(case_id or ""):
            raise RequestError("case_id: 영문·숫자·-·_ 1~32자")
        try:
            row = self.recorder.get(case_id)
        except Exception as e:
            raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__})") from e
        if row is None:
            raise NotFound(f"반환 기록 없음: {case_id}")
        if row.get("decision") != DECISION_RETURNED:
            raise Conflict("state", f"바구니까지 전달된 반환이 아님(결과 {row.get('decision')}) — 인계할 물건 없음")
        item_id = row.get("item_id")
        be = self.backend_factory()
        item = be.db_get_item(item_id)
        if item is None:
            raise NotFound(f"물건 기록 없음: {item_id}")
        return be, item_id, item.get("status")

    def handover(self, case_id: str, payload: object) -> dict:
        """직원 화면: 바구니의 물건을 분실인에게 건넸다 → 물건 상태 인계 대기 → 인계 완료 (11/4).
        본문은 {"staff_confirmed": true} 만 받는다. 로봇은 움직이지 않으므로 반환 실행 잠금을 쓰지 않는다."""
        if not isinstance(payload, dict) or set(payload) != {"staff_confirmed"} or payload["staff_confirmed"] is not True:
            raise RequestError('본문은 {"staff_confirmed": true} 만 보냅니다(직원이 건넨 것을 확인한 뒤)')
        be, item_id, status = self._waiting_item(case_id)
        if status == HANDOVER_DONE:
            raise Conflict("duplicate", f"이미 인계 완료: 물건 {item_id}")
        if status != HANDOVER_WAIT:
            raise Conflict("state", f"인계 대기 상태가 아님(지금 {status}) — 직원이 물건 위치 확인")
        r = be.db_set_status(item_id, HANDOVER_DONE, changed_by="staff")
        if not (r or {}).get("ok"):
            raise Unavailable(f"상태 기록 실패: {(r or {}).get('reason', '')}")
        try:
            self.reporter.progress(case_id, "인계 완료", f"물건 {item_id} · 직원이 분실인에게 건넴")
        except Exception:
            pass
        return {"case_id": case_id, "item_id": item_id, "status": HANDOVER_DONE}

    def hold_handover(self, case_id: str, payload: object) -> dict:
        """직원 화면: 인계 대기 중에 건네지 않기로 함(본인 아님 등) → 반환 보류 + 경보 (11/4).
        본문 {"reason": HOLD_REASONS 중 하나}. 자유 입력은 받지 않는다(기록·알림에 개인정보가 섞이지 않게)."""
        if not isinstance(payload, dict) or set(payload) != {"reason"} or payload["reason"] not in HOLD_REASONS:
            raise RequestError(f'본문은 {{"reason": {" | ".join(HOLD_REASONS)}}} 만 보냅니다')
        be, item_id, status = self._waiting_item(case_id)
        if status == HANDOVER_HOLD:
            raise Conflict("duplicate", f"이미 반환 보류: 물건 {item_id}")
        if status != HANDOVER_WAIT:
            raise Conflict("state", f"인계 대기 상태가 아님(지금 {status}) — 인계 취소할 수 없음")
        r = be.db_set_status(item_id, HANDOVER_HOLD, changed_by="staff")
        if not (r or {}).get("ok"):
            raise Unavailable(f"상태 기록 실패: {(r or {}).get('reason', '')}")
        try:
            self.reporter.alert(case_id, f"인계 취소 → 반환 보류({payload['reason']})", f"물건 {item_id} · 바구니에서 꺼내 보관, 직원 확인")
        except Exception:
            pass
        return {"case_id": case_id, "item_id": item_id, "status": HANDOVER_HOLD, "reason": payload["reason"]}

    # ---------- 인계 교차 검증(11/6, docs/design/handover_cross_check.md) ----------
    # 로봇이 제출보관함(H-1)에 둔 물건을 직원이 AI 판단과 독립적으로 3가지 확인한 뒤에만 건넨다.
    # 하나라도 틀리면 반환 보류 → 물건은 원래 보관 칸으로(칸 예약은 인계 완료 때만 풀림, 011 마이그레이션)
    def handover_queue(self, limit: int = 20) -> list[dict]:
        """직원 화면: 제출보관함에서 확인을 기다리는 반환(인계 대기). 개인정보는 가린 이름만"""
        out = []
        be = self.backend_factory()
        for row in self.recent(limit):
            if row.get("decision") != DECISION_RETURNED:
                continue
            item = be.db_get_item(row.get("item_id")) or {}
            if item.get("status") != HANDOVER_WAIT:
                continue
            feats = item.get("features") or {}
            claim = None
            if row.get("claim_id"):
                try:
                    c = self.claims.get(row["claim_id"])
                    claim = {"claim_id": c["claim_id"], "name_masked": c["name_masked"]} if c else None
                except Exception:
                    claim = None
            out.append({"case_id": row["case_id"], "item_id": row["item_id"], "claim": claim,
                        "category": item.get("category") or feats.get("category"),
                        "public": {k: feats[k] for k in ("color", "shape", "material") if feats.get(k)},
                        "has_photo": self.item_photo(row["item_id"]) is not None})
        return out

    def handover_secret(self, case_id: str) -> dict:
        """직원 화면 '답 보기': 비공개 특징(확인 질문 정답). 분실인 설명을 먼저 들은 뒤에만 연다(화면 쪽 규칙).
        인계 대기 중에만 돌려준다(끝난 사례의 정답은 다시 보여 주지 않음)."""
        be, item_id, status = self._waiting_item(case_id)
        if status != HANDOVER_WAIT:
            raise Conflict("state", f"인계 대기 상태가 아님(지금 {status})")
        feats = (be.db_get_item(item_id) or {}).get("features") or {}
        return {"case_id": case_id, "item_id": item_id,
                "secret": {k: feats[k] for k in ("mark", "visible_text") if feats.get(k)}}

    def verify_handover(self, case_id: str, payload: object) -> dict:
        """직원 교차 검증 결과. 본문 {"item_match": bool, "id_match": bool, "feature_match": bool}
        셋 다 True → 인계 완료. 하나라도 False → 반환 보류(이유는 서버가 정함: 신분 → 본인 아님, 물건·특징 → 물건 다름)"""
        if (not isinstance(payload, dict) or set(payload) != set(VERIFY_CHECKS)
                or not all(isinstance(payload[k], bool) for k in VERIFY_CHECKS)):
            raise RequestError(f"본문은 {list(VERIFY_CHECKS)} 세 칸(true/false)만 보냅니다")
        failed = [k for k in VERIFY_CHECKS if not payload[k]]
        summary = " · ".join(f"{VERIFY_CHECKS[k]} {'O' if payload[k] else 'X'}" for k in VERIFY_CHECKS)
        if not failed:
            out = self.handover(case_id, {"staff_confirmed": True})
            result = {**out, "result": HANDOVER_DONE, "checks": dict(payload)}
        else:
            reason = "본인 아님" if "id_match" in failed else "물건 다름"
            out = self.hold_handover(case_id, {"reason": reason})
            result = {**out, "result": HANDOVER_HOLD, "checks": dict(payload),
                      "next": "물건을 원래 보관 칸에 다시 넣고 '보관함으로 되돌림'을 누르세요"}
        try:
            self.reporter.progress(case_id, "교차 검증", f"물건 {result['item_id']} · {summary}")
        except Exception:
            pass
        return result

    def restock(self, case_id: str, payload: object) -> dict:
        """반환 보류된 물건을 원래 보관 칸에 다시 넣었다 → 본센터 보관(직원). 본문 {"staff_confirmed": true}"""
        if not isinstance(payload, dict) or set(payload) != {"staff_confirmed"} or payload["staff_confirmed"] is not True:
            raise RequestError('본문은 {"staff_confirmed": true} 만 보냅니다(원래 칸에 넣은 뒤)')
        be, item_id, status = self._waiting_item(case_id)
        if status != HANDOVER_HOLD:
            raise Conflict("state", f"반환 보류 상태가 아님(지금 {status})")
        r = be.db_set_status(item_id, "본센터 보관", changed_by="staff")
        if not (r or {}).get("ok"):
            raise Unavailable(f"상태 기록 실패: {(r or {}).get('reason', '')}")
        slot = None
        try:
            slot = next(({"slot_id": s["slot_id"], "pose_name": s["pose_name"]}
                         for sec in self.storage.layout()["sections"] for s in sec["slots"]
                         if s.get("item") and s["item"]["item_id"] == item_id), None)
        except Exception:
            pass
        try:
            self.reporter.progress(case_id, "보관함 복귀", f"물건 {item_id} · {slot['slot_id'] if slot else '칸 정보 없음'}")
        except Exception:
            pass
        return {"case_id": case_id, "item_id": item_id, "status": "본센터 보관", "slot": slot}

    def item_photo(self, item_id: str):
        """등록 사진 파일(Path) 또는 None. 사진 폴더 밖 경로는 거부"""
        from agents.intake import photo_root
        from pathlib import Path
        fn = getattr(self.intake, "photo_path", None)
        try:
            rel = fn(item_id) if callable(fn) else None
        except Exception:
            rel = None
        if not rel:
            return None
        root = Path(self.photo_dir) if self.photo_dir else photo_root()
        path = (root / rel).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            return None
        return path

    # ---------- 로봇 상태(11/5, docs/contracts/robot_api.md) ----------
    def robot_state(self) -> dict:
        """로봇 부품의 robot_state() — 화면(/live 진짜 부품 모드)이 관절 값을 보여 줄 때 읽는다. 없으면 available=false"""
        from agents.robot_api import validate_robot_state
        try:
            fn = getattr(self.backend_factory(), "robot_state", None)
            if not callable(fn):
                return {"available": False, "reason": "로봇 부품에 robot_state 가 없음(가짜 부품이거나 아직 연결 전)"}
            s = fn()
        except Exception as e:
            return {"available": False, "reason": f"상태 읽기 오류({type(e).__name__})"}
        errs = validate_robot_state(s)
        return {"available": True, **s} if not errs else {"available": False, "reason": "; ".join(errs)}

    # ---------- 로봇 정지 · 원점 복귀(직원 화면 버튼, 11/4) ----------
    def stop_robot(self) -> dict:
        """정지 버튼: 반환 진행 중에도 누를 수 있다. 다음 로봇 동작을 막고 robot_stop(즉시 정지만)을 부른다."""
        running = self._run_lock.locked()
        self._stop_event.set()
        try:
            r = self.backend_factory().robot_stop() or {}
        except Exception as e:
            r = {"ok": False, "reason": f"정지 명령 오류({type(e).__name__})"}
        ok = bool(r.get("ok"))
        try:
            self.reporter.alert("STAFF", f"🛑 직원 정지 버튼{' (반환 진행 중)' if running else ''}"
                                f"{'' if ok else ' — 정지 실패, 즉시 전원 차단·직원 호출'}",
                                "로봇 정지. 상황 확인 후 직원 화면 '원점 복귀'")
        except Exception:
            pass
        return {"ok": ok, "reason": r.get("reason", ""), "running": running}

    def robot_home(self, payload: object) -> dict:
        """원점 복귀 버튼: 직원이 주변을 확인한 뒤에만. 반환이 진행 중이면 거부(409 busy). 본문 {"staff_confirmed": true}"""
        if not isinstance(payload, dict) or set(payload) != {"staff_confirmed"} or payload["staff_confirmed"] is not True:
            raise RequestError('본문은 {"staff_confirmed": true} 만 보냅니다(로봇 주변을 확인한 뒤)')
        if not self._run_lock.acquire(blocking=False):
            raise Conflict("busy", "반환이 진행 중입니다. 먼저 정지 버튼을 누르고 반환이 끝난 뒤 원점 복귀하세요")
        try:
            try:
                r = self.backend_factory().robot_home() or {}
            except Exception as e:
                r = {"ok": False, "reason": f"원점 복귀 오류({type(e).__name__})"}
            ok = bool(r.get("ok"))
            try:
                if ok:
                    self.reporter.progress("STAFF", "원점 복귀 완료", "직원 화면 버튼")
                else:
                    self.reporter.alert("STAFF", f"원점 복귀 실패: {r.get('reason', '')}", "직원이 로봇 상태를 직접 확인")
            except Exception:
                pass
            return {"ok": ok, "reason": r.get("reason", "")}
        finally:
            self._run_lock.release()

    def get_case(self, case_id: str) -> dict | None:
        if not ID_RE.match(case_id or ""):
            raise RequestError("case_id: 영문·숫자·-·_ 1~32자")
        try:
            return self.recorder.get(case_id)
        except Exception as e:
            raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__})") from e

    def recent(self, limit: int = 20) -> list[dict]:
        try:
            return self.recorder.recent(max(1, min(limit, 100)))
        except Exception as e:
            raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__})") from e

    def health(self) -> dict:
        try:   # 상태 확인은 부품이 고장 나도 답해야 한다
            be = self.backend_factory()
            sources = be.sources() if callable(getattr(be, "sources", None)) else {"all": type(be).__name__}
        except Exception as e:
            sources = {"error": type(e).__name__}
        gpu = None
        if self.gpu_lease is not None:
            try:
                from agents.gpu_lease import holder
                h = holder()
                gpu = {"lease": "on", "holder": h}
            except Exception as e:
                gpu = {"lease": "on", "error": type(e).__name__}
        device = getattr(self.reviewer, "device", None) if self.reviewer is not None else None
        return {"ok": True, "busy": self._run_lock.locked(), "reviewer": self.reviewer is not None,
                "reviewer_device": device,     # 11/4: LLM 검토가 cpu 인지 gpu 인지(.env MAIN_AI_DEVICE)
                "send": not getattr(self.reporter, "dry_run", True), "sources": sources, "gpu": gpu or {"lease": "off"}}


def demo_backend_factory() -> Callable[[], object]:
    """진짜 부품이 없을 때 쓰는 시연용 부품: 보관함에 W01~W07, 접수 번호 A-W01 ~ A-W07.

    요청마다 새 가짜 부품을 만든다(집기 시도 횟수 같은 상태가 다음 요청에 남지 않게). 물건 상태만 이어진다.
    """
    import json
    from pathlib import Path

    from agents.backends import CompositeBackend
    from agents.tools import MockBackend

    spec = json.loads((Path(__file__).resolve().parent.parent / "evaluation" / "test_cases.json").read_text(encoding="utf-8"))
    objs = spec["objects"]
    # 물건 상태는 관제탑이 켜져 있는 동안 요청끼리 이어진다(반환 → 인계 대기 → 직원 인계 완료를 시연할 수 있게, 11/4)
    db = {f"A-{oid}": {"status": "본센터 보관", "features": objs[oid], "object_id": oid} for oid in objs}

    def make():
        bin_items = [{"object_id": oid, "features": objs[oid], "center": [100 + 80 * i, 240]}
                     for i, oid in enumerate(spec["bin"])]
        return CompositeBackend(fallback=MockBackend(bin_items=bin_items, db=db))
    return make


__all__ = ["TowerService", "RequestError", "Conflict", "Unavailable", "NotFound", "parse_request", "demo_backend_factory", "GATE_FIELDS"]
