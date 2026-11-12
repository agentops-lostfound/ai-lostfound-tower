# 레거시/정지 조건 감사 (2026-11-11, v0.2.37 기준, 읽기 전용 점검)

점검: Claude(Fable, medium). grasp_flow.py 전체 + 호출 헬퍼를 읽고 사용처는 grep으로 확인. 파일 쓰기 없는 단위 테스트 12개 모듈 56건 통과.
주의: 감사 후 v0.2.38에서 grasp_flow.py 바닥 접촉 블록(약 20줄)이 바뀌어 grasp_flow.py의 그 아래 줄 번호는 몇 줄 밀렸을 수 있음.

## 0. 실제 호출 경로 (오늘 설정)
- simple_mode 항상 True (server.py:227 기본값, beta.js:38 토글 숨김) → relaxed도 항상 True (grasp_flow.py:205).
- tcp_active.json 없음 → Model().position_calibration=None.
- workflow.json: finish_mode='hold', return_waypoints=[], calibration_stop=false → 반환 경로 분기(grasp_flow.py:855-880) 미실행.

## A. 삭제 후보 (죽은 코드)
| # | 위치 | 근거 | 같이 정리 |
|---|---|---|---|
| A1 | grasp_flow.py:284-301, 400-408, 758 / local_grasp_correction.py 전체 / beta_data/local_grasp_correction.json | `correction=None if simple_mode or common_profile else ...` → 항상 None. central_observed 분기(하드코딩 [234.4,101.0], roll_window=(3074,200))도 not simple_mode 조건 | approach_path.py:58 roll_window 검사 |
| A2 | grasp_flow.py:287 `position_calibration={'mode':'legacy_provisional'}` | 적용 안 되는데 매 리포트에 기록 | - |
| A3 | grasp_alignment.py:10-54 measure(), grasp_flow.py:543 `else measure_alignment(...)` | simple_mode=False일 때만 호출 | test_grasp_alignment.py |
| A4 | grasp_alignment.py:57-79 descent_clearance() | 운영 호출 0건 (테스트만) | 〃 |
| A5 | grasp_alignment.py:178 draw_clearance, :208 measure_visible_side | import만, 호출 없음 | - |
| A6 | grasp_contact.py 전체 | import만 (LiftTracker로 대체) | test_grasp_contact.py |
| A7 | grasp_guard.py 전체 | test_grasp_guard.py만 import | 〃 |
| A8 | reproduction.py, beta_data/provisional_reproduction.json | test_reproduction.py만 import | 〃 |
| A9 | robot_actions.py:30-33 small_move_arrival, manual_worker.py:27-33·207-210 dict 허용오차/arrival_displacement_ticks, robot_actions.py:116,130 인자 | 모든 move가 정수 46 | test_gap_revision.py:50-58 |
| A10 | grasp_flow.py:146 corrected_model_roll | 운영 호출 없음 | test_rotation_polarity.py:7-17 |
| A11 | position_diagnostics.py:31 observed_translation | 테스트만 | test_position_diagnostics.py:15 |
| A12 | grasp_flow.py:42,104 WIDE_DEEPER_MM=0 및 −7mm 설명 주석 | 무효 연산 | - |
| A13 | grasp_flow.py 미사용 import(cv2, uuid, Path, ALL, verify_lift, draw_clearance, measure_visible_side), goals 리스트(:263,:445) | grep 확인 | - |
| A14 | robot_actions.py:128 `if duration>20`, :243 start 변수 | 도달 불가 / 미사용 | - |
| A15 | gap_observation.py:67-73 ratios | 계산만 하고 안 씀 | - |
| A16 | grasp_flow.py:650 '영상 보정 명령 한도 초과' | coarse_grasp.py:68-70이 먼저 클립·raise | - |
| A17 | grasp_flow.py:530 load_fixed_finger(...) | 반환값 버림 (:470, :595 중복) | - |
| A18 | manual_worker.py:306-307 '집게가 닫히기 시작하지 않음' | goal=max(goal,pos-8) 때문에 사실상 도달 불가 (B13 참고) | - |
| A19 | 비-relaxed 분기: grasp_flow.py:128 [60], :130·:312 5°, :441 12°, approach_path.py:37,49,71 strict | relaxed 항상 True | - |
| A20 | grasp_geometry.pink_tube 색 문자열 경로(:27-62), target_mask 색 이름 분기, finger_edges.py:19, server.py:115-119 /api/grasp/geometry | 집기는 항상 dict 경로, 해당 API는 UI 호출 없음 | test_grasp_geometry.py |
| A21 | arm_fixed_finger_reference_trial.json, joint_direction_observations.json, user_grasp_verifications.jsonl | beta/*.py 참조 0건 | archives/로 이동 |

## B. 정지 조건 재검토 (허용오차·일관성 게이트)
| # | 위치 / 메시지 | 문제 | 권장 |
|---|---|---|---|
| B1 | grasp_flow.py:172-173 '현재 높이에서 손목 회전 경로의 위치/기울기 조건…' | XY8/높이5/기울기10°/판+20. 기울기 10°가 far_tilt 15°·stage_tilt 18°와 충돌, 처짐이 높이차에 섞임. 19:47 f1f0c3c7 실패 | 판+20만 정지, 나머지 경고 (최소 기울기는 stage_tilt) |
| B2 | robot_actions.py:185-210, go_home:219 '30mm 수직 상승 경로를 계산할 수 없습니다' | 실패 시 HOME 자체 거부. 손목 한계 자세에서 잘 걸림 | 실패해도 가능한 만큼 상승 후 HOME 진행 |
| B3 | coarse_grasp.py:72 '간격 보정 이동량이 작아 영상 반응을 판단할 수 없습니다' | FK 이동 <0.7mm면 정지. v0.2.36 방침과 중복 | 삭제 (재측정만, 기울기 갱신 생략) |
| B4 | coarse_grasp.py:79 '영상 간격 변화가 불명확', :81 '반응 방향이 이전 측정과 반대' | 작은 이동은 잡음으로 부호 반전 | 이동 <1.5mm면 판정 생략, 부호 반전은 1회 재시도 후 |
| B5 | gap_observation.py:85-87, coarse_grasp.py:33-35, grasp_flow.py:618-619 (상한 high_px) | 넓은 물품 band 약 2.3mm → 맞추기 어려워 반복 실패 | 정지는 gap>=low만, 상한 초과는 경고 |
| B6 | partial_boundary.py:60-61,69 '잘린 물체 연결 근거 부족' | topview_both_sides_clear·loose_lab_match가 큰 물체 인식을 통째로 실패시킴. 18:57 2a93027c 실패 | 두 항목은 기록만, 정지는 edge_direction·connection |
| B7 | view_clearance.py:20 → grasp_flow.py:510 '조건부 시야 확보 실패' | 기울기 10° 하드코딩 | stage_tilt 전달 |
| B8 | grasp_flow.py:583-585 '회전 후 영상 정렬이 개선되지 않았습니다' / '영상 방향 보정 미완료' | 개선 <2° 또는 4회 후 12°(경계 8°) 초과 | 5° 이상 악화 때만 정지, 4회 후 15° 이하면 경고 진행 |
| B9 | grasp_flow.py:128-135, :760, :847 'IK 해를 찾지 못했습니다' | max_tilt_deg(10/15)와 stage_tilt(18) 불일치, 하강 IK 사전확인이 죽은 분기에만 있음 | 통일 + 이동 전 하강·상승 IK 확인 |
| B10 | grasp_flow.py:337 | 15° 재시도·오프셋 직접계획이 예외 문자열 매칭에 의존. approach_path.py:109 경로검사 실패는 재시도 없음 | 예외 종류로 구분, 경로 검사 실패도 재시도 |
| B11 | grasp_alignment.py:96-97 'ARM 카메라 설정이 달라졌습니다' | 물체 위 도착 후에야 검사, 완전 일치 요구 | 시작 시 1회, frame_size만 비교 |
| B12 | gripper_aperture.py:55 '집게 개방 폭 부족' | 폭 79mm 이상 넓은 물품 계획 단계 거부 | 80% 폭 실측 또는 완화 |
| B13 | manual_worker.py:330-331 닫기 중 '다축 목표 도착 확인 시간 초과' | 집게가 20틱 못 가서 닿으면 접촉 판정 안 되고 15초 후 래치 | grip_contact 모드는 이동량 무관하게 정체=접촉 후보 |
| B14 | manual_worker.py:38-51 settled_at_target | 6축 0.25초 흔들림 3틱 이하 요구 | 집게 제외, 5~6틱 |
| B15 | grasp_flow.py:598 '개방 전 최신 ARM 외형 프레임 필요' | 1초 넘은 프레임이면 즉시 실패 | 2초 재시도 루프 |
| B16 | grasp_flow.py:257-258 '그리퍼 틱 범위가 개방 폭 실측 때와 다릅니다' | 완전 일치 요구 | 유지, 몇 틱 차이는 경고 |

임계값 중복: 어깨 처짐 허용 manual_worker.py:21 70틱 / following_compensation.py:9 60틱 / robot_actions.py:236 90틱 / manual_worker.py:312 90틱 → 70으로 통일 권장. 측면 이동 높이 하강 정지는 진행기록 '8mm'이나 실제 코드(gap_motion.py:23-30)는 expected_z 있으면 10mm.

## C. 설정 변경에 깨지는 캐시/키
| # | 위치 | 원인 | 권장 |
|---|---|---|---|
| C1 | gap_learning.py:10-18 context_key, :77 learn_offset | settings.json 전체(검출 주기·ROI·오버레이 토글 저장 시 바뀜), *tcp*.json(임시 파일), arm_fixed_finger.json, 관절 한계, 카메라 device_path를 해시 → 키 바뀌면 기울기 None(오프셋 0), 오프셋 학습 초기화, **누적 샘플 17개 삭제** | 키를 frame_size+SIGN+working_calibration+orientation 축으로 축소, 불일치 시 삭제 금지 |
| C2 | gap_learning.py:25-31 load_slope | 높이 차 25mm 초과 시 None | 스케일 값(최소한 부호) 반환 |
| C3 | grasp_flow.py:607-619 | band 재계산이 learned_slope 있을 때만 → 하한 6px vs 18.6px | 조건에서 기울기 제거 |
| C4 | gripper_aperture.py:38 | 개방 폭 표가 height_mm 5.0에 묶임 → 집기 높이 바꾸면 폭≥60mm 중단 | 높이 차는 경고만 |
| C5 | orientation_alignment.py:18 | working_calibration 바이트 해시 | 유지 |
| C6 | descent_shift.py:29 | EMA 0.5라 한 번 측정에 크게 흔들림 | 0.2 또는 중앙값 |
| C7 | grasp_flow.py:91 '임시 정합과 현재 모델/보관함 설정이 다릅니다' | robot_frame 재저장 시 | 유지 |

## D. 유지할 안전 정지
- 충돌: stage_motion.py:25(접근 판+10, 하강 목표−8mm), grasp_flow.py:659(측면 경로 판+15), gap_motion.py:30(측면 이동 중 하강), approach_path.py:69-71 safe(), grasp_flow.py:868(반환 판+5, 현재 미사용)
- 의도된 정지: grasp_flow.py:579(회전 후 손목 60틱), :778-779(하강 후 간격 −8px), gap_observation.py:107(재보정 2회 실패)
- 작업자: manual_worker.py:312 90틱(단, raise가 작업자 프로세스를 죽여 연결 끊김 → halt(True)+error로 바꾸면 재연결 불필요), :330-331 도착 시간초과, :282/grasp_flow.py:812 집게 55°C, :217 시작 자세 20틱, :218 범위 밖, :221 135°/s, :276-277 하트비트
- 범위·상태: robot_actions.py:55-62 validate_goal, :110-114 check, :51 fresh, grasp_flow.py:125
- 장면: grasp_flow.py:281 마커 8px 이동, :64 대상이 마커 영역 밖

## E. 없어진 동작을 고정하는 테스트
test_grasp_alignment.py 전체(A3/A4), test_grasp_contact.py 전체(A6), test_grasp_guard.py 전체(A7), test_reproduction.py 전체(A8), test_gap_revision.py:50-58(A9), test_rotation_polarity.py:7-17(A10), test_position_diagnostics.py:15(A11), test_grasp_flow.py:49-67(이름과 실제 동작 다름), test_aperture_partial.py:22-24(C4)·:18(B12), test_coarse_grasp.py:27-32·:61-63(B4), test_grasp_geometry.py(A20)

## 우선순위 Top 10
1. C1 context_key 축소 + 불일치 시 샘플 삭제 금지
2. B1 회전 전 경로 검사 → 판+20만 정지
3. B5 간격 상한을 정지 조건에서 제외
4. B3/B4 작은 이동 중단 제거·완화
5. B2 30mm 상승 실패해도 HOME 진행
6. B6 topview_both_sides_clear·loose_lab_match 정지 제외
7. B7/B9 기울기 임계 stage_tilt 통일 + 하강 IK 사전 확인
8. C4/C3 집기 높이 키·기울기 유무 band 분기 제거
9. A1~A8 일괄 삭제 + E 테스트 정리
10. B13 닫기 정체=접촉 후보, manual_worker 90틱 오류는 래치로

## 델타 (v0.2.38/v0.2.39 반영, 2차 점검 · Fable medium)
- 무효가 된 항목 없음. 감사 이후 4회 시도가 B3·B4·B6·C1 재현.
- **C1/C8 실제 발동 → v0.2.40에서 수정 완료**: 20:18:52 arm_fixed_finger.json 재등록 → context_key 변경 → 20:19/20:20 사전 오프셋 0(initial) → 손가락이 물체 안 −135/−117px → B3/B4로 중단. 학습 파일 백업 archives/*.20261111-202541.json. 키 축소 + 불일치 시 삭제 금지.
- 줄번호: grasp_flow.py 1-779 동일, 바닥 접촉 블록 780-806, 그 아래 +6. coarse_grasp.py object_alignment 91-114.
- A12 보강: WIDE_DEEPER_MM=0 무효, −7mm 주석·'TCP가 안 내려가면 접촉' 주석이 현재 동작과 다름.
- B6 수정 권장: edge_evidence가 raise하지 말고 association false로 반환 → object_alignment의 '회전 안 함' 경로가 살아남. 단 fixed_gap(coarse_grasp.py:25-30)이 근거 부족 선을 쓸지 별도 결정.
- B8: 잘린 물체는 경계선 기준 8°, edge_evidence 30° 관문 때문에 30° 넘게 틀어지면 회전 시도 없이 B6 중단.
- A22: coarse_grasp.py:102 association 조건과 '회전 안 함' 대체(:111)는 현재 도달 불가(잘린 형상은 반드시 edge_evidence 통과 또는 raise). B6 고치면 살아남.
- A23: extent_penalty(outline_refinement.py:62), aspect_ratio_penalty(:86,:90, object_reference.py:184), arm_camera_orientation_candidate·opening_axis_deg(object_reference.py:19-21) 읽는 곳 0건.
- B17: 회전 루프 중 기준이 상자 축(12°)↔경계선(8°)으로 바뀌면 '개선되지 않음' 오판 가능(grasp_flow.py:562-585). 같은 경계 각도에 임계 3개(8°, 15° gap_observation.py:56, 30° partial_boundary.py:52).
- B18: 바닥 접촉 데드존 오판 — 팔이 전혀 안 움직여도 lag 1,2,3,4mm로 쌓여 4단계에 '접촉'. 실제로 1~2mm 이상 내려간 적이 있을 때만 인정 권장.
- B19: 바닥 루프 중 joints_for IK 실패가 전체 중단(:795,:804) → 루프 안에서 잡아 '최대 깊이'로 처리 권장.
- B20: 루프 절대 하한 없음, 최악 목표−20mm 명령. 미확인 종료 시 +0.5mm 복귀 없음 → 절대 하한 + 실제 높이 복귀 권장.
- B21: 시작이 접촉보다 8mm 넘게 위면 12단계 안에 감지 불가.
- B22(추정): 실제 높이 기준 명령으로 처짐이 한 번에 풀릴 수 있음 — steps[0].lag_mm 확인 필요.
- B23: −8px 검사·감소량 학습이 추가 하강 전에만 → 바닥 루프 뒤 재측정 권장.
- 테스트 없음: v0.2.39 잘린 형상 분기, 바닥 접촉 루프.
- 우선순위: C1(완료) → B6 → B3/B4 → B18/B19 → 기존 순서(B1,B5,B2,B7/B9,C4/C3,A 일괄,B13) → B20,B21,B23,B17.

## Codex 검토 판정 (Fable medium, v0.2.40 기준, 읽기 전용)

- C1: 부분동의. v0.2.40 함정 — '반대' raise가 session['slopes'] 기록 전(coarse_grasp.py:80-83)이라 부호가 실제로 바뀌면 틀린 기울기가 영구히 재사용됨. 수정안: hard_key(SIGN·모델·opening_axis_local·roll_sign·reference 값·frame_size, 값 기반) 불일치 시 '재확인 대기'(크기·부호는 쓰되 첫 간격 ≥ −30px 또는 1.5mm 이상 이동의 기울기 부호 일치로 확인), '반대' 중단 시 항상 suspect 표시, 2회 연속이면 폐기. 샘플 보존 유지.
- B6/A22: 동의. edge_evidence는 proof 반환, usable_for_rotation(직선성+연결, 각도 무관) / usable_for_gap(+각도 ≤15°) 분리. fixed_gap은 usable_for_gap 아니면 재측정 → 시야 확보 → 하강 전 정지.
- 바닥 접촉: 동의. 기준을 '접촉 감지'→'충분히 낮은가'로. 명령 하한 max(grasp_z−12, plane−8), 피드백 < plane−6 즉시 종료, 2mm 고정 사다리, low_enough = 피드백 ≤ plane+3, 종료 상태 contact/floor_limit/ik_limit/stalled_high, stalled_high면 +10mm 후 plane+1까지 1회 연속 이동, lag>1mm면 항상 피드백+0.5mm로 해제, 루프 뒤 fixed_gap 재검사(−8px 미만이면 닫지 않고 상승·정지). 2단계(선택): 작업자 부하(주소 60) 읽기.
- B17: 동의(임계 통합 권고 철회). 같은 axis_source끼리만 개선 비교.
- 삭제: simple_mode=False는 실행 가능(server.py:227, prototype.html), 오늘 오전 실제 사용 → A1/A3/A19는 사용자 결정. A4~A7, A9~A18, A21은 정리 가능.
- B5: Codex 맞음(권고 철회). 상한 유지, 입력을 80%/100% 실측 개방 폭으로 교정.
- B12: Codex 맞음. 80%/100% 실측 후 가장 작은 적합 행 선택.
- C4: 부분동의. 넓은 물품은 판 높이 실측표, 좁은 물품은 높이 차 3mm까지 재사용.
- B2: 부분동의. 30→20→10mm 단계 상승, 관절 공간 상승(FK z 단조 증가 ≥10mm) 후에도 10mm 미만이면 HOME 거부 유지.
- 합의 순서: ① 바닥 묶음(B18/19/20/23) ② B6/A22 ③ C1 보완 ④ B3/B4 ⑤ B17 ⑥ B5/B12/C4(실측 후) ⑦ B1/B7/B9 기울기 통일 ⑧ B2 ⑨ A 정리 ⑩ (선택) 부하 측정·90틱 래치.
- 실측 필요: 80%/100% 개방 폭(사용자), plane+3/plane−8 창은 넓은 물품 2~3회 floor_contact.steps로 조정.
