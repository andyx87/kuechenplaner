-- Tarif-Modell v3: Abo = monatlich berechnete Freischaltung (rollend ab Kaufdatum),
-- Zugang UNABHÄNGIG vom Guthaben. Guthaben dient nur noch für Extra-Volumen (Overage)
-- bzw. PAYG. Kündigung & Downgrade wirken zum Periodenende; Upgrade sofort (anteilig).
-- Tabellen schema-qualifiziert (koch.*), damit der Import nicht von search_path abhängt.
SET search_path TO koch, public;

-- Bezahlte Periode (rollend): NULL = kein aktives Abo (PAYG).
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS abo_bezahlt_bis date;
-- Kündigung vorgemerkt: läuft bis abo_bezahlt_bis, fällt danach auf PAYG zurück.
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS abo_gekuendigt boolean NOT NULL DEFAULT false;
-- Geplanter Tarifwechsel zum Periodenende (Downgrade bzw. 'payg' bei Kündigung).
ALTER TABLE koch.account ADD COLUMN IF NOT EXISTS abo_naechster_tarif text REFERENCES koch.tarif(code);

-- Bestandskonten mit aktivem Abo-Tarif eine laufende Periode geben, damit der Zugang
-- nach dem Deploy nicht sofort abläuft (eine Monatsfreischaltung ab heute).
UPDATE koch.account
   SET abo_bezahlt_bis = (CURRENT_DATE + INTERVAL '1 month')::date
 WHERE tarif_code <> 'payg' AND abo_bezahlt_bis IS NULL;
