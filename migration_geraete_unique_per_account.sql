-- Multi-Tenant-Fix: Geräte-Name war GLOBAL unique → Konten konnten Namen blockieren,
-- die ein anderes Konto schon nutzt (z.B. 'Backofen'/'Herd'). Jetzt unique PRO Konto.
SET search_path TO koch, public;
ALTER TABLE koch.geraete DROP CONSTRAINT IF EXISTS geraete_name_key;
ALTER TABLE koch.geraete ADD CONSTRAINT geraete_account_name_key UNIQUE (account_id, name);
