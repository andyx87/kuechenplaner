import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/koch")
DB_SCHEMA = os.environ.get("DB_SCHEMA", "koch")

# --- E-Mail-Versand (Resend) ---
# Ohne RESEND_API_KEY ist der Versand ein No-Op (wird nur geloggt) – die App
# funktioniert weiter (Einladungen liefern dann weiter den Link zum manuellen Teilen).
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
# Absender für System-Mails (Reset/Bestätigung/Einladung). Kundenkommunikation/Kontakt
# laeuft ueber die Kontaktadresse aus SUPPORT_EMAIL (Footer/Impressum).
MAIL_FROM = os.environ.get("MAIL_FROM", "Küchenplaner <no-reply@example.com>")
# Basis-URL für Links in E-Mails (Einladung, Passwort-Reset, Bestätigung).
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8096").rstrip("/")

# Betreiberangaben fuer den Footer der System-Mails (leer = nicht angezeigt).
# Betreiber muessen diese Werte selbst setzen.
OPERATOR_NAME = os.environ.get("OPERATOR_NAME", "")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "")

# --- KI: eigener Anbieter ("bring your own key") ---
# Alle KI-Funktionen sind OPTIONAL. Ohne KI_BASE_URL + KI_MODEL_DEFAULT ist die KI aus:
# die Web-App blendet die KI-Knöpfe aus (GET /api/ki/status), alles andere funktioniert.
# Text/Vision laufen über eine OpenAI-kompatible Chat-Completions-API (OpenAI, OpenRouter,
# LiteLLM, Ollama, vLLM, Gemini-OpenAI-Endpunkt, ...). Siehe app/ki/.
def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


KI_BASE_URL = _env("KI_BASE_URL").rstrip("/")
KI_API_KEY = _env("KI_API_KEY")
KI_MODEL_DEFAULT = _env("KI_MODEL_DEFAULT")
# Modell für Bildeingaben (Foto-Erkennung, Rezept aus Screenshot/PDF, Chat mit Bild).
# Leer = KI_MODEL_DEFAULT; "aus" = der Anbieter kann keine Bilder -> Foto-Funktionen aus.
KI_MODEL_VISION = _env("KI_MODEL_VISION")
# Modell für den Prospekt-Import (ein Aufruf je Seite, Bild oder Text). Leer = Vision-Modell.
KI_MODEL_FLYER = _env("KI_MODEL_FLYER")
try:
    KI_TIMEOUT_S = float(_env("KI_TIMEOUT_S", "120"))
except ValueError:
    KI_TIMEOUT_S = 120.0

# Bildgenerierung (optional): OpenAI-Images-kompatibel (POST /images/generations).
# Aktiv nur mit KI_IMAGE_MODEL. URL/Schlüssel fallen auf die Text-Einstellungen zurück.
KI_IMAGE_BASE_URL = _env("KI_IMAGE_BASE_URL", KI_BASE_URL).rstrip("/")
KI_IMAGE_API_KEY = _env("KI_IMAGE_API_KEY", KI_API_KEY)
KI_IMAGE_MODEL = _env("KI_IMAGE_MODEL")
KI_IMAGE_SIZE = _env("KI_IMAGE_SIZE", "1024x1024")
# Einheitlicher, rein beschreibender Stil-Prompt für alle Rezeptbilder.
KI_IMAGE_STYLE = _env("KI_IMAGE_STYLE") or (
    "professional food photography, single plated dish, overhead 45 degree angle, "
    "soft natural daylight, shallow depth of field, photorealistic, high detail, "
    "appetizing, clean composition, tableware and background matching the cuisine of the dish"
)

# Spracheingabe (optional): OpenAI-kompatible Transkription (POST /audio/transcriptions,
# z. B. whisper-1). Aktiv nur mit KI_TRANSCRIBE_MODEL.
KI_TRANSCRIBE_BASE_URL = _env("KI_TRANSCRIBE_BASE_URL", KI_BASE_URL).rstrip("/")
KI_TRANSCRIBE_API_KEY = _env("KI_TRANSCRIBE_API_KEY", KI_API_KEY)
KI_TRANSCRIBE_MODEL = _env("KI_TRANSCRIBE_MODEL")

