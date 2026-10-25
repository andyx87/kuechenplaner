import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/koch")
DB_SCHEMA = os.environ.get("DB_SCHEMA", "koch")

# --- E-Mail-Versand (Resend) ---
# Ohne RESEND_API_KEY ist der Versand ein No-Op (wird nur geloggt) – die App
# funktioniert weiter (Einladungen liefern dann weiter den Link zum manuellen Teilen).
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
# Absender für System-Mails (Reset/Bestätigung/Einladung). Kundenkommunikation/Kontakt
# laeuft ueber die Kontaktadresse aus SUPPORT_EMAIL (Footer/Impressum).
MAIL_FROM = os.environ.get("MAIL_FROM", "Topfplan <no-reply@example.com>")
# Basis-URL für Links in E-Mails (Einladung, Passwort-Reset, Bestätigung).
# Auch Fallback fuer Stripe-Redirects (Erfolg/Abbruch), wenn der Request keinen Origin liefert.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8096").rstrip("/")

# Betreiberangaben fuer den Footer der System-Mails (leer = nicht angezeigt).
# Betreiber muessen diese Werte selbst setzen.
OPERATOR_NAME = os.environ.get("OPERATOR_NAME", "")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "")

# --- IT-Recht Kanzlei – Legal Text Interface (Rechtstexte-Schnittstelle) ---
# Gemeinsames Auth-Token; muss mit dem im Mandantenportal hinterlegten Wert
# übereinstimmen. Ohne Token weist der Endpunkt jede Anfrage ab (Fehler 3).
ITRK_TOKEN = os.environ.get("ITRK_TOKEN", "")

# --- KI: Google Vertex AI (OpenAI-kompatibler Endpoint) ---
# Authentifizierung ueber Service-Account/ADC (kein API-Key): in der Cloud
# automatisch ueber den Cloud-Run-Service-Account, lokal ueber
# `gcloud auth application-default login`. Siehe app/gauth.py.
# Pflicht fuer die KI-Funktionen (kein Default): eigene GCP-Projekt-ID.
GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
# Gemini ist nur ueber den globalen Endpoint vollstaendig verfuegbar
# (flash-lite/pro fehlen in europe-west3) -> Default "global".
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "global")
# Chat/Vision: OpenAI-kompatibler Vertex-Endpoint.
VERTEX_BASE_URL = os.environ.get("VERTEX_BASE_URL", "") or (
    f"https://aiplatform.googleapis.com/v1beta1/projects/{GCP_PROJECT}"
    f"/locations/{VERTEX_LOCATION}/endpoints/openapi")
# Bilder (Imagen): nativer predict-Endpoint (v1, kein OpenAI-Schema).
VERTEX_PREDICT_BASE = os.environ.get("VERTEX_PREDICT_BASE", "") or (
    f"https://aiplatform.googleapis.com/v1/projects/{GCP_PROJECT}"
    f"/locations/{VERTEX_LOCATION}")
# Gate "ist KI konfiguriert?" (frueher CHAT_MODEL). Default an, da Vertex
# ueber den Service-Account immer erreichbar ist. Das konkrete Modell je
# Anfrage liefert billing.modell_fuer_konto() (Stufe schnell/standard/pro).
CHAT_MODEL = os.environ.get("CHAT_MODEL", "") or "vertex"
# Bildgenerierung über Gemini (Imagen 4 wird am 17.08.2026 abgeschaltet). EIN Modell,
# zwei Auflösungen via billing.BILD_SIZE (Stufe schnell=512, standard=1K), tokenbasiert
# abgerechnet (usageMetadata; Bild-Output-Tokens). Über generateContent (kein predict).
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "") or "gemini-3.1-flash-image"
IMAGE_MODEL_STANDARD = os.environ.get("IMAGE_MODEL_STANDARD", "") or "gemini-3.1-flash-image"
# Einheitlicher Stil-Prompt fuer ALLE Rezeptbilder (per .env IMAGE_STYLE anpassbar),
# damit die Bibliothek einen konsistenten Look hat.
# Kurzer, rein BESCHREIBENDER Bild-Stil (Englisch wirkt bei Imagen am besten und
# verhindert, dass Prompt-Text als Schrift ins Bild gerendert wird). EINE Zeile,
# keine Anweisungen, kein "kein Text"-Hinweis (der provoziert erst Text).
IMAGE_STYLE = os.environ.get("IMAGE_STYLE", "") or (
    "professional food photography, single plated dish, overhead 45 degree angle, "
    "soft natural daylight, shallow depth of field, photorealistic, high detail, "
    "appetizing, clean composition, tableware and background matching the cuisine of the dish"
)

