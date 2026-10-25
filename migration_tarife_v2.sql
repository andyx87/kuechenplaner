-- Tarif-Modell v2: Aufschlag (Markup) PRO STUFE statt global; Nutzungsfenster
-- Tag + Woche (statt Stunde/Monat). Volumen in marked-up Cent.
--   PAYG     : keine Grundgebühr, Aufschlag 125 % (Token + Bilder)
--   Basis    : 4,99 €/Mon., Aufschlag 100 %, Woche 1,25 € / Tag 0,60 €
--   Plus     : 7,99 €/Mon., Aufschlag  85 %, Woche 2,00 € / Tag 1,00 €
--   Max      :14,99 €/Mon., Aufschlag  65 %, Woche 3,75 € / Tag 1,80 €
-- Abo-Überlauf (Guthaben nach Volumen): vergünstigter Aufschlag 65 %.
SET search_path TO koch, public;

ALTER TABLE tarif ADD COLUMN IF NOT EXISTS markup_prozent numeric(6,2) NOT NULL DEFAULT 0;
ALTER TABLE tarif ADD COLUMN IF NOT EXISTS tages_limit_cents integer;
ALTER TABLE plattform_einstellung ADD COLUMN IF NOT EXISTS overage_markup_prozent numeric(6,2) NOT NULL DEFAULT 65;

UPDATE tarif SET preis_cents = 499,  markup_prozent = 100, tages_limit_cents = 60,   wochen_limit_cents = 125  WHERE code = 'basis';
UPDATE tarif SET preis_cents = 799,  markup_prozent = 85,  tages_limit_cents = 100,  wochen_limit_cents = 200  WHERE code = 'plus';
UPDATE tarif SET preis_cents = 1499, markup_prozent = 65,  tages_limit_cents = 180,  wochen_limit_cents = 375  WHERE code = 'max';
UPDATE tarif SET preis_cents = 0,    markup_prozent = 125, tages_limit_cents = NULL, wochen_limit_cents = NULL WHERE code = 'payg';
