--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: koch; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA koch;

-- E-Mail-Spalten sind case-insensitiv (citext).
CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA koch;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.account (
    id integer NOT NULL,
    name text NOT NULL,
    einstellungen jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    zuletzt_aktiv timestamp with time zone
);


--
-- Name: account_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.account_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: account_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.account_id_seq OWNED BY koch.account.id;


--
-- Name: account_mitglied; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.account_mitglied (
    account_id integer NOT NULL,
    user_id integer NOT NULL,
    rolle text DEFAULT 'member'::text NOT NULL,
    beigetreten_am timestamp with time zone DEFAULT now() NOT NULL,
    ki_erlaubt boolean DEFAULT true NOT NULL
);


--
-- Name: angebote; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.angebote (
    id integer NOT NULL,
    haendler text,
    gueltig_von date NOT NULL,
    gueltig_bis date NOT NULL,
    name text NOT NULL,
    beschreibung text,
    preis_normal numeric(6,2),
    preis_angebot numeric(6,2),
    einheit text,
    kategorie text,
    quelle_datei text,
    importiert_am timestamp with time zone DEFAULT now(),
    master_zutat_id integer,
    art text,
    bild text,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.angebote FORCE ROW LEVEL SECURITY;


--
-- Name: angebote_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.angebote_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: angebote_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.angebote_id_seq OWNED BY koch.angebote.id;


--
-- Name: app_session; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.app_session (
    id integer NOT NULL,
    user_id integer NOT NULL,
    account_id integer,
    token_hash text NOT NULL,
    ablauf timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: app_session_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.app_session_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: app_session_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.app_session_id_seq OWNED BY koch.app_session.id;


--
-- Name: app_user; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.app_user (
    id integer NOT NULL,
    email koch.citext NOT NULL,
    password_hash text,
    name text DEFAULT ''::text NOT NULL,
    plattform_rolle text,
    aktiv boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    darf_angebote_upload boolean DEFAULT true NOT NULL
);


--
-- Name: app_user_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.app_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: app_user_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.app_user_id_seq OWNED BY koch.app_user.id;


--
-- Name: bewertung; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.bewertung (
    id integer NOT NULL,
    rezept_id integer NOT NULL,
    sterne integer NOT NULL,
    kommentar text,
    bewertet_am timestamp with time zone DEFAULT now() NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer,
    CONSTRAINT bewertung_sterne_check CHECK (((sterne >= 1) AND (sterne <= 5)))
);

ALTER TABLE ONLY koch.bewertung FORCE ROW LEVEL SECURITY;


--
-- Name: bewertung_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.bewertung_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bewertung_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.bewertung_id_seq OWNED BY koch.bewertung.id;


--
-- Name: bugreport; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.bugreport (
    id integer NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer,
    user_id integer,
    seite text,
    text text NOT NULL,
    status text DEFAULT 'offen'::text NOT NULL,
    user_agent text,
    erstellt_am timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY koch.bugreport FORCE ROW LEVEL SECURITY;


--
-- Name: bugreport_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.bugreport_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bugreport_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.bugreport_id_seq OWNED BY koch.bugreport.id;


--
-- Name: einkauf_extra; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.einkauf_extra (
    id integer NOT NULL,
    name text NOT NULL,
    menge numeric,
    einheit text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer,
    rezept_id integer
);

ALTER TABLE ONLY koch.einkauf_extra FORCE ROW LEVEL SECURITY;


--
-- Name: einkauf_extra_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.einkauf_extra_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: einkauf_extra_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.einkauf_extra_id_seq OWNED BY koch.einkauf_extra.id;


--
-- Name: einkaufstag; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.einkaufstag (
    id integer NOT NULL,
    datum date NOT NULL,
    haendler text,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.einkaufstag FORCE ROW LEVEL SECURITY;


--
-- Name: einkaufstag_haendler; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.einkaufstag_haendler (
    id integer NOT NULL,
    datum date NOT NULL,
    haendler text NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.einkaufstag_haendler FORCE ROW LEVEL SECURITY;


--
-- Name: einkaufstag_haendler_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.einkaufstag_haendler_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: einkaufstag_haendler_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.einkaufstag_haendler_id_seq OWNED BY koch.einkaufstag_haendler.id;


--
-- Name: einkaufstag_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.einkaufstag_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: einkaufstag_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.einkaufstag_id_seq OWNED BY koch.einkaufstag.id;


--
-- Name: einladung; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.einladung (
    id bigint NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer NOT NULL,
    email koch.citext,
    token text NOT NULL,
    rolle text DEFAULT 'member'::text NOT NULL,
    status text DEFAULT 'offen'::text NOT NULL,
    eingeladen_von integer,
    erstellt timestamp with time zone DEFAULT now() NOT NULL,
    eingeloest_am timestamp with time zone
);

ALTER TABLE ONLY koch.einladung FORCE ROW LEVEL SECURITY;


--
-- Name: einladung_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.einladung_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: einladung_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.einladung_id_seq OWNED BY koch.einladung.id;


--
-- Name: essensplan; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.essensplan (
    id integer NOT NULL,
    datum date NOT NULL,
    mahlzeit text DEFAULT 'Abendessen'::text NOT NULL,
    rezept_id integer,
    notiz text,
    person_ids integer[] DEFAULT '{}'::integer[] NOT NULL,
    portionen numeric(5,2),
    erstellt_am timestamp with time zone DEFAULT now() NOT NULL,
    gaeste integer DEFAULT 0 NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer,
    gekocht boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY koch.essensplan FORCE ROW LEVEL SECURITY;


--
-- Name: essensplan_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.essensplan_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: essensplan_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.essensplan_id_seq OWNED BY koch.essensplan.id;


--
-- Name: geraete; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.geraete (
    id integer NOT NULL,
    name text NOT NULL,
    typ text,
    notizen text,
    vorhanden boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    standard boolean DEFAULT true NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.geraete FORCE ROW LEVEL SECURITY;


--
-- Name: geraete_heute; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.geraete_heute (
    geraet_id integer NOT NULL,
    gewaehlt_am timestamp with time zone DEFAULT now() NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.geraete_heute FORCE ROW LEVEL SECURITY;


--
-- Name: geraete_heute_stand; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.geraete_heute_stand (
    id integer DEFAULT 1 NOT NULL,
    stand_datum date NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.geraete_heute_stand FORCE ROW LEVEL SECURITY;


--
-- Name: geraete_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.geraete_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: geraete_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.geraete_id_seq OWNED BY koch.geraete.id;


--
-- Name: lagerort; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.lagerort (
    id integer NOT NULL,
    name text NOT NULL,
    sortierung integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.lagerort FORCE ROW LEVEL SECURITY;


--
-- Name: lagerort_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.lagerort_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: lagerort_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.lagerort_id_seq OWNED BY koch.lagerort.id;


--
-- Name: person; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.person (
    id integer NOT NULL,
    name text NOT NULL,
    rolle text DEFAULT 'erwachsener'::text NOT NULL,
    kcal_ziel integer,
    eiweiss_pct integer DEFAULT 30 NOT NULL,
    fett_pct integer DEFAULT 30 NOT NULL,
    kh_pct integer DEFAULT 40 NOT NULL,
    portionsfaktor numeric(4,2) DEFAULT 1.0 NOT NULL,
    aktiv boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    ernaehrung text DEFAULT ''::text NOT NULL,
    allergien text DEFAULT ''::text NOT NULL,
    mag_nicht text DEFAULT ''::text NOT NULL,
    mag_gern text DEFAULT ''::text NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.person FORCE ROW LEVEL SECURITY;


--
-- Name: person_abwesenheit_regel; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.person_abwesenheit_regel (
    id integer NOT NULL,
    person_id integer NOT NULL,
    woche_typ text DEFAULT 'alle'::text NOT NULL,
    von_wochentag integer NOT NULL,
    von_mahlzeit text NOT NULL,
    bis_wochentag integer NOT NULL,
    bis_mahlzeit text NOT NULL,
    folgewoche boolean DEFAULT false NOT NULL,
    notiz text,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer,
    CONSTRAINT person_abwesenheit_regel_bis_wochentag_check CHECK (((bis_wochentag >= 1) AND (bis_wochentag <= 7))),
    CONSTRAINT person_abwesenheit_regel_von_wochentag_check CHECK (((von_wochentag >= 1) AND (von_wochentag <= 7))),
    CONSTRAINT person_abwesenheit_regel_woche_typ_check CHECK ((woche_typ = ANY (ARRAY['alle'::text, 'gerade'::text, 'ungerade'::text])))
);

ALTER TABLE ONLY koch.person_abwesenheit_regel FORCE ROW LEVEL SECURITY;


--
-- Name: person_abwesenheit_regel_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.person_abwesenheit_regel_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: person_abwesenheit_regel_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.person_abwesenheit_regel_id_seq OWNED BY koch.person_abwesenheit_regel.id;


--
-- Name: person_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.person_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: person_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.person_id_seq OWNED BY koch.person.id;


--
-- Name: person_notiz; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.person_notiz (
    id bigint NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer NOT NULL,
    person_id integer NOT NULL,
    text text NOT NULL,
    quelle text DEFAULT 'manuell'::text NOT NULL,
    erstellt timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY koch.person_notiz FORCE ROW LEVEL SECURITY;


--
-- Name: person_notiz_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.person_notiz_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: person_notiz_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.person_notiz_id_seq OWNED BY koch.person_notiz.id;


--
-- Name: personen_heute; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.personen_heute (
    id integer NOT NULL,
    person_id integer NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.personen_heute FORCE ROW LEVEL SECURITY;


--
-- Name: personen_heute_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.personen_heute_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: personen_heute_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.personen_heute_id_seq OWNED BY koch.personen_heute.id;


--
-- Name: rezept_geraete; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.rezept_geraete (
    rezept_id integer NOT NULL,
    geraet_id integer NOT NULL,
    pflicht boolean DEFAULT true NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.rezept_geraete FORCE ROW LEVEL SECURITY;


--
-- Name: rezept_zutaten; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.rezept_zutaten (
    id integer NOT NULL,
    rezept_id integer NOT NULL,
    zutat_id integer NOT NULL,
    menge numeric(10,2),
    einheit text,
    optional boolean DEFAULT false NOT NULL,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.rezept_zutaten FORCE ROW LEVEL SECURITY;


--
-- Name: rezept_zutaten_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.rezept_zutaten_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rezept_zutaten_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.rezept_zutaten_id_seq OWNED BY koch.rezept_zutaten.id;


--
-- Name: rezepte; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.rezepte (
    id integer NOT NULL,
    name text NOT NULL,
    beschreibung text,
    anleitung text,
    portionen integer DEFAULT 2 NOT NULL,
    dauer_minuten integer,
    quelle text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    zubereitung jsonb,
    zubereitung_guided jsonb,
    geraete_sig text,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer,
    veroeffentlicht boolean DEFAULT false NOT NULL,
    bild text
);

ALTER TABLE ONLY koch.rezepte FORCE ROW LEVEL SECURITY;


--
-- Name: rezepte_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.rezepte_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rezepte_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.rezepte_id_seq OWNED BY koch.rezepte.id;


--
-- Name: vorrat; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.vorrat (
    id integer NOT NULL,
    zutat_id integer NOT NULL,
    menge numeric(10,2) NOT NULL,
    einheit text NOT NULL,
    ablaufdatum date,
    ort text,
    hinzugefuegt_am timestamp with time zone DEFAULT now() NOT NULL,
    lagerort_id integer,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.vorrat FORCE ROW LEVEL SECURITY;


--
-- Name: v_rezept_machbarkeit; Type: VIEW; Schema: koch; Owner: -
--

CREATE VIEW koch.v_rezept_machbarkeit AS
 SELECT r.id AS rezept_id,
    r.name AS rezept,
    count(*) FILTER (WHERE (NOT rz.optional)) AS pflicht_zutaten,
    count(*) FILTER (WHERE ((NOT rz.optional) AND (vz.zutat_id IS NOT NULL))) AS davon_vorhanden,
    count(*) FILTER (WHERE ((NOT rz.optional) AND (vz.zutat_id IS NULL))) AS fehlend
   FROM ((koch.rezepte r
     JOIN koch.rezept_zutaten rz ON ((rz.rezept_id = r.id)))
     LEFT JOIN ( SELECT DISTINCT vorrat.zutat_id
           FROM koch.vorrat) vz ON ((vz.zutat_id = rz.zutat_id)))
  GROUP BY r.id, r.name;


--
-- Name: zutaten; Type: TABLE; Schema: koch; Owner: -
--

CREATE TABLE koch.zutaten (
    id integer NOT NULL,
    name text NOT NULL,
    kategorie text,
    standard_einheit text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    grundzutat boolean DEFAULT false NOT NULL,
    kanonische_zutat_id integer,
    kanonisch_fixiert boolean DEFAULT false NOT NULL,
    gebinde_menge numeric,
    gebinde_einheit text,
    account_id integer DEFAULT (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer
);

ALTER TABLE ONLY koch.zutaten FORCE ROW LEVEL SECURITY;


--
-- Name: v_vorrat_aggregiert; Type: VIEW; Schema: koch; Owner: -
--

CREATE VIEW koch.v_vorrat_aggregiert AS
 SELECT z.id AS zutat_id,
    z.name AS zutat,
    v.einheit,
    sum(v.menge) AS menge_gesamt,
    min(v.ablaufdatum) AS naechstes_ablaufdatum
   FROM (koch.vorrat v
     JOIN koch.zutaten z ON ((z.id = v.zutat_id)))
  GROUP BY z.id, z.name, v.einheit;


--
-- Name: vorrat_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.vorrat_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vorrat_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.vorrat_id_seq OWNED BY koch.vorrat.id;


--
-- Name: zutaten_id_seq; Type: SEQUENCE; Schema: koch; Owner: -
--

CREATE SEQUENCE koch.zutaten_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: zutaten_id_seq; Type: SEQUENCE OWNED BY; Schema: koch; Owner: -
--

ALTER SEQUENCE koch.zutaten_id_seq OWNED BY koch.zutaten.id;


--
-- Name: account id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.account ALTER COLUMN id SET DEFAULT nextval('koch.account_id_seq'::regclass);


--
-- Name: angebote id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.angebote ALTER COLUMN id SET DEFAULT nextval('koch.angebote_id_seq'::regclass);


--
-- Name: app_session id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_session ALTER COLUMN id SET DEFAULT nextval('koch.app_session_id_seq'::regclass);


--
-- Name: app_user id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_user ALTER COLUMN id SET DEFAULT nextval('koch.app_user_id_seq'::regclass);


--
-- Name: bewertung id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bewertung ALTER COLUMN id SET DEFAULT nextval('koch.bewertung_id_seq'::regclass);


--
-- Name: bugreport id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bugreport ALTER COLUMN id SET DEFAULT nextval('koch.bugreport_id_seq'::regclass);


--
-- Name: einkauf_extra id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkauf_extra ALTER COLUMN id SET DEFAULT nextval('koch.einkauf_extra_id_seq'::regclass);


--
-- Name: einkaufstag id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag ALTER COLUMN id SET DEFAULT nextval('koch.einkaufstag_id_seq'::regclass);


--
-- Name: einkaufstag_haendler id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag_haendler ALTER COLUMN id SET DEFAULT nextval('koch.einkaufstag_haendler_id_seq'::regclass);


--
-- Name: einladung id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einladung ALTER COLUMN id SET DEFAULT nextval('koch.einladung_id_seq'::regclass);


--
-- Name: essensplan id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.essensplan ALTER COLUMN id SET DEFAULT nextval('koch.essensplan_id_seq'::regclass);


--
-- Name: geraete id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.geraete ALTER COLUMN id SET DEFAULT nextval('koch.geraete_id_seq'::regclass);


--
-- Name: lagerort id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.lagerort ALTER COLUMN id SET DEFAULT nextval('koch.lagerort_id_seq'::regclass);


--
-- Name: person id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person ALTER COLUMN id SET DEFAULT nextval('koch.person_id_seq'::regclass);


--
-- Name: person_abwesenheit_regel id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person_abwesenheit_regel ALTER COLUMN id SET DEFAULT nextval('koch.person_abwesenheit_regel_id_seq'::regclass);


--
-- Name: person_notiz id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person_notiz ALTER COLUMN id SET DEFAULT nextval('koch.person_notiz_id_seq'::regclass);


--
-- Name: personen_heute id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.personen_heute ALTER COLUMN id SET DEFAULT nextval('koch.personen_heute_id_seq'::regclass);


--
-- Name: rezept_zutaten id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_zutaten ALTER COLUMN id SET DEFAULT nextval('koch.rezept_zutaten_id_seq'::regclass);


--
-- Name: rezepte id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezepte ALTER COLUMN id SET DEFAULT nextval('koch.rezepte_id_seq'::regclass);


--
-- Name: vorrat id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.vorrat ALTER COLUMN id SET DEFAULT nextval('koch.vorrat_id_seq'::regclass);


--
-- Name: zutaten id; Type: DEFAULT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.zutaten ALTER COLUMN id SET DEFAULT nextval('koch.zutaten_id_seq'::regclass);


--
-- Name: account_mitglied account_mitglied_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.account_mitglied
    ADD CONSTRAINT account_mitglied_pkey PRIMARY KEY (account_id, user_id);


--
-- Name: account account_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.account
    ADD CONSTRAINT account_pkey PRIMARY KEY (id);


--
-- Name: angebote angebote_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.angebote
    ADD CONSTRAINT angebote_pkey PRIMARY KEY (id);


--
-- Name: app_session app_session_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_session
    ADD CONSTRAINT app_session_pkey PRIMARY KEY (id);


--
-- Name: app_session app_session_token_hash_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_session
    ADD CONSTRAINT app_session_token_hash_key UNIQUE (token_hash);


--
-- Name: app_user app_user_email_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_user
    ADD CONSTRAINT app_user_email_key UNIQUE (email);


--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (id);


--
-- Name: bewertung bewertung_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bewertung
    ADD CONSTRAINT bewertung_pkey PRIMARY KEY (id);


--
-- Name: bugreport bugreport_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bugreport
    ADD CONSTRAINT bugreport_pkey PRIMARY KEY (id);


--
-- Name: einkauf_extra einkauf_extra_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkauf_extra
    ADD CONSTRAINT einkauf_extra_pkey PRIMARY KEY (id);


--
-- Name: einkaufstag einkaufstag_datum_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag
    ADD CONSTRAINT einkaufstag_account_datum_key UNIQUE (account_id, datum);


--
-- Name: einkaufstag_haendler einkaufstag_haendler_account_id_datum_haendler_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag_haendler
    ADD CONSTRAINT einkaufstag_haendler_account_id_datum_haendler_key UNIQUE (account_id, datum, haendler);


--
-- Name: einkaufstag_haendler einkaufstag_haendler_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag_haendler
    ADD CONSTRAINT einkaufstag_haendler_pkey PRIMARY KEY (id);


--
-- Name: einkaufstag einkaufstag_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag
    ADD CONSTRAINT einkaufstag_pkey PRIMARY KEY (id);


--
-- Name: einladung einladung_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einladung
    ADD CONSTRAINT einladung_pkey PRIMARY KEY (id);


--
-- Name: einladung einladung_token_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einladung
    ADD CONSTRAINT einladung_token_key UNIQUE (token);


--
-- Name: essensplan essensplan_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.essensplan
    ADD CONSTRAINT essensplan_pkey PRIMARY KEY (id);


--
-- Name: geraete_heute geraete_heute_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.geraete_heute
    ADD CONSTRAINT geraete_heute_pkey PRIMARY KEY (geraet_id);


--
-- Name: geraete geraete_account_name_key; Type: CONSTRAINT; Schema: koch; Owner: -
-- Pro-Konto eindeutig (vorher global UNIQUE(name) -> blockierte Namen anderer Konten).

ALTER TABLE ONLY koch.geraete
    ADD CONSTRAINT geraete_account_name_key UNIQUE (account_id, name);


--
-- Name: geraete geraete_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.geraete
    ADD CONSTRAINT geraete_pkey PRIMARY KEY (id);


--
-- Name: lagerort lagerort_name_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.lagerort
    ADD CONSTRAINT lagerort_account_name_key UNIQUE (account_id, name);


--
-- Name: lagerort lagerort_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.lagerort
    ADD CONSTRAINT lagerort_pkey PRIMARY KEY (id);


--
-- Name: person_abwesenheit_regel person_abwesenheit_regel_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person_abwesenheit_regel
    ADD CONSTRAINT person_abwesenheit_regel_pkey PRIMARY KEY (id);


--
-- Name: person_notiz person_notiz_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person_notiz
    ADD CONSTRAINT person_notiz_pkey PRIMARY KEY (id);


--
-- Name: person person_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person
    ADD CONSTRAINT person_pkey PRIMARY KEY (id);


--
-- Name: personen_heute personen_heute_person_id_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.personen_heute
    ADD CONSTRAINT personen_heute_person_id_key UNIQUE (person_id);


--
-- Name: personen_heute personen_heute_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.personen_heute
    ADD CONSTRAINT personen_heute_pkey PRIMARY KEY (id);


--
-- Name: rezept_geraete rezept_geraete_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_geraete
    ADD CONSTRAINT rezept_geraete_pkey PRIMARY KEY (rezept_id, geraet_id);


--
-- Name: rezept_zutaten rezept_zutaten_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_zutaten
    ADD CONSTRAINT rezept_zutaten_pkey PRIMARY KEY (id);


--
-- Name: rezept_zutaten rezept_zutaten_rezept_id_zutat_id_key; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_zutaten
    ADD CONSTRAINT rezept_zutaten_rezept_id_zutat_id_key UNIQUE (rezept_id, zutat_id);


--
-- Name: rezepte rezepte_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezepte
    ADD CONSTRAINT rezepte_pkey PRIMARY KEY (id);


--
-- Name: vorrat vorrat_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.vorrat
    ADD CONSTRAINT vorrat_pkey PRIMARY KEY (id);


--
-- Name: zutaten zutaten_pkey; Type: CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.zutaten
    ADD CONSTRAINT zutaten_pkey PRIMARY KEY (id);


--
-- Name: angebote_gueltig_idx; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX angebote_gueltig_idx ON koch.angebote USING btree (gueltig_von, gueltig_bis);


--
-- Name: angebote_haendler_idx; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX angebote_haendler_idx ON koch.angebote USING btree (haendler, gueltig_von);


--
-- Name: bewertung_acc_rezept; Type: INDEX; Schema: koch; Owner: -
--

CREATE UNIQUE INDEX bewertung_acc_rezept ON koch.bewertung USING btree (account_id, rezept_id);


--
-- Name: einladung_acc; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX einladung_acc ON koch.einladung USING btree (account_id, status);


--
-- Name: geraete_heute_stand_acc_key; Type: INDEX; Schema: koch; Owner: -
--

CREATE UNIQUE INDEX geraete_heute_stand_acc_key ON koch.geraete_heute_stand USING btree (account_id);


--
-- Name: idx_angebote_master_zutat; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX idx_angebote_master_zutat ON koch.angebote USING btree (master_zutat_id);


--
-- Name: idx_rezept_geraete_geraet; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX idx_rezept_geraete_geraet ON koch.rezept_geraete USING btree (geraet_id);


--
-- Name: idx_rezept_zutaten_zutat; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX idx_rezept_zutaten_zutat ON koch.rezept_zutaten USING btree (zutat_id);


--
-- Name: idx_vorrat_ablauf; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX idx_vorrat_ablauf ON koch.vorrat USING btree (ablaufdatum);


--
-- Name: idx_vorrat_zutat; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX idx_vorrat_zutat ON koch.vorrat USING btree (zutat_id);


--
-- Name: idx_zutaten_kanonisch; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX idx_zutaten_kanonisch ON koch.zutaten USING btree (kanonische_zutat_id);


--
-- Name: person_notiz_acc_person; Type: INDEX; Schema: koch; Owner: -
--

CREATE INDEX person_notiz_acc_person ON koch.person_notiz USING btree (account_id, person_id);


--
-- Name: zutaten_acc_name_key; Type: INDEX; Schema: koch; Owner: -
--

CREATE UNIQUE INDEX zutaten_acc_name_key ON koch.zutaten USING btree (COALESCE(account_id, 0), name);


--
-- Name: account_mitglied account_mitglied_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.account_mitglied
    ADD CONSTRAINT account_mitglied_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id) ON DELETE CASCADE;


--
-- Name: account_mitglied account_mitglied_user_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.account_mitglied
    ADD CONSTRAINT account_mitglied_user_id_fkey FOREIGN KEY (user_id) REFERENCES koch.app_user(id) ON DELETE CASCADE;


--
-- Name: angebote angebote_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.angebote
    ADD CONSTRAINT angebote_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: angebote angebote_master_zutat_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.angebote
    ADD CONSTRAINT angebote_master_zutat_id_fkey FOREIGN KEY (master_zutat_id) REFERENCES koch.zutaten(id) ON DELETE SET NULL;


--
-- Name: app_session app_session_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_session
    ADD CONSTRAINT app_session_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id) ON DELETE SET NULL;


--
-- Name: app_session app_session_user_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.app_session
    ADD CONSTRAINT app_session_user_id_fkey FOREIGN KEY (user_id) REFERENCES koch.app_user(id) ON DELETE CASCADE;


--
-- Name: bewertung bewertung_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bewertung
    ADD CONSTRAINT bewertung_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: bewertung bewertung_rezept_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bewertung
    ADD CONSTRAINT bewertung_rezept_id_fkey FOREIGN KEY (rezept_id) REFERENCES koch.rezepte(id) ON DELETE CASCADE;


--
-- Name: bugreport bugreport_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bugreport
    ADD CONSTRAINT bugreport_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id) ON DELETE CASCADE;


--
-- Name: bugreport bugreport_user_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.bugreport
    ADD CONSTRAINT bugreport_user_id_fkey FOREIGN KEY (user_id) REFERENCES koch.app_user(id) ON DELETE SET NULL;


--
-- Name: einkauf_extra einkauf_extra_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkauf_extra
    ADD CONSTRAINT einkauf_extra_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: einkauf_extra einkauf_extra_rezept_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkauf_extra
    ADD CONSTRAINT einkauf_extra_rezept_id_fkey FOREIGN KEY (rezept_id) REFERENCES koch.rezepte(id) ON DELETE SET NULL;


--
-- Name: einkaufstag einkaufstag_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag
    ADD CONSTRAINT einkaufstag_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: einkaufstag_haendler einkaufstag_haendler_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.einkaufstag_haendler
    ADD CONSTRAINT einkaufstag_haendler_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id) ON DELETE CASCADE;


--
-- Name: essensplan essensplan_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.essensplan
    ADD CONSTRAINT essensplan_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: essensplan essensplan_rezept_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.essensplan
    ADD CONSTRAINT essensplan_rezept_id_fkey FOREIGN KEY (rezept_id) REFERENCES koch.rezepte(id) ON DELETE SET NULL;


--
-- Name: geraete geraete_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.geraete
    ADD CONSTRAINT geraete_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: geraete_heute geraete_heute_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.geraete_heute
    ADD CONSTRAINT geraete_heute_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: geraete_heute geraete_heute_geraet_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.geraete_heute
    ADD CONSTRAINT geraete_heute_geraet_id_fkey FOREIGN KEY (geraet_id) REFERENCES koch.geraete(id) ON DELETE CASCADE;


--
-- Name: geraete_heute_stand geraete_heute_stand_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.geraete_heute_stand
    ADD CONSTRAINT geraete_heute_stand_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: lagerort lagerort_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.lagerort
    ADD CONSTRAINT lagerort_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: person_abwesenheit_regel person_abwesenheit_regel_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person_abwesenheit_regel
    ADD CONSTRAINT person_abwesenheit_regel_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: person_abwesenheit_regel person_abwesenheit_regel_person_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person_abwesenheit_regel
    ADD CONSTRAINT person_abwesenheit_regel_person_id_fkey FOREIGN KEY (person_id) REFERENCES koch.person(id) ON DELETE CASCADE;


--
-- Name: person person_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person
    ADD CONSTRAINT person_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: person_notiz person_notiz_person_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.person_notiz
    ADD CONSTRAINT person_notiz_person_id_fkey FOREIGN KEY (person_id) REFERENCES koch.person(id) ON DELETE CASCADE;


--
-- Name: personen_heute personen_heute_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.personen_heute
    ADD CONSTRAINT personen_heute_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: personen_heute personen_heute_person_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.personen_heute
    ADD CONSTRAINT personen_heute_person_id_fkey FOREIGN KEY (person_id) REFERENCES koch.person(id) ON DELETE CASCADE;


--
-- Name: rezept_geraete rezept_geraete_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_geraete
    ADD CONSTRAINT rezept_geraete_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: rezept_geraete rezept_geraete_geraet_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_geraete
    ADD CONSTRAINT rezept_geraete_geraet_id_fkey FOREIGN KEY (geraet_id) REFERENCES koch.geraete(id) ON DELETE CASCADE;


--
-- Name: rezept_geraete rezept_geraete_rezept_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_geraete
    ADD CONSTRAINT rezept_geraete_rezept_id_fkey FOREIGN KEY (rezept_id) REFERENCES koch.rezepte(id) ON DELETE CASCADE;


--
-- Name: rezept_zutaten rezept_zutaten_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_zutaten
    ADD CONSTRAINT rezept_zutaten_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: rezept_zutaten rezept_zutaten_rezept_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_zutaten
    ADD CONSTRAINT rezept_zutaten_rezept_id_fkey FOREIGN KEY (rezept_id) REFERENCES koch.rezepte(id) ON DELETE CASCADE;


--
-- Name: rezept_zutaten rezept_zutaten_zutat_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezept_zutaten
    ADD CONSTRAINT rezept_zutaten_zutat_id_fkey FOREIGN KEY (zutat_id) REFERENCES koch.zutaten(id) ON DELETE RESTRICT;


--
-- Name: rezepte rezepte_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.rezepte
    ADD CONSTRAINT rezepte_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: vorrat vorrat_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.vorrat
    ADD CONSTRAINT vorrat_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: vorrat vorrat_lagerort_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.vorrat
    ADD CONSTRAINT vorrat_lagerort_id_fkey FOREIGN KEY (lagerort_id) REFERENCES koch.lagerort(id) ON DELETE SET NULL;


--
-- Name: vorrat vorrat_zutat_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.vorrat
    ADD CONSTRAINT vorrat_zutat_id_fkey FOREIGN KEY (zutat_id) REFERENCES koch.zutaten(id) ON DELETE RESTRICT;


--
-- Name: zutaten zutaten_account_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.zutaten
    ADD CONSTRAINT zutaten_account_id_fkey FOREIGN KEY (account_id) REFERENCES koch.account(id);


--
-- Name: zutaten zutaten_kanonische_zutat_id_fkey; Type: FK CONSTRAINT; Schema: koch; Owner: -
--

ALTER TABLE ONLY koch.zutaten
    ADD CONSTRAINT zutaten_kanonische_zutat_id_fkey FOREIGN KEY (kanonische_zutat_id) REFERENCES koch.zutaten(id) ON DELETE SET NULL;


--
-- Name: bewertung acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.bewertung USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: bugreport acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.bugreport USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: einkauf_extra acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.einkauf_extra USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: einkaufstag acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.einkaufstag USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: einkaufstag_haendler acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.einkaufstag_haendler USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: einladung acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.einladung USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: essensplan acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.essensplan USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: geraete acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.geraete USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: geraete_heute acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.geraete_heute USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: geraete_heute_stand acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.geraete_heute_stand USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: lagerort acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.lagerort USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: person acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.person USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: person_abwesenheit_regel acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.person_abwesenheit_regel USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: person_notiz acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.person_notiz USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: personen_heute acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.personen_heute USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: vorrat acc_isolation; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY acc_isolation ON koch.vorrat USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: zutaten zutaten_mod; Type: POLICY; Schema: koch; Owner: -
-- F12: FOR ALL streng account-gebunden (kein account_id IS NULL im USING), damit ein
-- Mandant globale Katalog-Zeilen (account_id IS NULL) NICHT löschen/ändern kann. Die
-- Lesbarkeit globaler Zutaten regelt die separate FOR-SELECT-Policy unten (wie bei angebote).
--

CREATE POLICY zutaten_mod ON koch.zutaten USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: zutaten zutaten_select; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY zutaten_select ON koch.zutaten FOR SELECT USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id IS NULL) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: angebote; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.angebote ENABLE ROW LEVEL SECURITY;

--
-- Name: angebote angebote_mod; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY angebote_mod ON koch.angebote USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: angebote angebote_select; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY angebote_select ON koch.angebote FOR SELECT USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id IS NULL) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: bewertung; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.bewertung ENABLE ROW LEVEL SECURITY;

--
-- Name: bugreport; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.bugreport ENABLE ROW LEVEL SECURITY;

--
-- Name: einkauf_extra; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.einkauf_extra ENABLE ROW LEVEL SECURITY;

--
-- Name: einkaufstag; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.einkaufstag ENABLE ROW LEVEL SECURITY;

--
-- Name: einkaufstag_haendler; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.einkaufstag_haendler ENABLE ROW LEVEL SECURITY;

--
-- Name: einladung; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.einladung ENABLE ROW LEVEL SECURITY;

--
-- Name: essensplan; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.essensplan ENABLE ROW LEVEL SECURITY;

--
-- Name: geraete; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.geraete ENABLE ROW LEVEL SECURITY;

--
-- Name: geraete_heute; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.geraete_heute ENABLE ROW LEVEL SECURITY;

--
-- Name: geraete_heute_stand; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.geraete_heute_stand ENABLE ROW LEVEL SECURITY;

--
-- Name: lagerort; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.lagerort ENABLE ROW LEVEL SECURITY;

--
-- Name: person; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.person ENABLE ROW LEVEL SECURITY;

--
-- Name: person_abwesenheit_regel; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.person_abwesenheit_regel ENABLE ROW LEVEL SECURITY;

--
-- Name: person_notiz; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.person_notiz ENABLE ROW LEVEL SECURITY;

--
-- Name: personen_heute; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.personen_heute ENABLE ROW LEVEL SECURITY;

--
-- Name: rezept_geraete; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.rezept_geraete ENABLE ROW LEVEL SECURITY;

--
-- Name: rezept_geraete rezept_geraete_mod; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY rezept_geraete_mod ON koch.rezept_geraete USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: rezept_geraete rezept_geraete_select; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY rezept_geraete_select ON koch.rezept_geraete FOR SELECT USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer) OR (EXISTS ( SELECT 1
   FROM koch.rezepte r
  WHERE ((r.id = rezept_geraete.rezept_id) AND r.veroeffentlicht)))));


--
-- Name: rezept_zutaten; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.rezept_zutaten ENABLE ROW LEVEL SECURITY;

--
-- Name: rezept_zutaten rezept_zutaten_mod; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY rezept_zutaten_mod ON koch.rezept_zutaten USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: rezept_zutaten rezept_zutaten_select; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY rezept_zutaten_select ON koch.rezept_zutaten FOR SELECT USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer) OR (EXISTS ( SELECT 1
   FROM koch.rezepte r
  WHERE ((r.id = rezept_zutaten.rezept_id) AND r.veroeffentlicht)))));


--
-- Name: rezepte; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.rezepte ENABLE ROW LEVEL SECURITY;

--
-- Name: rezepte rezepte_mod; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY rezepte_mod ON koch.rezepte USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer))) WITH CHECK (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer)));


