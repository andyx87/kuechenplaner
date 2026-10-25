-- Tarif-Modell v4: Umstellung auf Abo-/Kontingent-Modell (kein €-Guthaben, kein PAYG).
--
-- Zielmodell:
--   Gratis   : Nicht-KI frei · 10 KI-Text-Aktionen + 3 Bilder pro Monat · 14-Tage-Trial
--   Topfplan-Abo: 9,99 €/Mo · alle KI · Text unbegrenzt · 50 Bilder pro Monat
--   Foto-Pack: 12,99 € einmalig · 75 Bild-Credits  (kein Tarif, nur bild_credits-Zukauf)
--   Nur "schnell"-Bilder. Bild-Credits (account.bild_credits) decken Bilder über dem Limit.
--
-- STUFE 1 (diese Datei): rein ADDITIV. Neue Spalten + Tarif-Definitionen. Ändert noch KEIN
-- Verhalten – die alten Tarife/Guthaben-Logik laufen unverändert weiter, bis Stufe 2 die
-- neue Gating-Logik aktiviert. Idempotent ausführbar. Muss vom Tabellen-Eigentümer laufen.

SET search_path TO koch, public;

-- 1) Monats-Kontingente je Tarif (NULL = unbegrenzt)
ALTER TABLE koch.tarif ADD COLUMN IF NOT EXISTS monats_ki_limit   integer;  -- KI-Text-Aktionen/Monat
ALTER TABLE koch.tarif ADD COLUMN IF NOT EXISTS monats_bild_limit integer;  -- Bilder/Monat

-- 2) Neue Tarife 'gratis' und 'abo' (bestehende basis/plus/max/payg bleiben vorerst unberührt;
--    Deaktivierung/Umzug der Konten erfolgt in einer späteren Stufe).
INSERT INTO koch.tarif (code, name, ist_payg, preis_cents, markup_prozent,
                        monats_ki_limit, monats_bild_limit, sortierung, aktiv) VALUES
  ('gratis', 'Gratis', false,   0, 0,   10,    3, 0, true),
  ('abo',    'Topfplan',  false, 999, 0, NULL,   50, 1, true)
ON CONFLICT (code) DO UPDATE SET
  name              = EXCLUDED.name,
  ist_payg          = EXCLUDED.ist_payg,
  preis_cents       = EXCLUDED.preis_cents,
  monats_ki_limit   = EXCLUDED.monats_ki_limit,
  monats_bild_limit = EXCLUDED.monats_bild_limit,
  sortierung        = EXCLUDED.sortierung,
  aktiv             = EXCLUDED.aktiv;

-- 3) Konto: Bild-Credit-Vorrat + Stripe-Abo-Felder + Trial-Ende
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS bild_credits           integer NOT NULL DEFAULT 0;
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS stripe_customer_id     text;
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS stripe_subscription_id text;
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS trial_bis              date;

-- Verifikation (informativ):
--   SELECT code, preis_cents, monats_ki_limit, monats_bild_limit, aktiv FROM koch.tarif ORDER BY sortierung;
--   \d koch.account   -- bild_credits, stripe_customer_id, stripe_subscription_id, trial_bis vorhanden