# --- Erst-Setup: Plattform-Admin (F8) ---
# Nur wer beim allerersten Signup dieses Token mitgibt, wird super_admin und übernimmt
# Konto 1. Leer = niemand wird automatisch Admin (Betreiber promotet dann per DB/Seed).
# Verhindert, dass ein Fremder auf einem frischen Deploy den Admin per Signup-Reihenfolge greift.
ADMIN_BOOTSTRAP_TOKEN = os.environ.get("ADMIN_BOOTSTRAP_TOKEN", "")

PORT = int(os.environ.get("PORT", "8093"))
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
API_TOKEN = os.environ.get("API_TOKEN", "")

# --- Client-IP hinter Proxies (S-5, AND-22/AND-33) ---
# Anzahl vertrauenswürdiger Proxies, die pro Hop die Peer-IP an X-Forwarded-For
# anhängen. Beispiel CDN + Cloud-Load-Balancer: 2 = CDN + Load-Balancer/Google-
# Frontend – die echte Client-IP ist dann der zweitletzte Eintrag im Header.
# Alle Einträge DAHINTER (vorne) stammen ursprünglich vom Client und sind frei
# fälschbar; die erste Adresse darf deshalb nie ungeprüft verwendet werden.
# Einzelner Load-Balancer / Reverse-Proxy: 1.
# Ungültige Werte fallen auf den Default zurück.
try:
    TRUSTED_PROXY_HOPS = max(1, min(10, int(os.environ.get("TRUSTED_PROXY_HOPS", "2"))))
except ValueError:
    TRUSTED_PROXY_HOPS = 2

# --- MCP-Endpunkt (/mcp, Streamable HTTP) ---
# Secure-by-default AUS: Der MCP-Server exponiert vollständig mutierende Tools
# (rezept_loeschen, vorrat_reduzieren, angebot_loeschen …) OHNE eigene Auth und
# läuft ohne Auth-Kontext auf Konto 1 bzw. mit RLS-Bypass. In der Cloud (öffentliche
# Cloud-Run-URL) wäre er damit anonym erreichbar → deshalb Default deaktiviert.
# Nur für eine KI-Anbindung im lokalen Netz (z.B. Open WebUI/LiteLLM) per MCP_ENABLED=1
# gezielt aktivieren – dort ist der Port nicht öffentlich erreichbar.
MCP_ENABLED = os.environ.get("MCP_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

# --- Abo-Modell v4 (Kontingent statt €-Guthaben/PAYG) ---
# Secure/konservativ-by-default AUS: solange nicht gesetzt, läuft die bisherige
# PAYG-/Guthaben-Abrechnung unverändert. Wird erst zum Go-Live aktiviert (Stufe 4/5).
# Neues Modell: Gratis (monatl. KI-Text- + Bild-Kontingent), Abo (KI frei, Bild-Kontingent),
# Trial (Vollzugang bis trial_bis), Bild-Credits über dem Bild-Limit. Kein Guthaben/PAYG.
ABO_MODELL_V4 = os.environ.get("ABO_MODELL_V4", "0").strip().lower() in ("1", "true", "yes", "on")

# Oeffentlicher ICS-Speiseplan-Feed: eigener Token (in der Abo-URL), damit Google
# Kalender den Feed ohne vorgeschalteten Login abrufen kann. Steht die App hinter
# einem Zugangsschutz, muss der ICS-Pfad dort freigegeben sein. Leer = Feed deaktiviert.
KALENDER_TOKEN = os.environ.get("KALENDER_TOKEN", "")
# Basis-URL des koch-web Frontends fuer Rezept-Hyperlinks im Kalender,
# z.B. https://kochen.example.com (ohne abschliessenden Slash).
WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "").rstrip("/")

