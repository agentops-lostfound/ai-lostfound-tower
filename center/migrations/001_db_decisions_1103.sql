-- 001 (11/3) DB 확정 사항을 이미 만든 DB 에 반영 — docs/design/database.md 6장
-- 새로 만든 DB(schema.sql)에는 이미 들어 있으므로 없을 때만 추가한다(몇 번 실행해도 같음)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'item_id_format') THEN
        ALTER TABLE item ADD CONSTRAINT item_id_format
            CHECK (item_id ~ '^[A-Z]-([0-9]{8}-[0-9]{4}|W[0-9]{2})$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'claim_id_format') THEN
        ALTER TABLE claim ADD CONSTRAINT claim_id_format
            CHECK (claim_id ~ '^C-[0-9]{8}-[0-9]{4}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'claim_description_keys') THEN
        ALTER TABLE claim ADD CONSTRAINT claim_description_keys
            CHECK ((description - ARRAY['category', 'color', 'shape', 'mark', 'visible_text', 'material']) = '{}'::jsonb);
    END IF;
END $$;