# Online-Angebotssuche (optional, experimentell): Gemini-API mit Google-Suche
# (Grounding). Aktiv nur mit eigenem Gemini-API-Schlüssel.
KI_WEBSUCHE_GEMINI_API_KEY = _env("KI_WEBSUCHE_GEMINI_API_KEY")
KI_WEBSUCHE_MODEL = _env("KI_WEBSUCHE_MODEL", "gemini-2.5-flash")

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

# --- MCP-Endpunkt (/mcp, Streamable HTTP) mit OAuth 2.1 ---
# Der MCP-Server ist nur mit Anmeldung nutzbar: OAuth 2.1 (Claude-Connector, Dynamic Client
# Registration, PKCE S256) oder persönliches Zugriffstoken (Einstellungen → Claude & MCP).
# Jeder Aufruf läuft im Haushalt des Token-Inhabers unter Postgres-RLS. MCP_ENABLED=0
# schaltet den Endpunkt samt OAuth-Routen ab.
MCP_ENABLED = os.environ.get("MCP_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")

# Öffentliche Basis-URL des Servers, unter der /mcp, /authorize, /token und
# /.well-known/* erreichbar sind (Issuer + Ressource). Für Claude zwingend HTTPS und aus dem
# Internet erreichbar. Leer = APP_BASE_URL (Web-App und API hinter demselben Origin).
PUBLIC_URL = (os.environ.get("PUBLIC_URL") or APP_BASE_URL).strip().rstrip("/")

# Zusätzlich erlaubte OAuth-Redirect-URIs (kommagetrennt, exakte Werte). Immer erlaubt:
# die Claude-Callbacks (claude.ai/claude.com) und Loopback-Redirects (localhost/127.0.0.1,
# beliebiger Port) für Desktop-Clients wie Claude Code.
OAUTH_REDIRECT_URIS = [u.strip() for u in os.environ.get("OAUTH_REDIRECT_URIS", "").split(",") if u.strip()]
# OAUTH_REDIRECT_FREI=1 erlaubt jede HTTPS-Redirect-URI (andere MCP-Clients). Standard: aus.
OAUTH_REDIRECT_FREI = os.environ.get("OAUTH_REDIRECT_FREI", "0").strip().lower() in ("1", "true", "yes", "on")
try:
    OAUTH_ACCESS_TTL_S = max(300, int(os.environ.get("OAUTH_ACCESS_TTL_S", "3600")))
except ValueError:
    OAUTH_ACCESS_TTL_S = 3600
try:
    OAUTH_REFRESH_TTL_TAGE = max(1, int(os.environ.get("OAUTH_REFRESH_TTL_TAGE", "30")))
except ValueError:
    OAUTH_REFRESH_TTL_TAGE = 30

# Oeffentlicher ICS-Speiseplan-Feed: eigener Token (in der Abo-URL), damit Google
# Kalender den Feed ohne vorgeschalteten Login abrufen kann. Steht die App hinter
# einem Zugangsschutz, muss der ICS-Pfad dort freigegeben sein. Leer = Feed deaktiviert.
KALENDER_TOKEN = os.environ.get("KALENDER_TOKEN", "")
# Basis-URL des koch-web Frontends fuer Rezept-Hyperlinks im Kalender,
# z.B. https://kochen.example.com (ohne abschliessenden Slash).
WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "").rstrip("/")

# --- Datenschutz: Personenbezug gegenueber der KI ---
# AUS-by-default: die App sendet KEINE Klarnamen von Haushaltsmitgliedern an das Modell und
# speichert personenbezogene Infos nicht mehr proaktiv aus dem Chat-Verlauf. Personen werden
# gegenueber der KI stabil durchnummeriert ("Person 1", "Person 2", ...). Der fachliche Nutzen
# bleibt vollstaendig erhalten (Portionsfaktoren, Allergien strikt ausschliessen) – nur die
# Identitaet wird nicht uebertragen. Mit KI_PERSONENNAMEN=1 gilt wieder das alte Verhalten.
KI_PERSONENNAMEN = os.environ.get("KI_PERSONENNAMEN", "0").strip().lower() in ("1", "true", "yes", "on")

# --- Sentry (Fehler-Monitoring, optional) ---
# Secure/konservativ-by-default AUS: ohne DSN wird Sentry gar nicht importiert/initialisiert
# (kein Crash, kein Overhead). Erst mit gesetztem SENTRY_DSN aktiv (Betreiber traegt die DSN
# per Env ein, kein Secret im Code).
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
SENTRY_ENV = os.environ.get("SENTRY_ENV", "staging")