--
-- Name: rezepte rezepte_select; Type: POLICY; Schema: koch; Owner: -
--

CREATE POLICY rezepte_select ON koch.rezepte FOR SELECT USING (((current_setting('app.bypass'::text, true) = 'on'::text) OR (account_id = (NULLIF(current_setting('app.account_id'::text, true), ''::text))::integer) OR veroeffentlicht));


--
-- Name: vorrat; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.vorrat ENABLE ROW LEVEL SECURITY;

--
-- Name: zutaten; Type: ROW SECURITY; Schema: koch; Owner: -
--

ALTER TABLE koch.zutaten ENABLE ROW LEVEL SECURITY;


--
-- Ergänzungen aus späteren Migrationen (im Dump noch nicht enthalten).
-- Idempotent; damit ist schema.sql für frische Installationen vollständig.
--

ALTER TABLE koch.app_user ADD COLUMN IF NOT EXISTS email_verifiziert boolean NOT NULL DEFAULT false;
ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS gang text;
ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS kueche text;
ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS importiert boolean NOT NULL DEFAULT false;
ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS je_veroeffentlicht boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS koch.passwort_reset (
    id serial PRIMARY KEY,
    user_id integer NOT NULL,
    token_hash text NOT NULL UNIQUE,
    ablauf timestamp with time zone NOT NULL,
    benutzt boolean NOT NULL DEFAULT false,
    erstellt timestamp with time zone NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS passwort_reset_token_idx ON koch.passwort_reset (token_hash);

CREATE TABLE IF NOT EXISTS koch.email_verify (
    id serial PRIMARY KEY,
    user_id integer NOT NULL,
    token_hash text NOT NULL UNIQUE,
    ablauf timestamp with time zone NOT NULL,
    erstellt timestamp with time zone NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS email_verify_token_idx ON koch.email_verify (token_hash);

CREATE INDEX IF NOT EXISTS account_mitglied_user_idx ON koch.account_mitglied (user_id);
CREATE INDEX IF NOT EXISTS person_acc_idx ON koch.person (account_id);
CREATE INDEX IF NOT EXISTS app_session_user_idx ON koch.app_session (user_id);
CREATE INDEX IF NOT EXISTS app_user_created_idx ON koch.app_user (created_at DESC);


--
-- PostgreSQL database dump complete
--


