-- ============================================================
-- Koch-Assistent – Postgres-Schema
-- Empfehlung: eigenes Schema 'koch' in einer vorhandenen Postgres-Instanz
-- ============================================================

CREATE SCHEMA IF NOT EXISTS koch;
SET search_path TO koch, public;

-- ---------- Stammdaten ----------

-- Kanonische Zutatenliste: Rezepte UND Vorrat referenzieren dieselbe Zutat,
-- damit der Vorratsabgleich und die Reduktion nach dem Kochen eindeutig funktionieren.
CREATE TABLE zutaten (
    id                SERIAL PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    kategorie         TEXT,                 -- z.B. Gemüse, Milchprodukt, Gewürz
    standard_einheit  TEXT,                 -- g, ml, Stück
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Küchengeräte (Geräte-Datenbank)
CREATE TABLE geraete (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    typ         TEXT,                          -- Backofen, Mixer, Sous-vide ...
    notizen     TEXT,
    vorhanden   BOOLEAN NOT NULL DEFAULT true, -- gehört grundsätzlich zum Haushalt
    standard    BOOLEAN NOT NULL DEFAULT true, -- Alltagsgerät (true) vs. situativ wie Grill (false)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Rezepte ----------

CREATE TABLE rezepte (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    beschreibung  TEXT,
    anleitung     TEXT,                        -- Schritte als Markdown
    portionen     INT  NOT NULL DEFAULT 2,
    dauer_minuten INT,
    quelle        TEXT,                        -- URL oder Buch
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rezept ↔ Zutat (mit Mengen)
CREATE TABLE rezept_zutaten (
    id         SERIAL PRIMARY KEY,
    rezept_id  INT NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
    zutat_id   INT NOT NULL REFERENCES zutaten(id) ON DELETE RESTRICT,
    menge      NUMERIC(10,2),
    einheit    TEXT,
    optional   BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (rezept_id, zutat_id)
);

-- Rezept ↔ Gerät (welche Geräte braucht das Rezept)
CREATE TABLE rezept_geraete (
    rezept_id  INT NOT NULL REFERENCES rezepte(id) ON DELETE CASCADE,
    geraet_id  INT NOT NULL REFERENCES geraete(id) ON DELETE CASCADE,
    pflicht    BOOLEAN NOT NULL DEFAULT true,  -- erforderlich vs. nur hilfreich
    PRIMARY KEY (rezept_id, geraet_id)
);

-- ---------- Vorrat ----------

-- Mehrere Einträge pro Zutat sind erlaubt (Chargen mit unterschiedlichem Ablaufdatum).
-- Reduktion nach dem Kochen: FIFO nach ablaufdatum – die Logik dafür liegt im MCP-Tool.
CREATE TABLE vorrat (
    id              SERIAL PRIMARY KEY,
    zutat_id        INT NOT NULL REFERENCES zutaten(id) ON DELETE RESTRICT,
    menge           NUMERIC(10,2) NOT NULL,
    einheit         TEXT NOT NULL,
    ablaufdatum     DATE,
    ort             TEXT,                       -- Kühlschrank, Speisekammer, Tiefkühler
    hinzugefuegt_am TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Tagesauswahl der Geräte ----------

-- Welche Geräte will sie HEUTE nutzen. Die Web-App leert die Tabelle und schreibt sie neu.
-- Vorhandensein einer Zeile = ausgewählt. So liest die KI die Auswahl ohne Parameter.
CREATE TABLE geraete_heute (
    geraet_id   INT PRIMARY KEY REFERENCES geraete(id) ON DELETE CASCADE,
    gewaehlt_am TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Merkt sich, fuer welchen Tag die aktuelle Auswahl gilt. Bei Tageswechsel
-- setzt die App die Auswahl auf die Alltagsgeraete (standard = true) zurueck.
CREATE TABLE geraete_heute_stand (
    id          INT PRIMARY KEY DEFAULT 1,
    stand_datum DATE NOT NULL,
    CONSTRAINT geraete_heute_stand_einzeilig CHECK (id = 1)
);

-- ---------- Indizes ----------
CREATE INDEX idx_rezept_zutaten_zutat ON rezept_zutaten(zutat_id);
CREATE INDEX idx_rezept_geraete_geraet ON rezept_geraete(geraet_id);
CREATE INDEX idx_vorrat_zutat          ON vorrat(zutat_id);
CREATE INDEX idx_vorrat_ablauf         ON vorrat(ablaufdatum);

-- ---------- View: Vorrat aggregiert pro Zutat ----------
-- Für Vorratsanzeige und Reduktionslogik.
CREATE VIEW v_vorrat_aggregiert AS
SELECT z.id                AS zutat_id,
       z.name              AS zutat,
       v.einheit,
       SUM(v.menge)        AS menge_gesamt,
       MIN(v.ablaufdatum)  AS naechstes_ablaufdatum
FROM vorrat v
JOIN zutaten z ON z.id = v.zutat_id
GROUP BY z.id, z.name, v.einheit;

-- ---------- View: Rezept-Machbarkeit ----------
-- Pro Rezept: wie viele Pflichtzutaten sind im Vorrat vorhanden.
-- (Mengenabgleich über Einheiten hinweg ist eine spätere Ausbaustufe –
--  hier wird nur geprüft, ob die Zutat überhaupt vorhanden ist.)
CREATE VIEW v_rezept_machbarkeit AS
SELECT r.id   AS rezept_id,
       r.name AS rezept,
       COUNT(*) FILTER (WHERE NOT rz.optional)                             AS pflicht_zutaten,
       COUNT(*) FILTER (WHERE NOT rz.optional AND vz.zutat_id IS NOT NULL) AS davon_vorhanden,
       COUNT(*) FILTER (WHERE NOT rz.optional AND vz.zutat_id IS NULL)     AS fehlend
FROM rezepte r
JOIN rezept_zutaten rz ON rz.rezept_id = r.id
LEFT JOIN (SELECT DISTINCT zutat_id FROM vorrat) vz ON vz.zutat_id = rz.zutat_id
GROUP BY r.id, r.name;
