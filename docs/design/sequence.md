# ④ 시퀀스 — 반환 흐름(UC-1) 호출 순서

> participant 이름은 components.md, 화살표 라벨은 interfaces.md 의 함수 이름 그대로. 코드: agents/supervisor.py

## 정상 흐름 + 웹·방문 관문
```mermaid
sequenceDiagram
  participant Sup as 반환 흐름
  participant BE as 부품 묶음
  participant Rev as LLM 검토
  participant Rep as 관제 알림
  Note over Sup: web_gate — 동의·본인인증·확인 질문(코드 관문)
  alt 동의 거부 / 인증 실패
    Sup->>Sup: rejected
  else 확인 질문 오답
    Sup->>Rep: alert(case, 확인 질문 미통과)
  else 통과
    Sup->>BE: db_get_item(item_id)
    BE-->>Sup: dict | None
    alt None
      Sup->>Rep: alert(case, 물건 기록 없음)
    else 기록 있음
      opt LLM 검토 켬
        Sup->>Rev: reviewer(summary)
        Rev-->>Sup: ("ok" | "hold", note)
      end
      Sup->>BE: db_set_status(item_id, 승인·수령 예약)
      Sup->>Rep: progress(case, 메인 AI 승인)
    end
  end
  Note over Sup: visit_gate — 신분증 대조·안쪽 특징·직원 확인
  alt 불일치
    Sup->>BE: db_set_status(item_id, 반환 보류)
    Sup->>Rep: alert(case, 불일치)
  else 직원 확인 완료
    Sup->>Rep: progress(case, 직원 확인 완료)
  end
```

## 로봇 반환 (locate → approach → grasp → deliver)
```mermaid
sequenceDiagram
  participant Sup as 반환 흐름
  participant BE as 부품 묶음
  participant Rep as 관제 알림
  Sup->>BE: vision_topview()
  BE-->>Sup: list[detection]
  alt 0개
    Sup->>Rep: alert(case, 물건 못 찾음)
  else 1개 이상
    Sup->>BE: match_item(features, detections)
    BE-->>Sup: {status, index, score, margin}
    alt uncertain / none
      Sup->>Rep: alert(case, 매칭 불확실 — 직원 확인)
    else matched
      opt 작업대 mm 좌표 없음(카메라 보정 안 됨, 11/4)
        Sup->>Rep: alert(case, 작업대 좌표 없음 — 로봇 안 움직임)
      end
      Sup->>BE: db_set_status(item_id, 반환 중)
      BE-->>Sup: {ok, reason}
      alt 상태 기록 실패
        Sup->>Rep: alert(case, 상태 기록 실패 — 로봇 안 움직임)
      else 기록 성공
      Sup->>BE: robot_approach(center_mm, center_px)
      BE-->>Sup: {ok, reason}
      alt 접근 실패
        Sup->>BE: robot_stop()
        Sup->>Rep: alert(case, 사전 접근 실패)
      else 접근 성공
        loop 최대 MAX_GRASP_ATTEMPTS(2)번
          Sup->>BE: robot_grasp()
          opt 집기 성공일 때만
            Sup->>BE: robot_verify_grasp()
          end
        end
        alt 2번 모두 실패
          Sup->>BE: robot_stop()
          Sup->>Rep: alert(case, 집기 실패 — 직원 호출)
        else 집기 성공
          Sup->>BE: robot_deliver()
          BE-->>Sup: {ok, reason}
          alt 전달 실패
            Sup->>BE: robot_stop()
            Sup->>Rep: alert(case, 바구니 전달 실패)
          else 전달 성공
            Sup->>Rep: progress(case, 바구니 전달 완료)
            Sup->>BE: db_set_status(item_id, 인계 대기)
            opt 기록 실패
              Sup->>Rep: alert(case, 바구니 전달 완료 · 상태 기록 실패)
            end
          end
        end
      end
      end
    end
  end
```
- 그림은 코드가 하는 일 그대로다(11/3 review 1·2·7 반영). `robot_stop()` 이 실패하면 알림 문구에 "정지 실패 — 직원 즉시 호출"이 붙는다
- 승인 단계의 `db_set_status(승인·수령 예약)` 도 실패하면 직원 확인으로 끝난다
