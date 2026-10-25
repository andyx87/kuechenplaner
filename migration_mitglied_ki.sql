SET search_path TO koch, public;

-- Pro Haushaltsmitglied steuerbar, ob es KI-Funktionen nutzen darf (Owner entscheidet).
-- Default true = darf. Owner/super_admin sind ohnehin immer erlaubt (siehe userauth.darf_ki).
ALTER TABLE account_mitglied ADD COLUMN IF NOT EXISTS ki_erlaubt boolean NOT NULL DEFAULT true;
