-- LF-9. Apply explicitly using tools/db_migrate.py. No production execution by the author.
ALTER TABLE collection ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS collection_request_unique ON collection(request_id) WHERE request_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS collection_alert (
    collection_id INTEGER NOT NULL REFERENCES collection(collection_id),
    item_id VARCHAR(32) NOT NULL REFERENCES item(item_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY(collection_id,item_id)
);
-- Admin creates a dedicated LOGIN and grants this NOLOGIN role. Do not reuse an owner login.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='lf_stats_reader') THEN
        CREATE ROLE lf_stats_reader NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO lf_stats_reader;
GRANT SELECT ON stats_item, stats_return TO lf_stats_reader;
REVOKE ALL ON item, claim, finder_contact, quiz_attempt, reservation FROM lf_stats_reader;
