"""사진 분석(Qwen) 지켜보기 — 통합 시연 화면(/showcase)의 "사진 분석" 카드 (LF-18, 11/10 변재원)

한줄 설명: 키오스크가 찍은 사진이 **접수 → 작업자가 가져감 → Qwen 분석 → 결과 → 저장할 값으로 바꿈**까지 가는 과정을
진행 기록판(LiveBoard)의 vision 사건으로 남긴다. 화면은 그 사건으로 "Qwen 이 무엇을 읽었고, 그것이 DB 의 어떤 값이 됐는지"를 보여 준다.

- 분석은 관제탑이 아니라 Qwen 작업자(tools/intake_qwen_worker.py, 관제탑 PC 의 Qwen 전용 가상환경)가 한다.
  이 부품은 작업자가 관제탑을 부르는 순간(대기 목록 조회·단계 알림·결과 보내기)을 보고 사건을 만들 뿐이다
- 작업자가 켜져 있는지: 대기 목록을 마지막으로 물어본 때(2초마다 묻는다)로 판단한다
- 비공개 특징(확인 질문 정답)은 값 대신 개수·상태만 넣는다: 읽은 글자(logos_or_text)·스티커(stickers)·특이점(distinctive_features).
  공개 값(종류·색·모양·재질)은 그대로. 글자 값에는 observability.mask_text 를 한 번 더 건다
- 사건 만들기에 실패해도 접수·분석·저장은 그대로 된다(모두 감싸 조용히 넘김)
"""
from __future__ import annotations

import threading
import time

from agents.observability import mask_text

STAGES = {"queued": "사진 접수 · 분석 차례 기다림", "picked": "작업자가 사진을 가져감", "wait_gpu": "그래픽카드 차례 기다림",
          "analyze": "Qwen 분석 중", "result": "결과 도착", "fail": "분석 실패"}
WORKER_STAGES = ("wait_gpu", "analyze", "fail")      # 작업자가 직접 알릴 수 있는 단계
WORKER_ALIVE_S = 12.0                                  # 이 시간 안에 대기 목록을 물었으면 작업자가 켜져 있다고 본다
MAX_ITEMS = 200


def _txt(v, limit: int = 60) -> str:
    s = mask_text(str(v if v is not None else "-"))
    return s if len(s) <= limit else s[:limit - 1] + "…"


def raw_view(qwen: dict | None) -> dict:
    """Qwen 원본 결과에서 화면에 내도 되는 것만: 공개 값은 그대로, 비공개 값은 개수·상태만"""
    q = qwen if isinstance(qwen, dict) else {}
    texts = [t for t in q.get("logos_or_text") or [] if isinstance(t, str) and t.strip()]
    stickers = [s for s in q.get("stickers") or [] if isinstance(s, dict)]
    return {"category": _txt(q.get("category")), "colors": [_txt(c, 20) for c in (q.get("colors") or [])[:5]],
            "shape": _txt(q.get("shape")), "materials": [_txt(m, 20) for m in (q.get("materials") or [])[:5]],
            "logos_or_text": f"{len(texts)}개 읽음" if texts else "읽은 글자 없음",
            "stickers": {"present": f"{len(stickers)}개 있음", "absent": "없음"}.get(q.get("sticker_status"), "알 수 없음"),
            "distinctive_features": f"{len(q.get('distinctive_features') or [])}개"}


def saved_view(feats: dict | None) -> dict:
    """저장할 값(계약 특징)에서 화면에 내도 되는 것만: 공개 칸은 값, 비공개 칸(mark·visible_text)은 상태만"""
    from agents.contracts import NONE, UNKNOWN
    f = feats if isinstance(feats, dict) else {}

    def secret(v):
        return "없음" if v == NONE else "확인 불가" if v in (None, UNKNOWN, "") else "저장됨(값은 가림)"
    return {"category": _txt(f.get("category")), "color": _txt(f.get("color")), "shape": _txt(f.get("shape")),
            "material": _txt(f.get("material")), "confidence": f.get("confidence"),
            "mark": secret(f.get("mark")), "visible_text": secret(f.get("visible_text"))}


class VisionWatch:
    def __init__(self, board, clock=time.time):
        self.board, self._clock = board, clock
        self._lock = threading.Lock()
        self._queued: dict[str, float] = {}      # 접수 번호 → 접수 시각
        self._picked: set[str] = set()
        self._seen = 0.0                         # 작업자가 대기 목록을 마지막으로 물은 때

    def _emit(self, item_id: str, stage: str, **more) -> None:
        try:
            self.board.vision({"item_id": item_id, "stage": stage, "label": STAGES.get(stage, stage), **more})
        except Exception:
            pass

    def queued(self, item_id: str, machine: str = "") -> None:
        """키오스크가 사진과 함께 접수함 → 분석 차례를 기다린다"""
        with self._lock:
            self._queued[item_id] = self._clock()
            if len(self._queued) > MAX_ITEMS:
                for k in list(self._queued)[:MAX_ITEMS // 2]:
                    self._queued.pop(k, None)
                    self._picked.discard(k)
        self._emit(item_id, "queued", machine=machine, worker=self.worker()["on"])

    def polled(self, rows: list[dict] | None) -> None:
        """작업자가 대기 목록을 물음 → 켜져 있다는 표시 + 목록에 처음 나간 물건은 '가져감'"""
        fresh = []
        with self._lock:
            self._seen = self._clock()
            for r in rows or []:
                iid = r.get("item_id") if isinstance(r, dict) else None
                if iid and iid not in self._picked:
                    self._picked.add(iid)
                    fresh.append(iid)
        for iid in fresh:
            self._emit(iid, "picked", waited=self._waited(iid))

    def stage(self, item_id: str, stage: str, detail: str = "") -> bool:
        """작업자가 알린 단계(그래픽카드 기다림·분석 시작·실패). 모르는 단계는 받지 않는다"""
        if stage not in WORKER_STAGES:
            return False
        with self._lock:
            self._seen = self._clock()
        self._emit(item_id, stage, detail=_txt(detail, 100), waited=self._waited(item_id))
        return True

    def result(self, item_id: str, qwen: dict | None, feats: dict | None) -> None:
        """결과가 들어와 저장됨: Qwen 이 읽은 값(원본)과 저장한 값을 나란히"""
        self._emit(item_id, "result", seconds=self._waited(item_id), raw=raw_view(qwen), saved=saved_view(feats))
        with self._lock:
            self._queued.pop(item_id, None)
            self._picked.discard(item_id)

    def _waited(self, item_id: str):
        with self._lock:
            t = self._queued.get(item_id)
        return None if t is None else round(self._clock() - t, 1)

    def worker(self) -> dict:
        with self._lock:
            ago = None if not self._seen else round(self._clock() - self._seen, 1)
        return {"on": ago is not None and ago <= WORKER_ALIVE_S, "seen_ago": ago}


__all__ = ["VisionWatch", "raw_view", "saved_view", "STAGES", "WORKER_STAGES"]
