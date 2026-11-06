-- 007 (11/6) 본센터 보관함 정답지 — 구역(행)·칸·저장 자세·물건 보관 위치 (LF-8, 변재원)
-- 한줄 설명: "어떤 물건이 보관함 몇 행 몇 번 칸에 있고, 로봇팔은 어느 저장 자세로 가야 하는가"를 DB 에 남긴다.
-- 비전(김건태) run_storage_check.py 의 --storage JSON 은 tools/storage_export.py 가 이 표들로 만든다.
-- 배치: 보관판(가로 약 50cm × 세로 약 25cm)을 4행 × 2칸 = 8칸 + 인계 구역(제출보관함 20×20cm) 1칸
--       모형폰 행은 폰 2개를 각각 가로로 눕혀 둔다. 행별 품목은 시작값(추정)이며 화면·API 로 바꿀 수 있다
-- 저장 자세(pose_name)는 로봇 티칭(robot/teaching_gui.py)에서 정한 이름. 티칭 전에는 비워 둔다(NULL)
-- agents/storage.py LAYOUT 과 같게 유지한다(tests/test_storage.py 가 확인)

CREATE TABLE IF NOT EXISTS storage_section (
    section_code       VARCHAR(8)  PRIMARY KEY,                  -- R1~R4(행), H(인계 구역)
    label              VARCHAR(32) NOT NULL,
    kind               VARCHAR(8)  NOT NULL CHECK (kind IN ('shelf', 'handover')),
    allowed_categories TEXT[]      NOT NULL DEFAULT '{}',        -- 빈 배열 = 품목 제한 없음
    bounds_mm          JSONB,                                    -- 작업대 mm [x1, y1, x2, y2] (ArUco 기준, 선택)
    sort_order         SMALLINT    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS storage_slot (
    slot_id      VARCHAR(8)  PRIMARY KEY,                        -- 예: R1-1, R1-2, H-1
    section_code VARCHAR(8)  NOT NULL REFERENCES storage_section(section_code),
    slot_no      SMALLINT    NOT NULL CHECK (slot_no > 0),
    pose_name    VARCHAR(32) CHECK (pose_name ~ '^[a-z][a-z0-9_]{0,31}$'),  -- 저장 자세 이름(티칭 전 NULL)
    note         VARCHAR(64),                                    -- 예: 가로 배치
    UNIQUE (section_code, slot_no)
);

-- 칸 하나에 물건 하나(PK), 물건 하나는 칸 하나(UNIQUE)
CREATE TABLE IF NOT EXISTS storage_assignment (
    slot_id     VARCHAR(8)  PRIMARY KEY REFERENCES storage_slot(slot_id),
    item_id     VARCHAR(32) NOT NULL UNIQUE REFERENCES item(item_id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_by VARCHAR(16) NOT NULL DEFAULT 'staff' CHECK (assigned_by IN ('staff', 'tower', 'system'))
);

-- 탑뷰 개수 확인 기록(run_storage_check.py 결과 status 를 그대로 남김). 개인정보 없음
CREATE TABLE IF NOT EXISTS inventory_check (
    id             SERIAL      PRIMARY KEY,
    section_code   VARCHAR(8)  NOT NULL REFERENCES storage_section(section_code),
    item_id        VARCHAR(32) REFERENCES item(item_id),
    expected_count SMALLINT    NOT NULL CHECK (expected_count >= 0),
    detected_count SMALLINT    CHECK (detected_count >= 0),
    status         VARCHAR(32) NOT NULL CHECK (status IN ('count_match', 'count_mismatch', 'verification_unavailable',
                                                         'resolution_mismatch', 'invalid_calibration',
                                                         'section_out_of_frame', 'match_held')),
    at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS inventory_check_section_idx ON inventory_check (section_code, at);

-- 물건이 인계 대기·인계 완료가 되면(바구니로 나감) 보관 칸을 자동으로 비운다
CREATE OR REPLACE FUNCTION storage_release_on_handover() RETURNS trigger AS $$
BEGIN
    IF NEW.status IN ('인계 대기', '인계 완료') THEN
        DELETE FROM storage_assignment WHERE item_id = NEW.item_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS storage_release_on_handover ON item;
CREATE TRIGGER storage_release_on_handover AFTER UPDATE OF status ON item
    FOR EACH ROW WHEN (NEW.status IS DISTINCT FROM OLD.status) EXECUTE FUNCTION storage_release_on_handover();

-- 시작 배치(추정) — 이미 있으면 그대로 둔다(화면에서 바꾼 값 보존)
INSERT INTO storage_section (section_code, label, kind, allowed_categories, sort_order) VALUES
  ('R1', '1행 모형폰',          'shelf',    '{모형폰}',             1),
  ('R2', '2행 USB·핸드크림',     'shelf',    '{USB,핸드크림}',        2),
  ('R3', '3행 립밤',            'shelf',    '{립밤}',               3),
  ('R4', '4행 지갑·보조배터리',   'shelf',    '{지갑,보조배터리}',      4),
  ('H',  '인계 구역(제출보관함)', 'handover', '{}',                   5)
ON CONFLICT (section_code) DO NOTHING;

INSERT INTO storage_slot (slot_id, section_code, slot_no, note) VALUES
  ('R1-1', 'R1', 1, '가로 배치'), ('R1-2', 'R1', 2, '가로 배치'),
  ('R2-1', 'R2', 1, NULL),       ('R2-2', 'R2', 2, NULL),
  ('R3-1', 'R3', 1, NULL),       ('R3-2', 'R3', 2, NULL),
  ('R4-1', 'R4', 1, NULL),       ('R4-2', 'R4', 2, NULL),
  ('H-1',  'H',  1, '20×20cm')
ON CONFLICT (slot_id) DO NOTHING;
