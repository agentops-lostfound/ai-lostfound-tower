-- AI 분실물 관제탑 DB v1 (PostgreSQL 16) — 설계·확정: 변재원(11/3). 확정 내용: docs/design/database.md 6장
-- 이미 만든 DB 는 이 파일이 다시 실행되지 않는다 → 바뀐 점은 center/migrations/*.sql (python tools/db_migrate.py --apply)
-- 설명·그림: docs/design/database.md
-- 원칙
--   1) 물건·사람 기록과 관제탑 기록을 한 DB에 두되, 표마다 주인을 정한다(주석의 [주인])
--   2) 개인정보는 최소로: 주민등록번호 칸 없음, 분실인 신분 정보는 가린 값만, 습득자 연락처는 따로 떼어 직원만 열람
--   3) 비공개 특징(mark·visible_text = 확인 질문 정답)은 공개 특징과 다른 칸에 둔다
--   4) 이미지 비슷함 검색(pgvector)은 임베딩 모델이 정해진 뒤 center/schema_vector.sql 로 추가한다
-- 실행: psql -d lostfound -f center/schema.sql  (여러 번 실행해도 안전: IF NOT EXISTS)

-- ========== 기준 정보 ==========
-- [주인: 변재원 LF-8] 습득물 등록기계·본센터
CREATE TABLE IF NOT EXISTS machine (
    machine_id    VARCHAR(16) PRIMARY KEY,                  -- 예: KIOSK-A, CENTER
    kind          VARCHAR(8)  NOT NULL CHECK (kind IN ('kiosk', 'center')),
    line          VARCHAR(16),                              -- 호선(등록기계만)
    station       VARCHAR(32),                              -- 설치 역
    is_virtual    BOOLEAN     NOT NULL DEFAULT FALSE        -- 시연용 가상 등록기계(B)
);

-- [주인: 김재민(화면)·변재원(DB)] 습득 장소 추천 목록(같은 호선·자주 나오는 장소부터)
CREATE TABLE IF NOT EXISTS place (
    place_id      SERIAL      PRIMARY KEY,
    line          VARCHAR(16) NOT NULL,
    station       VARCHAR(32) NOT NULL,
    label         VARCHAR(64) NOT NULL,                     -- 예: 남자 화장실 안
    use_count     INTEGER     NOT NULL DEFAULT 0,           -- 추천 순서용
    UNIQUE (line, station, label)
);

-- ========== 접수 ==========
-- [주인: 변재원 LF-8, 쓰기: 등록기계 화면(김재민)·비전(김건태), 읽기·상태 변경: 관제탑]
CREATE TABLE IF NOT EXISTS item (
    item_id          VARCHAR(32) PRIMARY KEY,               -- 접수 번호(화면에 보여 줌), 예: A-20261103-0001 (contracts.ITEM_ID_PATTERN)
    machine_id       VARCHAR(16) NOT NULL REFERENCES machine(machine_id),
    place_id         INTEGER     REFERENCES place(place_id),
    place_text       VARCHAR(128) NOT NULL,                 -- 고른 장소 또는 직접 입력(필수)
    received_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           VARCHAR(16) NOT NULL DEFAULT '등록기계 보관'
                     CHECK (status IN ('등록기계 보관', '회수 중', '본센터 보관', '확인 중',
                                       '승인·수령 예약', '반환 중', '인계 완료', '반환 보류')),
    category         VARCHAR(16) NOT NULL DEFAULT '확인 불가', -- contracts.CATEGORIES (MVP: 지갑)
    features         JSONB       NOT NULL DEFAULT '{}',     -- 공개 특징: color·shape·material·confidence
    private_features JSONB       NOT NULL DEFAULT '{}',     -- 비공개 특징: mark·visible_text (후보 카드·MCP에 안 보임)
    photo_path       VARCHAR(256),                          -- 접수 사진 파일 위치(사진은 DB 밖 저장)
    object_id        VARCHAR(32),                           -- 시연·평가용 물건 ID(정답지 W01 등)
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (NOT (private_features ?| ARRAY['color', 'shape', 'material'])),
    CHECK (NOT (features ?| ARRAY['mark', 'visible_text'])),
    CONSTRAINT item_id_format CHECK (item_id ~ '^[A-Z]-([0-9]{8}-[0-9]{4}|W[0-9]{2})$')
);
CREATE INDEX IF NOT EXISTS item_status_idx ON item (status);
CREATE INDEX IF NOT EXISTS item_machine_idx ON item (machine_id, received_at);

-- [주인: 변재원 LF-8] 습득자 연락처(선택 입력 = 저장 동의). 주인이 찾아가면 감사 연락에만, 직원만 열람
-- 보관: 물건이 '인계 완료'된 뒤 30일이 지나면 지운다(tools/purge_contacts.py, 관제탑 켤 때 자동 실행)
CREATE TABLE IF NOT EXISTS finder_contact (
    item_id      VARCHAR(32) PRIMARY KEY REFERENCES item(item_id),
    name         VARCHAR(32),
    phone        VARCHAR(20),
    consented_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- [주인: 변재원 LF-8] 상태가 바뀐 기록(누가·언제·무엇에서 무엇으로)
CREATE TABLE IF NOT EXISTS item_status_log (
    id          SERIAL      PRIMARY KEY,
    item_id     VARCHAR(32) NOT NULL REFERENCES item(item_id),
    from_status VARCHAR(16),
    to_status   VARCHAR(16) NOT NULL,
    changed_by  VARCHAR(16) NOT NULL CHECK (changed_by IN ('kiosk', 'staff', 'tower', 'system')),
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS item_status_log_item_idx ON item_status_log (item_id, at);

-- ========== 회수 (등록기계 → 본센터, 하루 1번) ==========
-- [주인: 변재원 LF-8]
CREATE TABLE IF NOT EXISTS collection (
    collection_id SERIAL      PRIMARY KEY,
    machine_id    VARCHAR(16) NOT NULL REFERENCES machine(machine_id),
    picked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),       -- 등록기계에서 꺼냄
    arrived_at    TIMESTAMPTZ                               -- 본센터 도착(입고 확인)
);
CREATE TABLE IF NOT EXISTS collection_item (
    collection_id INTEGER     NOT NULL REFERENCES collection(collection_id),
    item_id       VARCHAR(32) NOT NULL REFERENCES item(item_id),
    arrived       BOOLEAN     NOT NULL DEFAULT FALSE,       -- 도착 확인되면 TRUE (빠진 물건 찾기)
    PRIMARY KEY (collection_id, item_id)
);

-- ========== 찾기 (분실인 웹) ==========
-- [주인: 김재민(화면)·정연우(설명 구조화)] 찾기 요청 1건 = 분실인 1명의 1회 방문 과정
CREATE TABLE IF NOT EXISTS claim (
    claim_id       VARCHAR(32) PRIMARY KEY CONSTRAINT claim_id_format CHECK (claim_id ~ '^C-[0-9]{8}-[0-9]{4}$'), -- 예: C-20261103-0001
    consented_at   TIMESTAMPTZ NOT NULL,                    -- 필수 동의(없으면 요청을 만들지 않음)
    name_masked    VARCHAR(32) NOT NULL,                    -- OCR 이름 가린 값, 예: 변*원
    id_no_masked   VARCHAR(32) NOT NULL,                    -- 신분증 번호 가린 값(주민등록번호 항목 없음)
    description    JSONB       NOT NULL DEFAULT '{}'        -- 설명을 접수 특징과 같은 칸 이름으로(contracts.DESCRIPTION_FIELDS)
                   CONSTRAINT claim_description_keys
                   CHECK ((description - ARRAY['category', 'color', 'shape', 'mark', 'visible_text', 'material']) = '{}'::jsonb),
    lost_line      VARCHAR(16),
    lost_station   VARCHAR(32),
    lost_date      DATE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- [주인: 김건태(매칭)·김재민] 후보 1·2·3 (점수는 내부용, 분실인 화면에 안 보임)
CREATE TABLE IF NOT EXISTS claim_candidate (
    claim_id  VARCHAR(32) NOT NULL REFERENCES claim(claim_id),
    item_id   VARCHAR(32) NOT NULL REFERENCES item(item_id),
    rank      SMALLINT    NOT NULL CHECK (rank BETWEEN 1 AND 3),
    score     REAL        NOT NULL,
    PRIMARY KEY (claim_id, item_id),
    UNIQUE (claim_id, rank)
);

-- [주인: 김재민] 확인 질문 시도(정답·입력한 답은 저장하지 않음, 맞았는지만)
CREATE TABLE IF NOT EXISTS quiz_attempt (
    id         SERIAL      PRIMARY KEY,
    claim_id   VARCHAR(32) NOT NULL REFERENCES claim(claim_id),
    item_id    VARCHAR(32) NOT NULL REFERENCES item(item_id),
    field      VARCHAR(16) NOT NULL CHECK (field IN ('mark', 'visible_text', 'place', 'color', 'shape')),
    passed     BOOLEAN     NOT NULL,
    at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS quiz_attempt_claim_idx ON quiz_attempt (claim_id, at);

-- [주인: 김재민] 수령 예약(메인 AI 승인 뒤)
CREATE TABLE IF NOT EXISTS reservation (
    claim_id   VARCHAR(32) PRIMARY KEY REFERENCES claim(claim_id),
    item_id    VARCHAR(32) NOT NULL REFERENCES item(item_id),
    visit_date DATE        NOT NULL,
    status     VARCHAR(12) NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'visited', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========== 반환 (관제탑) ==========
-- [주인: 관제탑(변재원)] agents/records.py 가 반환이 끝날 때마다 저장
CREATE TABLE IF NOT EXISTS return_case (
    case_id        VARCHAR(32)  PRIMARY KEY,                -- 같은 번호로 두 번 실행하지 않음
    item_id        VARCHAR(32)  NOT NULL REFERENCES item(item_id),
    claim_id       VARCHAR(32)  REFERENCES claim(claim_id), -- 웹 찾기에서 온 반환이면 연결
    decision       VARCHAR(16)  NOT NULL
                   CHECK (decision IN ('returned', 'rejected', 'staff_check', 'stopped')),
    reason         TEXT         NOT NULL,                   -- 결정 이유(개인정보 없음)
    approved       BOOLEAN      NOT NULL DEFAULT FALSE,
    matched_object VARCHAR(32),
    seconds        REAL         NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS return_case_item_idx ON return_case (item_id);

CREATE TABLE IF NOT EXISTS return_step (
    id        SERIAL      PRIMARY KEY,
    case_id   VARCHAR(32) NOT NULL REFERENCES return_case(case_id),
    step      VARCHAR(64) NOT NULL,
    detail    TEXT,
    at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========== 통계 질문(Text2SQL)용 읽기 전용 보기 — 개인정보 칸 없음 ==========
-- [주인: 정연우 LF-9]
CREATE OR REPLACE VIEW stats_item AS
    SELECT i.item_id, i.machine_id, m.line, m.station, i.category, i.status, i.received_at
    FROM item i JOIN machine m USING (machine_id);
CREATE OR REPLACE VIEW stats_return AS
    SELECT r.case_id, r.item_id, r.decision, r.approved, r.seconds, r.created_at
    FROM return_case r;
