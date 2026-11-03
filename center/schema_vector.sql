-- 이미지 비슷함 검색(pgvector) — 임베딩 모델이 정해진 뒤 실행(LF-6, 모델 TBD: CLIP 계열 등)
-- 필요: PostgreSQL에 pgvector 확장 설치. 차원(512)은 모델에 맞춰 바꾼다
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE item ADD COLUMN IF NOT EXISTS embedding vector(512);
-- 데이터가 수백 건 이상이 되면 색인 추가(그 전에는 전체 비교로 충분)
-- CREATE INDEX IF NOT EXISTS item_embedding_idx ON item USING hnsw (embedding vector_cosine_ops);
