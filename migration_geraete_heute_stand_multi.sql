SET search_path TO koch, public;

-- geraete_heute_stand war ein Single-Tenant-Singleton (CHECK id=1, PK id) -> nur EIN
-- Konto konnte eine Zeile haben. Neue Konten kollidierten mit der fremden id=1-Zeile
-- (RLS-Verletzung). Umstellen auf EINE Zeile pro Konto (Schlüssel = account_id).
ALTER TABLE geraete_heute_stand DROP CONSTRAINT IF EXISTS geraete_heute_stand_einzeilig;
ALTER TABLE geraete_heute_stand DROP CONSTRAINT IF EXISTS geraete_heute_stand_pkey;
CREATE UNIQUE INDEX IF NOT EXISTS geraete_heute_stand_acc_key ON geraete_heute_stand (account_id);
