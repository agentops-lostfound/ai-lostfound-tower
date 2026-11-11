-- 021 (11/11) 로봇 보관 칸은 물건이 제출보관함에 놓이는 순간(인계 대기) 비운다 (LF-18, 변재원) — 사용자 요청
-- 1) 011(11/6)은 '인계 완료' 때만 비웠다: 제출보관함에서 직원 교차 검증이 틀리면 원래 칸에 되돌리려고 인계 대기 동안 칸을 예약.
-- 2) 11/11 무인 인계(분실인이 직접 꺼내고 키오스크 [물건 받았어요])가 기본이 되자, 실물 칸은 비었는데 기록상 예약이 남아
--    · 새 물건이 R3-1 대신 R3-2 로 가고  · 다음 물건이 '칸 대기'가 되고  · [물건 받았어요]를 누르지 않으면 대기 물건이 영영 안 올라옴
-- 3) 이제 인계 대기가 되면 로봇 보관 칸(storage_section.kind = 'shelf', R1~R4)의 배정을 지운다. 직원 보관 선반(kind 'staff', S)은
--    직원이 꺼내 건넬 때까지 남긴다(인계 완료 때 비움 — 011 그대로). 드물게 반환 보류 → 되돌릴 때는 그때의 빈 칸(보관 화면 추천)에 넣는다
-- (agents/storage.py RELEASE_STATUSES · OUTLET_STATUS 와 같게 — tests/test_storage.py)
--
-- 되돌리기(직접 실행): 011 의 함수 본문으로 — IF NEW.status IN ('인계 완료') THEN DELETE ... END IF;
CREATE OR REPLACE FUNCTION storage_release_on_handover() RETURNS trigger AS $$
BEGIN
    IF NEW.status IN ('인계 완료') THEN
        DELETE FROM storage_assignment WHERE item_id = NEW.item_id;
    ELSIF NEW.status = '인계 대기' THEN
        DELETE FROM storage_assignment a
         USING storage_slot s, storage_section sec
         WHERE a.item_id = NEW.item_id AND a.slot_id = s.slot_id
           AND s.section_code = sec.section_code AND sec.kind = 'shelf';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
