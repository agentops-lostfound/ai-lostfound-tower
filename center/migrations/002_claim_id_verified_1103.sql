-- 002 (11/3) 웹 신분증 OCR 인증 결과를 찾기 요청에 저장 — 웹·관제탑 2단계 연결(agents/claims.py)
ALTER TABLE claim ADD COLUMN IF NOT EXISTS id_verified BOOLEAN NOT NULL DEFAULT FALSE;