# --- Stripe: Abo (wiederkehrend) + Foto-Credit-Pack (einmalig) ---
# Price-IDs werden im Stripe-Dashboard angelegt (Live-Modus) und hier per Env gesetzt.
# Ohne sie sind die jeweiligen Checkouts deaktiviert (Endpoint meldet "nicht konfiguriert").
STRIPE_PRICE_ABO = os.environ.get("STRIPE_PRICE_ABO", "")          # wiederkehrend, 9,99 €/Mo
STRIPE_PRICE_CREDITS = os.environ.get("STRIPE_PRICE_CREDITS", "")  # einmalig, 12,99 € Foto-Pack
FOTO_PACK_CREDITS = int(os.environ.get("FOTO_PACK_CREDITS", "75")) # Bild-Credits je Pack-Kauf

# --- Beta: Inaktive Tester zurueckstufen ---
# Beta-Tester, die laenger als N Tage inaktiv sind, verlieren den Vollzugang (trial_bis wird
# geloescht, Konto laeuft als Gratis weiter) und ihr Beta-Platz wird wieder frei. 0 = aus.
BETA_INAKTIV_TAGE = int(os.environ.get("BETA_INAKTIV_TAGE", "10"))

# --- Prospekt-Import: Modellstufe ---
# Der Import macht EINEN Modellaufruf pro Prospektseite (bis 24 Seiten). Angebote von einer
# Seite abzulesen ist Extraktion, keine Denkaufgabe – daher "schnell" (Flash-Lite: 0,10/0,40 €
# je 1 Mio. Token statt 0,30/2,50 €, also ca. ein Sechstel). Falls die Erkennungsqualitaet auf
# dichten Prospektseiten leidet, hier ohne Code-Aenderung auf "standard" zurueckstellen.
ANGEBOTE_STUFE = os.environ.get("ANGEBOTE_STUFE", "schnell").strip().lower()

# --- Datenschutz: Personenbezug gegenueber der KI ---
# AUS-by-default: die App sendet KEINE Klarnamen von Haushaltsmitgliedern an das Modell und
# speichert personenbezogene Infos nicht mehr proaktiv aus dem Chat-Verlauf. Personen werden
# gegenueber der KI stabil durchnummeriert ("Person 1", "Person 2", ...). Der fachliche Nutzen
# bleibt vollstaendig erhalten (Portionsfaktoren, Allergien strikt ausschliessen) – nur die
# Identitaet wird nicht uebertragen. Mit KI_PERSONENNAMEN=1 gilt wieder das alte Verhalten.
KI_PERSONENNAMEN = os.environ.get("KI_PERSONENNAMEN", "0").strip().lower() in ("1", "true", "yes", "on")

# --- Spracheingabe (Audio -> Text via KI) ---
# AUS-by-default: der Sprachpfad war weder im Monatskontingent gezaehlt noch ratenbegrenzt und
# lief auf dem Tarif-Modell des Kontos (also ggf. dem teuren). Bis er gedeckelt ist, bleibt er
# abgeschaltet; das Frontend blendet die Mikrofon-Knoepfe passend aus (settings.js).
SPRACHEINGABE_AKTIV = os.environ.get("SPRACHEINGABE_AKTIV", "0").strip().lower() in ("1", "true", "yes", "on")

# --- Sentry (Fehler-Monitoring, optional) ---
# Secure/konservativ-by-default AUS: ohne DSN wird Sentry gar nicht importiert/initialisiert
# (kein Crash, kein Overhead). Erst mit gesetztem SENTRY_DSN aktiv (Betreiber traegt die DSN
# per Env ein, kein Secret im Code).
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
SENTRY_ENV = os.environ.get("SENTRY_ENV", "staging")
