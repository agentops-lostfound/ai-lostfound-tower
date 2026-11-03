-- [선택, MVP 에서는 실행하지 않음 — 11/3 결정] 이미지 비슷함 검색(pgvector)
-- MVP(지갑 1종)는 특징 JSON 매칭으로 충분. 품목이 늘어 필요해지면 비전 담당과 모델(CLIP 계열 등)을 정한 뒤 실행
-- 필요: PostgreSQL에 pgvector 확장 설치. 차원(512)은 모델에 맞춰 바꾼다
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE item ADD COLUMN IF NOT EXISTS embedding vector(512);
-- 데이터가 수백 건 이상이 되면 색인 추가(그 전에는 전체 비교로 충분)
-- CREATE INDEX IF NOT EXISTS item_embedding_idx ON item USING hnsw (embedding vector_cosine_ops);
