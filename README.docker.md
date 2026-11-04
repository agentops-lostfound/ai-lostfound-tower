# Docker 개발 환경 (React + FastAPI + PostgreSQL)

기존 팀 공용 `docker-compose.yml`과 DB 컨테이너를 건드리지 않도록 신규 애플리케이션은 `docker-compose.app.yml` 및 별도 named volume으로 분리했습니다.

## 실행
1. Docker Engine/Desktop 및 Docker Compose v2 설치
2. 환경 파일 복사: `cp .env.app.example .env`
3. `.env`에서 POSTGRES_PASSWORD를 긴 임의 값으로 변경
4. 시작: `docker compose --env-file .env -f docker-compose.app.yml up --build -d`
5. 접속: `http://localhost:8080`
   - 등록기계 화면: `http://localhost:8080/?machine=KIOSK-A`
   - FastAPI 문서: `http://localhost:8080/api/docs`
   - 상태: `http://localhost:8080/api/health`

## 구현 API
- GET /places?machine_id=KIOSK-A
- POST /items: machine_id, place_text 필수; place_id, finder, photo 선택
- GET /items: 개발 확인용 최근 접수 목록
- POST /claims: 접수 번호 기반 반환 신청
- GET /claims: 개발 확인용 신청 목록

사진은 JPEG/PNG/WEBP data URL 최대 5MB를 검증해 별도 Docker volume에 저장합니다. DB에는 사진 파일명만 저장합니다. 프런트엔드는 /api 경로를 Nginx가 FastAPI로 프록시합니다.

## 기존 데이터베이스와의 관계
기존 루트 `docker-compose.yml`은 팀 공용 PostgreSQL 16 + pgvector 개발 환경입니다. 이 앱은 별도의 PostgreSQL 16 컨테이너와 데이터 볼륨을 사용합니다. 기존 DB에 연결하려면 compose의 app-db 서비스를 제거하고 DATABASE_URL을 기존 DB의 네트워크 주소로 변경하는 작업이 별도로 필요합니다.

## 현재 범위 / 운영 전 필수
개발 MVP입니다. 직원 인증/권한, 감사 로그, 분실물 후보 매칭 및 Qwen 이미지 분석, 본인 확인/승인/인계 예약, 자동 개인정보 파기, 백업/복구, TLS, rate limiting, Alembic migration, 테스트는 아직 구현되지 않았습니다. `GET /items`와 `GET /claims`는 개발 검증용이므로 운영 공개 전에 인증·권한을 반드시 추가해야 합니다. 개인정보/사진은 실제 개인정보 처리방침과 보안 정책을 확정한 후 운영 데이터로 사용하세요.
