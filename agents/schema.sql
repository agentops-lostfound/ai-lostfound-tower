-- 관제탑 소유 표 (docs/design/erd.md). 같은 PostgreSQL 안에 두고, 물건 표(item)는 DB 담당(정연우 LF-8)이 만든다.
-- 개인정보 칼럼은 두지 않는다(이름·전화·신분증 값 없음). item 표 이름이 정해지면 FK 를 맞춘다.

CREATE TABLE IF NOT EXISTS return_case (
    case_id        VARCHAR(32)  PRIMARY KEY,               -- 반환 사례 번호(같은 번호로 두 번 실행하지 않음)
    item_id        VARCHAR(32)  NOT NULL,                  -- 접수 번호 (FK → item.item_id, LF-8 확정 후)
    decision       VARCHAR(16)  NOT NULL
                   CHECK (decision IN ('returned', 'rejected', 'staff_check', 'stopped')),
    reason         TEXT         NOT NULL,                  -- 결정 이유(개인정보 없음)
    approved       BOOLEAN      NOT NULL DEFAULT FALSE,    -- 웹 단계 승인 여부
    matched_object VARCHAR(32),                            -- 집은 물건 ID
    seconds        REAL         NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS return_step (
    id        SERIAL       PRIMARY KEY,
    case_id   VARCHAR(32)  NOT NULL REFERENCES return_case(case_id),
    step      VARCHAR(64)  NOT NULL,                       -- 단계 이름
    detail    TEXT,                                        -- 점수·시도 횟수 등
    at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS return_case_item_idx ON return_case (item_id);
