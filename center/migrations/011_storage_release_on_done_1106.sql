-- 011 (11/6) 보관 칸은 '인계 완료' 때만 비운다 (LF-14, 변재원) — 인계 교차 검증(docs/design/handover_cross_check.md)
-- 이유: 제출보관함(인계 대기)에서 직원 교차 검증이 틀리면 반환 보류 → 물건을 **원래 칸**에 되돌려야 하므로,
--       인계 대기 동안에는 칸을 예약해 둔다(다른 물건이 들어오지 않게). 비전 내보내기는 보관 중 상태만 넣으므로 로봇 대상이 되지 않는다
CREATE OR REPLACE FUNCTION storage_release_on_handover() RETURNS trigger AS $$
BEGIN
    IF NEW.status IN ('인계 완료') THEN
        DELETE FROM storage_assignment WHERE item_id = NEW.item_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
