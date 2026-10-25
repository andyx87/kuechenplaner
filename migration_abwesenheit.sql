-- Regelmäßige Abwesenheiten (z.B. Wechselmodell-Kinder)
CREATE TABLE IF NOT EXISTS person_abwesenheit_regel (
  id             SERIAL PRIMARY KEY,
  person_id      INT  NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  woche_typ      TEXT NOT NULL DEFAULT 'alle'
                   CHECK (woche_typ IN ('alle', 'gerade', 'ungerade')),
  von_wochentag  INT  NOT NULL CHECK (von_wochentag BETWEEN 1 AND 7), -- ISO: 1=Mo…7=So
  von_mahlzeit   TEXT NOT NULL,  -- erster fehlender Slot (Frühstück/Mittag/Abendessen/…)
  bis_wochentag  INT  NOT NULL CHECK (bis_wochentag BETWEEN 1 AND 7), -- Rückkehr-Wochentag
  bis_mahlzeit   TEXT NOT NULL,  -- erster wieder vorhandener Slot
  folgewoche     BOOL NOT NULL DEFAULT FALSE, -- TRUE wenn Rückkehr in der Folgewoche
  notiz          TEXT
);

-- Hinweis: Konkrete Abwesenheitsregeln (z.B. Wechselmodell-Kinder) werden pro
-- Haushalt ueber die App/Tools angelegt, NICHT hier hartcodiert.
