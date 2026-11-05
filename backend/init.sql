CREATE TABLE IF NOT EXISTS places (
  id SERIAL PRIMARY KEY,
  machine_id VARCHAR(40) NOT NULL,
  label VARCHAR(128) NOT NULL,
  usage_count INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE(machine_id, label)
);
INSERT INTO places (machine_id, label, usage_count) VALUES
 ('KIOSK-A','해운대역 개찰구 주변',100),('KIOSK-A','해운대역 승강장',90),
 ('KIOSK-A','해운대역 대합실 및 의자',80),('KIOSK-A','해운대역 화장실',70),
 ('KIOSK-A','해운대역 출입구 및 계단',60),
 ('KIOSK-B','중앙역 개찰구 주변',100),('KIOSK-B','중앙역 승강장',90),
 ('KIOSK-B','중앙역 대합실',80),('KIOSK-B','중앙역 화장실',70),
 ('KIOSK-B','중앙역 출입구',60)
ON CONFLICT (machine_id,label) DO NOTHING;
CREATE TABLE IF NOT EXISTS items (
 id BIGSERIAL PRIMARY KEY, item_id VARCHAR(40) NOT NULL UNIQUE,
 machine_id VARCHAR(40) NOT NULL, place_id INTEGER REFERENCES places(id),
 place_text VARCHAR(128) NOT NULL, finder_name VARCHAR(80), finder_phone VARCHAR(30),
 photo_path TEXT, status VARCHAR(40) NOT NULL DEFAULT '등록기계 보관',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS claims (
 id BIGSERIAL PRIMARY KEY, claim_id VARCHAR(40) NOT NULL UNIQUE,
 item_id VARCHAR(40) NOT NULL REFERENCES items(item_id),
 claimant_name VARCHAR(80) NOT NULL, claimant_phone VARCHAR(30) NOT NULL,
 description TEXT, status VARCHAR(40) NOT NULL DEFAULT '접수',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
