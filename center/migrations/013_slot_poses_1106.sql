-- 013 (11/6) 보관 칸 ↔ 로봇 저장 자세 연결 (LF-8, 변재원) — 김건태 확정(디스코드 일반 채널 11/6 16:32)
-- 자세 값 원본: 김건태 poses.json(Studio normalized 관절값, outputs/robot_panel_live/poses.json), 이름만 DB 에 둔다
-- 각 행 1(로봇팔 가까운 칸) = pose_1·3·5·7, 2(먼 칸) = pose_2·4·6·8, H-1(제출보관함·배출구) = close
-- 배출구 동작 순서: outlet_return_1 → close → open → outlet_return_1 → home (agents/storage.py OUTLET_SEQUENCE)
-- 이미 보관함 화면에서 직접 넣은 이름은 덮어쓰지 않는다(비어 있는 칸만 채움)
UPDATE storage_slot AS s SET pose_name = v.pose
FROM (VALUES ('R1-1', 'pose_1'), ('R1-2', 'pose_2'), ('R2-1', 'pose_3'), ('R2-2', 'pose_4'),
             ('R3-1', 'pose_5'), ('R3-2', 'pose_6'), ('R4-1', 'pose_7'), ('R4-2', 'pose_8'),
             ('H-1', 'close')) AS v(slot_id, pose)
WHERE s.slot_id = v.slot_id AND s.pose_name IS NULL;
